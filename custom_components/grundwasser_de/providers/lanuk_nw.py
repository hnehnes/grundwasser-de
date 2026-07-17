"""North Rhine-Westphalia groundwater provider (LANUK, OpenHygrisC).

NRW publishes its groundwater data as the open **OpenHygrisC** bulk export
(``opengeodata.nrw.de``, dl-de/zero-2.0 — no login, unrestricted). There is no
per-station live endpoint (ELWAS-WEB is a session-bound JSF app), so the split
mirrors :mod:`.lfu_bb`:

* **search** — served from a bundled station list built offline by
  ``scripts/build_lanuk_nw_stations.py`` from the *messstelle* CSV
  (``E32``/``N32`` EPSG:25832 → WGS84). Only stations that publish both their
  location and their water level *and* actually carry a value in the current
  water-level file are kept, so search offers only stations that return data.
* **fetch** — reads the latest value from the water-level file
  ``OpenHygrisC_gw-wasserstand_2020-2029_…zip``. That file is a single ~255 MB
  ZIP holding ~3.5 M station-days (all NRW stations) and is refreshed **monthly**
  (``datum_messung`` runs to within a few weeks of *today*). Downloading it per
  poll is out of the question, so the reduced *latest value per station* snapshot
  is cached module-wide behind a lock (:data:`_SNAPSHOT_TTL`, default 12 h) and
  shared across every station and config entry — one download serves them all,
  and even at the shortest sensible cache age it is fetched only ~twice a day
  while the source itself only changes monthly. The reduction streams the ZIP
  from a temp file so peak memory stays at the ~few-thousand-entry result dict,
  not the 255 MB payload.

Unit is ``WASSERSTD_M`` (Grundwasseroberfläche in m NHN2016) = m ü. NHN, matching
the other providers. History is intentionally not retained: keeping a per-station
series for all ~3.5 M rows resident would dwarf the value it adds over the daily/
monthly cadence of the bulk snapshot; :class:`ProviderReading` carries the latest
value only.

Docs / license: https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/grundwasser/hygrisc/
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
import logging
import os
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from math import cos, radians
from pathlib import Path
from typing import Any

from aiohttp import ClientError, ClientSession

from ..api import haversine_km
from .base import Provider, ProviderError, ProviderReading, ProviderStation

_LOGGER = logging.getLogger(__name__)

DOMAIN = "lanuk_nw"
LABEL = "Nordrhein-Westfalen (LANUK)"

BASE = (
    "https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/grundwasser/hygrisc"
)
#: current-decade water-level bulk (all NRW stations, refreshed monthly).
WASSERSTAND_URL = f"{BASE}/OpenHygrisC_gw-wasserstand_2020-2029_EPSG25832_CSV.zip"

UNIT = "m"  # WASSERSTD_M – Grundwasseroberfläche in m NHN2016, i.e. m ü. NHN.
ATTRIBUTION = (
    "Datenbasis: Land NRW / Landesamt für Natur, Umwelt und Klima (LANUK) – "
    "OpenHygrisC, opengeodata.nrw.de (dl-de/zero-2.0)"
)

#: Bundled station master data — ``{id, name, lat, lon, gemeinde}`` per station —
#: built offline by ``scripts/build_lanuk_nw_stations.py``. Shipping it avoids a
#: runtime 29 MB messstelle-CSV download and the pyproj dependency (used only in
#: the build script for the EPSG:25832 → WGS84 conversion).
_STATIONS_FILE = Path(__file__).with_name("lanuk_nw_stations.json")

#: How long a reduced snapshot is reused before re-checking the source. The
#: re-check is a cheap HEAD; the ~244 MB bulk is only re-downloaded when its
#: ``Last-Modified`` actually changes (the source updates monthly).
_SNAPSHOT_TTL = timedelta(hours=12)
_DOWNLOAD_TIMEOUT = 600  # the water-level ZIP is large (~255 MB).
_TIMEOUT = 60  # for the lightweight Last-Modified HEAD check.
_CHUNK = 1 << 20  # 1 MiB stream chunks.

_USER_AGENT = (
    "Mozilla/5.0 (compatible; homeassistant-grundwasser-de/0.1; "
    "+https://github.com/hnehnes/niwis)"
)

# Module-wide reduced snapshot (``station_id -> (timestamp, value)``), shared
# across provider instances so the 255 MB bulk is fetched at most once per TTL.
_snapshot: dict[str, tuple[datetime, float]] | None = None
_snapshot_time: datetime | None = None
#: ``Last-Modified`` of the bulk the current snapshot was reduced from, so a
#: refresh can skip the 244 MB download when the monthly file is unchanged.
_snapshot_last_modified: str | None = None
_snapshot_lock = asyncio.Lock()


@lru_cache(maxsize=1)
def _load_stations() -> list[dict[str, Any]]:
    """Load and cache the bundled NRW station list (blocking file read)."""
    with _STATIONS_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------- #
# Pure helpers (no network – unit-tested against tests/fixtures/lanuk_nw/*).
# --------------------------------------------------------------------------- #
def parse_value(raw: str) -> float | None:
    """Parse an OpenHygrisC ``wasserstd_m`` cell (German decimal comma)."""
    raw = (raw or "").strip()
    if not raw or raw == "-":
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def parse_date(raw: str) -> datetime | None:
    """Parse an OpenHygrisC ``datum_messung`` cell (``YYYY-MM-DD``)."""
    raw = (raw or "").strip()
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None


def reduce_latest(lines: Any) -> dict[str, tuple[datetime, float]]:
    """Reduce water-level rows to the newest ``(timestamp, value)`` per station.

    ``lines`` is any iterable of text lines (a file object or a list): the
    semicolon-separated OpenHygrisC ``gw-wasserstand`` table with a header row.
    Rows whose value or date does not parse (empty, ``-``, ``trocken`` …) are
    ignored; the newest ``datum_messung`` per ``messstelle_id`` wins.
    """
    reader = csv.reader(lines, delimiter=";")
    try:
        header = next(reader)
    except StopIteration:
        return {}
    idx = {name: i for i, name in enumerate(header)}
    try:
        mi, di, wi = (
            idx["messstelle_id"],
            idx["datum_messung"],
            idx["wasserstd_m"],
        )
    except KeyError as err:
        raise ProviderError(f"unexpected wasserstand header: {header}") from err

    latest: dict[str, tuple[datetime, float]] = {}
    top = max(mi, di, wi)
    for row in reader:
        if len(row) <= top:
            continue
        value = parse_value(row[wi])
        when = parse_date(row[di])
        if value is None or when is None:
            continue
        station_id = row[mi].strip()
        current = latest.get(station_id)
        if current is None or when > current[0]:
            latest[station_id] = (when, value)
    return latest


def reduce_zip_file(path: str) -> dict[str, tuple[datetime, float]]:
    """Reduce the water-level ZIP at ``path`` to a latest-per-station snapshot."""
    with zipfile.ZipFile(path) as archive:
        members = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not members:
            raise ProviderError("wasserstand ZIP contains no CSV")
        with archive.open(members[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            return reduce_latest(text)


def bbox_deltas(lat: float, radius_km: float) -> tuple[float, float]:
    """Return ``(d_lat, d_lon)`` degree half-spans covering ``radius_km``."""
    d_lat = radius_km / 111.0
    d_lon = radius_km / (111.0 * max(cos(radians(lat)), 0.01))
    return d_lat, d_lon


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
class LanukNwProvider(Provider):
    """Groundwater provider backed by NRW's OpenHygrisC bulk export."""

    domain = DOMAIN
    label = LABEL

    def __init__(self, session: ClientSession) -> None:
        """Initialise with a shared aiohttp session (used only on fetch)."""
        self._session = session

    # -- search ------------------------------------------------------------- #
    async def async_search_radius(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[ProviderStation]:
        """Return stations within ``radius_km``, nearest first (bundled list)."""
        stations = await asyncio.get_running_loop().run_in_executor(
            None, _load_stations
        )
        d_lat, d_lon = bbox_deltas(latitude, radius_km)
        matches: list[ProviderStation] = []
        for station in stations:
            lat, lon = station["lat"], station["lon"]
            # cheap bounding-box reject before the haversine.
            if abs(lat - latitude) > d_lat or abs(lon - longitude) > d_lon:
                continue
            distance = haversine_km(latitude, longitude, lat, lon)
            if distance <= radius_km:
                matches.append(self._to_station(station, distance))
        matches.sort(key=lambda s: s.distance_km or 0.0)
        return matches

    async def async_search_query(self, query: str) -> list[ProviderStation]:
        """Return stations whose id or name contains ``query`` (bundled list)."""
        stations = await asyncio.get_running_loop().run_in_executor(
            None, _load_stations
        )
        needle = query.strip().casefold()
        matches = [
            self._to_station(station)
            for station in stations
            if needle in station["id"].casefold()
            or needle in (station["name"] or "").casefold()
        ]
        matches.sort(key=lambda s: s.name)
        return matches

    # -- fetch -------------------------------------------------------------- #
    async def async_fetch(self, station: ProviderStation) -> ProviderReading:
        """Return the latest published value for ``station`` from the snapshot."""
        snapshot = await self._ensure_snapshot()
        record = snapshot.get(station.station_id)
        if record is None:
            # In the bundle but not in the current-decade file (e.g. no recent
            # measurement) -> unknown, not an error, so a multi-station poll
            # stays healthy.
            _LOGGER.debug("no current NRW value for station %s", station.station_id)
            return ProviderReading(value=None, unit=UNIT, attribution=ATTRIBUTION)
        timestamp, value = record
        return ProviderReading(
            value=value,
            unit=UNIT,
            timestamp=timestamp,
            attribution=ATTRIBUTION,
        )

    # -- internals ---------------------------------------------------------- #
    @staticmethod
    def _to_station(
        station: dict[str, Any], distance_km: float | None = None
    ) -> ProviderStation:
        return ProviderStation(
            provider=DOMAIN,
            station_id=station["id"],
            name=station["name"] or station["id"],
            latitude=station["lat"],
            longitude=station["lon"],
            distance_km=distance_km,
        )

    async def _ensure_snapshot(self) -> dict[str, tuple[datetime, float]]:
        """Return the reduced snapshot, refreshing from the bulk only if changed.

        Within the TTL the cached snapshot is reused. After the TTL a cheap HEAD
        compares the bulk's ``Last-Modified`` against the snapshot's; the ~244 MB
        download only happens when it actually changed (the source is monthly).
        """
        global _snapshot, _snapshot_time, _snapshot_last_modified
        async with _snapshot_lock:
            now = datetime.now(UTC)
            if (
                _snapshot is not None
                and _snapshot_time is not None
                and now - _snapshot_time < _SNAPSHOT_TTL
            ):
                return _snapshot

            remote_lm = await self._remote_last_modified()
            unchanged = (
                remote_lm is not None and remote_lm == _snapshot_last_modified
            )
            if _snapshot is not None and (unchanged or remote_lm is None):
                # Monthly file unchanged (or HEAD failed) -> keep the snapshot,
                # just reset the TTL; no 244 MB download.
                _snapshot_time = now
                return _snapshot

            path = await self._download_bulk()
            try:
                snapshot = await asyncio.get_running_loop().run_in_executor(
                    None, reduce_zip_file, path
                )
            finally:
                await asyncio.get_running_loop().run_in_executor(
                    None, _unlink_quietly, path
                )
            _snapshot = snapshot
            _snapshot_time = now
            _snapshot_last_modified = remote_lm
            _LOGGER.debug("NRW snapshot refreshed: %d stations", len(snapshot))
            return snapshot

    async def _remote_last_modified(self) -> str | None:
        """Return the bulk's ``Last-Modified`` via a HEAD, or ``None`` on failure."""
        try:
            async with self._session.head(
                WASSERSTAND_URL,
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT,
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    return None
                return resp.headers.get("Last-Modified")
        except (TimeoutError, ClientError):
            return None

    async def _download_bulk(self) -> str:
        """Stream the water-level ZIP to a temp file and return its path."""
        fd, path = tempfile.mkstemp(prefix="lanuk_nw_", suffix=".zip")
        os.close(fd)
        try:
            async with self._session.get(
                WASSERSTAND_URL,
                headers={"User-Agent": _USER_AGENT},
                timeout=_DOWNLOAD_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    raise ProviderError(f"OpenHygrisC HTTP {resp.status}")
                with open(path, "wb") as handle:
                    async for chunk in resp.content.iter_chunked(_CHUNK):
                        handle.write(chunk)
        except (TimeoutError, ClientError) as err:
            _unlink_quietly(path)
            raise ProviderError(f"OpenHygrisC download failed: {err}") from err
        except ProviderError:
            _unlink_quietly(path)
            raise
        return path


def _unlink_quietly(path: str) -> None:
    """Remove ``path`` ignoring a missing file."""
    with contextlib.suppress(OSError):
        os.unlink(path)
