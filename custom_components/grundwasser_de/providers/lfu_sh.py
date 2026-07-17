"""Schleswig-Holstein groundwater provider (LfU, Umweltgeodienste SH).

Two open, unauthenticated sources (licence: dl-de/by-2.0):

* **stations** — the state WFS 2.0 ``WFS_UWAT``, feature type ``app:gwmn``
  (~733 Landesmessstellen Grundwasserstand). deegree serves it as
  ``application/geo+json`` reprojected to WGS84 (``srsName=EPSG:4326``), so no
  GML parser and no ``pyproj`` are needed. Each feature carries ``Kurznummer``,
  ``Messstellenname`` and a ``Link`` whose ``ms_nr`` is the full
  Messstellenkennzahl (e.g. ``10L02016001``) used for the time series.

* **time series** — the Open-Data groundwater level export. The full
  Messstellenkennzahl keys a Frictionless *table descriptor* at
  ``https://hsi-sh.de/gw/od/<ms_nr>_w_messwerte.json``; its ``path`` is the
  actual CSV (``Datum;Messwert``, m ü. NN, German date + comma decimal). We
  resolve the descriptor, then fetch and parse that CSV.

Stations whose descriptor/CSV is missing return ``value=None`` (the runtime
safety net, same as the other providers).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from aiohttp import ClientError, ClientSession

from ..api import haversine_km
from ._wfs import bbox_urn_4326, get_features
from .base import Provider, ProviderError, ProviderReading, ProviderStation

_LOGGER = logging.getLogger(__name__)

DOMAIN = "lfu_sh"
LABEL = "Schleswig-Holstein (LfU)"

WFS_URL = "https://umweltgeodienste.schleswig-holstein.de/WFS_UWAT"
WFS_TYPE = "app:gwmn"
#: Frictionless descriptor per Messstellenkennzahl -> its CSV ``path``.
DESCRIPTOR_URL = "https://hsi-sh.de/gw/od/{ms_nr}_w_messwerte.json"

UNIT = "m"  # Grundwasserstand in m ü. NN.
ATTRIBUTION = (
    "Datenbasis: Landesamt für Umwelt Schleswig-Holstein (LfU) "
    "– Umweltportal SH / Open Data (dl-de/by-2.0)"
)

#: bounding box over all of Schleswig-Holstein (minLon,minLat,maxLon,maxLat).
_SH_BBOX = bbox_urn_4326(54.2, 9.5, 200)
_HISTORY_LIMIT = 400
_TIMEOUT = 60
_MS_NR_RE = re.compile(r"ms_nr=\s*([0-9A-Za-z]+)")


# --------------------------------------------------------------------------- #
# Pure helpers (no I/O – unit-tested against tests/fixtures/lfu_sh/*).
# --------------------------------------------------------------------------- #
def _kurznummer(value: Any) -> str | None:
    """Normalise a ``Kurznummer`` (often ``"6377.0"``) to a plain id string."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    return text


def ms_nr_from_link(link: str | None) -> str | None:
    """Extract the Messstellenkennzahl (``ms_nr``) from a WFS ``Link`` value."""
    if not link:
        return None
    match = _MS_NR_RE.search(link)
    return match.group(1) if match else None


def parse_stations(features: list[dict]) -> list[dict]:
    """Map WFS GeoJSON features to ``{station_id, name, ms_nr, lat, lon}`` dicts.

    Features without geometry or without a resolvable ``ms_nr`` are skipped.
    """
    out: list[dict] = []
    for feature in features:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        ms_nr = ms_nr_from_link(props.get("Link"))
        kurz = _kurznummer(props.get("Kurznummer"))
        station_id = kurz or ms_nr
        if station_id is None:
            continue
        name = (props.get("Messstellenname") or "").strip() or station_id
        out.append(
            {
                "station_id": station_id,
                "name": name,
                "ms_nr": ms_nr,
                "lat": coords[1],
                "lon": coords[0],
            }
        )
    return out


