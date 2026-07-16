"""LfU Brandenburg groundwater provider (Auskunftsplattform Wasser, APW).

The APW (``apw.brandenburg.de``) is a cardoMap3 GIS (IDU). Its groundwater
time series are reachable — without authentication, only a session cookie — via
an AjaxPro control. The full reverse-engineered protocol, with a real captured
payload, is documented in ``docs/research/apw-brandenburg.md``; the fixtures in
``tests/fixtures/lfu_bb/`` are real responses.

Chain used here (MKZ → time series):

1. ``SelectionControl.AxExecuteQuery`` on theme ``256.397`` / layer ``L305``,
   filtering the ``nummer`` (Messstellenkennzahl) column → the internal
   ``msid`` (parsed from the ``id_messstelle=…`` diagram link in the hit HTML).
2. ``MultiExportControl.AxGetAvailableParameterChoice([msid])`` → the
   ``Wasserstand(NHN)`` parameter id (water level in *m ü. NHN*, matching the
   NIWIS groundwater unit).
3. ``MultiExportControl.AxExport(…, format=1)`` → a download link to a ZIP whose
   ``…_messreihen.csv`` holds the series (UTF-8 BOM, ``;``-separated, German
   decimal comma, ``dd.MM.yyyy`` dates).

The radius search uses a bundled station list (MKZ + WGS84 coordinates) derived
offline from the LfU shapefile ``gw_basis_mn.zip`` — the APW station list carries
no coordinates. Fetch then resolves the APW ``msid`` from the MKZ on demand. Note
the APW ``nummer`` does not always equal the shapefile ``MKZ`` (e.g. Münchehofe is
shapefile ``35480874`` but APW ``35480875``, and the latter is a water-quality
well without a level series), so some nearby stations have no fetchable level.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import zipfile
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from aiohttp import ClientError, ClientSession

from ..api import haversine_km
from .base import (
    Provider,
    ProviderError,
    ProviderReading,
    ProviderStation,
)

_LOGGER = logging.getLogger(__name__)

DOMAIN = "lfu_bb"
LABEL = "LfU Brandenburg (Auskunftsplattform Wasser)"

BASE_URL = "https://apw.brandenburg.de"
LANDING_URL = f"{BASE_URL}/?th=ZR_GW_ME"
SELECTION_URL = (
    f"{BASE_URL}/ajaxpro/IDU.cardoMap3.WebV2.Controls.SelectionTools."
    "SelectionControl.SelectionControl,cardo.Map3Lib.ashx"
)
MULTIEXPORT_URL = (
    f"{BASE_URL}/ajaxpro/IDU.cmApp.LFUBRB.Diagramme.Controls."
    "MultiExportControl.MultiExport,IDU.cmApp.LFUBRB.Diagramme.ashx"
)

#: cardoMap theme id + attribute-search column for the groundwater layer L305.
THEME_ID = "256.397"
MKZ_COLUMN = "nummer"
#: AjaxPro ``__type`` discriminator for a string-column iwan comparison filter.
FILTER_TYPE_STRING = (
    "IDU.Core.Web.Controls.SelectionTools.IwanQueryEditor.AxTypes."
    "AxIOComparisonFilterString, IDU.Core, Version=1.0.0.0, "
    "Culture=neutral, PublicKeyToken=107e611434a88619"
)

#: AxExport format enum: 0 = XLSX, 1 = CSV (used here).
EXPORT_FORMAT_CSV = 1
#: zusammenfassungVersion enum: 4 = "EineSpalte" (one value column per station).
EXPORT_SUMMARY_ONE_COLUMN = 4
#: fallback Wasserstand(NHN) parameter id, if name matching fails.
DEFAULT_NHN_PARAMETER = 50503000

UNIT_NHN = "m"  # m ü. NHN – HA-compatible unit, same as NIWIS groundwater.
ATTRIBUTION = (
    "Datenbasis: Landesamt für Umwelt Brandenburg (LfU), "
    "Auskunftsplattform Wasser – apw.brandenburg.de (dl-de/by-2-0)"
)

_TIMEOUT = 90  # seconds; the export renders a file server-side.
_DEFAULT_LOOKBACK_DAYS = 400  # covers even monthly/sparse stations.

_USER_AGENT = (
    "Mozilla/5.0 (compatible; homeassistant-grundwasser-de/0.1; "
    "+https://github.com/hnehnes/niwis)"
)
_MSID_RE = re.compile(r"id_messstelle=(\d+)")
_STATION_RE = re.compile(r"Messstelle:\s*<b>\s*([^,<]+?)\s*,\s*([^<]+?)\s*</b>")
_WCF_DATE_RE = re.compile(r"/Date\((-?\d+)\)/")

#: Bundled station master data (MKZ, name, WGS84 lat/lon) derived offline from
#: the LfU shapefile ``gw_basis_mn.zip`` (EPSG:25833 → WGS84). Shipping it avoids
#: a runtime shapefile download and heavy pyshp/pyproj dependencies. It is the
#: coordinate source for the radius search; the APW station list carries none.
_STATIONS_FILE = Path(__file__).with_name("lfu_bb_stations.json")


@lru_cache(maxsize=1)
def _load_stations() -> list[dict[str, Any]]:
    """Load and cache the bundled LfU station list (blocking file read)."""
    with _STATIONS_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------- #
# Pure helpers (no I/O – unit-tested against tests/fixtures/lfu_bb/*).
# --------------------------------------------------------------------------- #
def to_wcf_date(dt: datetime) -> str:
    """Format a datetime as a WCF ``/Date(ms)/`` string (UTC milliseconds)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    ms = int(dt.timestamp() * 1000)
    return f"/Date({ms})/"


