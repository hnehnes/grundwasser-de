"""Berlin groundwater provider (Wasserportal Berlin).

Backed by the public **Wasserportal Berlin** PHP endpoints (no login, standard
UA). The groundwater theme (``thema=gws``) exposes ~893 stations. The station
table carries no coordinates, so — like the LfU-Brandenburg provider — the
radius/name search runs against a **bundled** station list built offline (see
``scripts/build_wasserportal_be_stations.py``), which resolves each station's
UTM33 coordinates once and stores them as WGS84.

Fetch downloads a per-station daily CSV
(``station.php?anzeige=d&…&smode=c``): a metadata block, then a
``Datum;"GW-Stand (m ü. NHN)"`` header and ``dd.mm.yyyy;value`` rows in
ISO-8859 with a German decimal comma. Values in *m ü. NHN* match the other
providers' unit.

Docs: https://wasserportal.berlin.de/ (Thema Grundwasserstand = ``gws``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from aiohttp import ClientError, ClientSession

from ..api import haversine_km
from .base import Provider, ProviderError, ProviderReading, ProviderStation

_LOGGER = logging.getLogger(__name__)

DOMAIN = "wasserportal_be"
LABEL = "Berlin (Wasserportal)"

BASE_URL = "https://wasserportal.berlin.de"
UNIT = "m"  # GW-Stand in m ü. NHN, matching the other providers.
ATTRIBUTION = (
    "Datenbasis: Wasserportal Berlin, Senatsverwaltung für Mobilität, Verkehr, "
    "Klimaschutz und Umwelt (dl-de/by-2.0)"
)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; homeassistant-grundwasser-de/0.1; "
    "+https://github.com/hnehnes/niwis)"
)
_TIMEOUT = 60
#: recent history depth per station on fetch (days).
_LOOKBACK_DAYS = 400
_CSV_ENCODING = "iso-8859-15"

#: a ``dd.mm.yyyy;value`` data row (skips the metadata / header lines).
_ROW_RE = re.compile(r"^(\d{2}\.\d{2}\.\d{4});(.*)$")

#: Bundled station master data — ``{station_id, name, lat, lon}`` per station —
#: built offline by ``scripts/build_wasserportal_be_stations.py`` (the portal's
#: station table carries no coordinates; the builder resolves each station's
#: UTM33 coordinates and stores them as WGS84). Shipping it keeps the radius
#: search a pure in-memory haversine, with no per-station coordinate lookup.
_STATIONS_FILE = Path(__file__).with_name("wasserportal_be_stations.json")


@lru_cache(maxsize=1)
def _load_stations() -> list[dict[str, Any]]:
    """Load and cache the bundled Berlin station list (blocking file read)."""
    with _STATIONS_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------- #
# Pure helpers (no I/O – unit-tested against tests/fixtures/wasserportal_be/*).
# --------------------------------------------------------------------------- #
def parse_gws_csv(text: str) -> list[tuple[datetime, float]]:
    """Parse a Wasserportal ``gws`` daily CSV into ``(timestamp, value)`` pairs.

    The body starts with a semicolon-separated metadata block and a
    ``Datum;"GW-Stand (m ü. NHN)"`` header, followed by ``dd.mm.yyyy;value``
    rows with a German decimal comma. Metadata/header lines and empty/``-``
    values are skipped. Returns samples oldest-first.
    """
    samples: list[tuple[datetime, float]] = []
    for line in text.splitlines():
        match = _ROW_RE.match(line.strip())
        if not match:
            continue
        date_raw, value_raw = match.group(1), match.group(2)
        value_raw = value_raw.strip().strip('"').replace(",", ".")
        if not value_raw or value_raw == "-":
            continue
        try:
            when = datetime.strptime(date_raw, "%d.%m.%Y")
            value = float(value_raw)
        except ValueError:
            continue
        samples.append((when, value))
    samples.sort(key=lambda sample: sample[0])
    return samples


def build_csv_url(station_id: str, start: datetime, end: datetime) -> str:
    """Return the daily-CSV export URL for a station over ``[start, end]``."""
    return (
        f"{BASE_URL}/station.php?anzeige=d&station={station_id}&thema=gws"
        "&exportthema=gw&sreihe=ew&smode=c"
        f"&sdatum={start:%d.%m.%Y}&senddatum={end:%d.%m.%Y}"
    )


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
class WasserportalBeProvider(Provider):
    """Groundwater provider backed by Wasserportal Berlin's PHP endpoints."""

    domain = DOMAIN
    label = LABEL

    def __init__(self, session: ClientSession) -> None:
        """Initialise with a shared aiohttp session."""
        self._session = session

    # -- search ------------------------------------------------------------- #
    async def async_search_radius(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[ProviderStation]:
        """Return stations within ``radius_km``, nearest first, from the bundle."""
        stations = await asyncio.get_running_loop().run_in_executor(
            None, _load_stations
        )
        matches: list[ProviderStation] = []
        for station in stations:
            distance = haversine_km(
                latitude, longitude, station["lat"], station["lon"]
            )
            if distance <= radius_km:
                matches.append(self._to_station(station, distance))
        matches.sort(key=lambda s: s.distance_km or 0.0)
        return matches

    async def async_search_query(self, query: str) -> list[ProviderStation]:
        """Return bundle stations whose id or name contains ``query``."""
        stations = await asyncio.get_running_loop().run_in_executor(
            None, _load_stations
        )
        needle = query.strip().casefold()
        matches = [
            self._to_station(station)
            for station in stations
            if needle in station["station_id"].casefold()
            or needle in station["name"].casefold()
        ]
        matches.sort(key=lambda s: s.name)
        return matches

    # -- fetch -------------------------------------------------------------- #
    async def async_fetch(self, station: ProviderStation) -> ProviderReading:
        """Return the latest reading and recent history for ``station``."""
        end = datetime.now()
        start = end - timedelta(days=_LOOKBACK_DAYS)
        url = build_csv_url(station.station_id, start, end)
        text = await self._download_csv(url)
        history = parse_gws_csv(text)
        latest_ts, latest_value = history[-1] if history else (None, None)
        return ProviderReading(
            value=latest_value,
            unit=UNIT,
            timestamp=latest_ts,
            history=history,
            attribution=ATTRIBUTION,
        )

    # -- internals ---------------------------------------------------------- #
    @staticmethod
    def _to_station(
        record: dict[str, Any], distance_km: float | None = None
    ) -> ProviderStation:
        return ProviderStation(
            provider=DOMAIN,
            station_id=str(record["station_id"]),
            name=record["name"] or f"GWM {record['station_id']}",
            latitude=record["lat"],
            longitude=record["lon"],
            distance_km=distance_km,
        )

    async def _download_csv(self, url: str) -> str:
        """GET a daily-CSV export and decode it (ISO-8859-15)."""
        try:
            async with self._session.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    raise ProviderError(f"Wasserportal HTTP {resp.status}")
                raw = await resp.read()
        except (TimeoutError, ClientError) as err:
            raise ProviderError(f"Wasserportal request failed: {err}") from err
        return raw.decode(_CSV_ENCODING, errors="replace")