def parse_csv(text: str) -> list[tuple[datetime, float]]:
    """Parse a ``Datum;Messwert`` groundwater CSV into chronological pairs.

    Dates are German ``dd.mm.yyyy[ HH:MM:SS]``; values use a decimal comma.
    Unparseable rows are skipped.
    """
    samples: list[tuple[datetime, float]] = []
    for line in text.splitlines():
        row = line.strip()
        if not row or ";" not in row:
            continue
        date_raw, _, value_raw = row.partition(";")
        date_raw, value_raw = date_raw.strip(), value_raw.strip()
        if not date_raw or date_raw.lower().startswith("datum"):
            continue
        when = _parse_de_datetime(date_raw)
        if when is None:
            continue
        try:
            value = float(value_raw.replace(",", "."))
        except ValueError:
            continue
        samples.append((when, value))
    samples.sort(key=lambda s: s[0])
    return samples


def _parse_de_datetime(raw: str) -> datetime | None:
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
class LfuShProvider(Provider):
    """Groundwater provider backed by Schleswig-Holstein's WFS + Open-Data CSV."""

    domain = DOMAIN
    label = LABEL

    def __init__(self, session: ClientSession) -> None:
        """Initialise with a shared aiohttp session."""
        self._session = session

    async def async_search_radius(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[ProviderStation]:
        """Return stations within ``radius_km`` (WFS bbox), nearest first."""
        features = await get_features(
            self._session,
            WFS_URL,
            WFS_TYPE,
            bbox=bbox_urn_4326(latitude, longitude, radius_km),
        )
        matches: list[ProviderStation] = []
        for record in parse_stations(features):
            distance = haversine_km(
                latitude, longitude, record["lat"], record["lon"]
            )
            if distance <= radius_km:
                matches.append(self._to_station(record, distance))
        matches.sort(key=lambda s: s.distance_km or 0.0)
        return matches

    async def async_search_query(self, query: str) -> list[ProviderStation]:
        """Return stations whose number or name contains ``query``.

        The WFS has no cheap attribute filter here, so fetch the network once
        (all of SH) and filter client-side.
        """
        features = await get_features(
            self._session, WFS_URL, WFS_TYPE, bbox=_SH_BBOX
        )
        needle = query.strip().casefold()
        matches = [
            self._to_station(record)
            for record in parse_stations(features)
            if needle in record["station_id"].casefold()
            or needle in record["name"].casefold()
        ]
        matches.sort(key=lambda s: s.name)
        return matches

    async def async_fetch(self, station: ProviderStation) -> ProviderReading:
        """Return the latest reading (m ü. NN) and recent history for ``station``."""
        ms_nr = station.extra.get("ms_nr") or station.station_id
        history = await self._fetch_series(ms_nr)
        latest_ts, latest_value = history[-1] if history else (None, None)
        return ProviderReading(
            value=latest_value,
            unit=UNIT,
            timestamp=latest_ts,
            history=history[-_HISTORY_LIMIT:],
            attribution=ATTRIBUTION,
        )

    # -- internals ---------------------------------------------------------- #
    async def _fetch_series(self, ms_nr: str) -> list[tuple[datetime, float]]:
        csv_url = await self._resolve_csv_url(ms_nr)
        if csv_url is None:
            return []
        text = await self._get_text(csv_url)
        return parse_csv(text) if text else []

    async def _resolve_csv_url(self, ms_nr: str) -> str | None:
        """Resolve the Open-Data descriptor for ``ms_nr`` to its CSV ``path``."""
        url = DESCRIPTOR_URL.format(ms_nr=ms_nr)
        try:
            async with self._session.get(url, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    return None
                descriptor = await resp.json(content_type=None)
        except (TimeoutError, ClientError, ValueError) as err:
            raise ProviderError(f"SH descriptor request failed: {err}") from err
        path = descriptor.get("path") if isinstance(descriptor, dict) else None
        return path if isinstance(path, str) and path else None

    async def _get_text(self, url: str) -> str:
        try:
            async with self._session.get(url, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise ProviderError(f"SH CSV HTTP {resp.status}")
                return await resp.text()
        except (TimeoutError, ClientError) as err:
            raise ProviderError(f"SH CSV request failed: {err}") from err

    @staticmethod
    def _to_station(
        record: dict, distance_km: float | None = None
    ) -> ProviderStation:
        return ProviderStation(
            provider=DOMAIN,
            station_id=record["station_id"],
            name=record["name"],
            latitude=record["lat"],
            longitude=record["lon"],
            distance_km=distance_km,
            extra={"ms_nr": record["ms_nr"]} if record.get("ms_nr") else {},
        )