def parse_wcf_date(value: str) -> datetime:
    """Parse a WCF ``/Date(ms)/`` string into an aware UTC datetime."""
    match = _WCF_DATE_RE.search(value or "")
    if not match:
        raise ValueError(f"not a WCF date: {value!r}")
    return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC)


def parse_query_hits(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Extract ``{nummer, name, msid}`` from an ``AxExecuteQuery`` response.

    The station number/name come from the ``Messstelle: <b>NR, NAME</b>`` line
    and the internal id from the ``id_messstelle=…`` diagram link, both in the
    rendered hit HTML.
    """
    value = (payload or {}).get("value") or {}
    results: list[dict[str, str]] = []
    for theme in value.get("singleThemeResult") or []:
        for hit in theme.get("Hits") or []:
            text = hit.get("Text") or ""
            station = _STATION_RE.search(text)
            msid = _MSID_RE.search(text)
            if not station:
                continue
            results.append(
                {
                    "nummer": station.group(1).strip(),
                    "name": station.group(2).strip(),
                    "msid": msid.group(1) if msid else "",
                }
            )
    return results


def pick_nhn_parameter(payload: dict[str, Any]) -> int:
    """Return the ``Wasserstand(NHN)`` parameter id from a parameter-choice reply.

    Prefers a parameter whose name mentions ``NHN`` (the height-system water
    level, in m ü. NHN); falls back to :data:`DEFAULT_NHN_PARAMETER`.
    """
    value = (payload or {}).get("value") or {}
    for param in value.get("parameterAuswahl") or []:
        if "NHN" in (param.get("name") or "").upper():
            return int(param["id"])
    return DEFAULT_NHN_PARAMETER


def parse_messreihen_csv(text: str) -> list[tuple[datetime, float]]:
    """Parse an APW ``…_messreihen.csv`` body into ``(timestamp, value)`` pairs.

    Format: a ``;"Mengendaten"`` line, a ``"Zeitpunkt";"…"`` header, then
    ``dd.MM.yyyy;"value"`` rows with a German decimal comma. Empty values are
    skipped (gaps). Returns samples oldest-first.
    """
    samples: list[tuple[datetime, float]] = []
    reader = csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";")
    for row in reader:
        if len(row) < 2:
            continue
        date_raw, value_raw = row[0].strip(), row[1].strip()
        if not date_raw or date_raw.lower() == "zeitpunkt":
            continue  # header / summary lines
        try:
            when = datetime.strptime(date_raw, "%d.%m.%Y")
        except ValueError:
            continue
        value_raw = value_raw.replace(".", "").replace(",", ".")
        if not value_raw or value_raw == "-":
            continue
        try:
            samples.append((when, float(value_raw)))
        except ValueError:
            continue
    samples.sort(key=lambda s: s[0])
    return samples


def extract_messreihen_from_zip(data: bytes) -> str:
    """Return the ``…_messreihen.csv`` text from an AxExport ZIP (cp1252)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [n for n in archive.namelist() if "messreihen" in n.lower()]
        if not members:
            raise ProviderError("AxExport ZIP contains no messreihen CSV")
        raw = archive.read(members[0])
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
class LfuBbProvider(Provider):
    """Groundwater provider backed by the APW Brandenburg cardoMap3 backend."""

    domain = DOMAIN
    label = LABEL

    def __init__(self, session: ClientSession) -> None:
        """Initialise with a shared aiohttp session (cookies live in its jar)."""
        self._session = session
        self._session_ready = False

    # -- search ------------------------------------------------------------- #
    async def async_search_radius(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[ProviderStation]:
        """Return stations within ``radius_km``, nearest first.

        Coordinates come from the bundled LfU station list; the internal APW
        ``msid`` is resolved lazily on :meth:`async_fetch` (resolving it here
        would mean one APW query per station).
        """
        stations = await asyncio.get_running_loop().run_in_executor(
            None, _load_stations
        )
        matches: list[ProviderStation] = []
        for station in stations:
            distance = haversine_km(
                latitude, longitude, station["lat"], station["lon"]
            )
            if distance <= radius_km:
                matches.append(
                    ProviderStation(
                        provider=DOMAIN,
                        station_id=station["mkz"],
                        name=station["name"] or station["mkz"],
                        latitude=station["lat"],
                        longitude=station["lon"],
                        distance_km=distance,
                    )
                )
        matches.sort(key=lambda s: s.distance_km or 0.0)
        return matches

    async def async_search_query(self, query: str) -> list[ProviderStation]:
        """Find stations whose Messstellenkennzahl (``nummer``) matches ``query``.

        Uses a ``Like`` comparison so a partial MKZ works. (Name search is
        possible via the ``name`` column too, but MKZ is the stable key.)
        """
        payload = await self._execute_query(MKZ_COLUMN, "Like", query.strip())
        stations: list[ProviderStation] = []
        for hit in parse_query_hits(payload):
            extra: dict[str, Any] = {}
            if hit["msid"]:
                extra["msid"] = int(hit["msid"])
            stations.append(
                ProviderStation(
                    provider=DOMAIN,
                    station_id=hit["nummer"],
                    name=hit["name"] or hit["nummer"],
                    extra=extra,
                )
            )
        return stations

    # -- fetch -------------------------------------------------------------- #
    async def async_fetch(self, station: ProviderStation) -> ProviderReading:
        """Return the latest reading and recent history for ``station``."""
        msid = station.extra.get("msid") or await self._resolve_msid(
            station.station_id
        )
        if msid is None:
            # In the shapefile but not queryable in APW's level theme (e.g. a
            # level-only well absent from the "Menge" layer) -> unknown, not a
            # hard error, so a multi-station poll stays healthy.
            _LOGGER.debug("no APW level station for MKZ %s", station.station_id)
            return ProviderReading(value=None, unit=UNIT_NHN, attribution=ATTRIBUTION)
        parameter_id = station.extra.get("parameter_id")
        if parameter_id is None:
            choice = await self._post(
                MULTIEXPORT_URL,
                "AxGetAvailableParameterChoice",
                {"ids": [msid], "blackAndWhiteListings": None},
            )
            parameter_id = pick_nhn_parameter(choice)

        history = await self._export_series(msid, parameter_id)
        latest_ts, latest_value = history[-1] if history else (None, None)
        return ProviderReading(
            value=latest_value,
            unit=UNIT_NHN,
            timestamp=latest_ts,
            history=history,
            attribution=ATTRIBUTION,
        )

    # -- internals ---------------------------------------------------------- #
    async def _ensure_session(self) -> None:
        """Fetch the landing page once so the cardo session cookies are set."""
        if self._session_ready:
            return
        try:
            async with self._session.get(
                LANDING_URL,
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT,
            ) as resp:
                await resp.read()
        except (TimeoutError, ClientError) as err:
            raise ProviderError(f"APW session init failed: {err}") from err
        self._session_ready = True

    async def _post(
        self, url: str, method: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """POST an AjaxPro method call and return the decoded JSON reply."""
        await self._ensure_session()
        headers = {
            "User-Agent": _USER_AGENT,
            "Referer": LANDING_URL,
            "X-AjaxPro-Method": method,
            "Content-Type": "text/plain; charset=UTF-8",
        }
        try:
            async with self._session.post(
                url, data=json.dumps(args), headers=headers, timeout=_TIMEOUT
            ) as resp:
                body = await resp.text()
        except (TimeoutError, ClientError) as err:
            raise ProviderError(f"{method} failed: {err}") from err
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as err:
            raise ProviderError(f"{method}: invalid JSON: {body[:200]}") from err
        if isinstance(payload, dict) and "error" in payload:
            message = (payload["error"] or {}).get("Message", "unknown")
            raise ProviderError(f"{method}: {message}")
        return payload

    async def _execute_query(
        self, column: str, operator: str, value: str
    ) -> dict[str, Any]:
        """Run an ``AxExecuteQuery`` attribute query on the groundwater layer."""
        return await self._post(
            SELECTION_URL,
            "AxExecuteQuery",
            {
                "themeIds": [THEME_ID],
                "filter": {
                    "__type": FILTER_TYPE_STRING,
                    "columnName": column,
                    "compareOperator": operator,
                    "values": [value],
                },
            },
        )

    async def _resolve_msid(self, nummer: str) -> int | None:
        """Resolve a station's internal ``msid`` from its exact MKZ."""
        payload = await self._execute_query(MKZ_COLUMN, "Equal", nummer)
        for hit in parse_query_hits(payload):
            if hit["msid"]:
                return int(hit["msid"])
        return None

    async def _export_series(
        self, msid: int, parameter_id: int, lookback_days: int = _DEFAULT_LOOKBACK_DAYS
    ) -> list[tuple[datetime, float]]:
        """Export the recent series for one station and parse it to samples.

        The window is anchored to the series' actual end (via ``AxGetZeitraum``),
        not to ``now`` — some stations stopped reporting years ago, so a window
        relative to today would come back empty.
        """
        zeitraum = await self._post(
            MULTIEXPORT_URL,
            "AxGetZeitraum",
            {"parameterIds": [parameter_id], "mstIds": [msid]},
        )
        span = (zeitraum or {}).get("value") or {}
        if not span.get("ende"):
            # No data for this parameter at this station (e.g. a water-quality
            # well listed under the level theme but without a level series).
            return []
        try:
            end = parse_wcf_date(span["ende"])
        except ValueError:
            end = datetime.now(tz=UTC)
        begin = end - timedelta(days=lookback_days)
        reply = await self._post(
            MULTIEXPORT_URL,
            "AxExport",
            {
                "parameterIds": [parameter_id],
                "mstIds": [msid],
                "zusammenfassungVersion": EXPORT_SUMMARY_ONE_COLUMN,
                "userBeginn": to_wcf_date(begin),
                "userEnde": to_wcf_date(end),
                "format": EXPORT_FORMAT_CSV,
            },
        )
        link = reply.get("value")
        if not isinstance(link, str) or "ogc.ashx" not in link:
            raise ProviderError(f"AxExport returned no download link: {reply!r}")
        data = await self._download(link)
        return parse_messreihen_csv(extract_messreihen_from_zip(data))

    async def _download(self, path: str) -> bytes:
        """Download the export ZIP from a session-temp link."""
        await self._ensure_session()
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        try:
            async with self._session.get(
                url,
                headers={"User-Agent": _USER_AGENT, "Referer": LANDING_URL},
                timeout=_TIMEOUT,
            ) as resp:
                return await resp.read()
        except (TimeoutError, ClientError) as err:
            raise ProviderError(f"export download failed: {err}") from err
