"""Hamburg groundwater provider (BUKEA, Urban Data Platform).

Backed by the open **OGC API – Features** service (no login, CC0). One dataset
serves everything: each feature is one station-day (``messstellennummer`` +
coordinates + ``wasserstand_mnhn`` in m ü. NHN + ``datum_as_date``), so:

* **search** — a ``bbox`` query sorted by newest date, de-duplicated to the
  latest record per station, yields nearby stations with their current value
  (Hamburg has only ~40 stations, so this is one cheap request).
* **fetch** — filtering by ``messstellennummer`` (newest first) yields a
  station's recent series.

Docs: https://api.hamburg.de/datasets/v1/grundwassermessstellen/
"""

from __future__ import annotations

import logging
from datetime import datetime
from math import cos, radians
from typing import Any

from aiohttp import ClientError, ClientSession

from ..api import haversine_km
from .base import Provider, ProviderError, ProviderReading, ProviderStation

_LOGGER = logging.getLogger(__name__)

DOMAIN = "bukea_hh"
LABEL = "Hamburg (BUKEA)"

BASE_ITEMS = (
    "https://api.hamburg.de/datasets/v1/grundwassermessstellen"
    "/collections/grundwassermessstellen/items"
)
UNIT = "m"  # wasserstand_mnhn – m ü. NHN, matches the other providers.
ATTRIBUTION = (
    "Datenbasis: Freie und Hansestadt Hamburg, Behörde für Umwelt, Klima, "
    "Energie und Agrarwirtschaft (BUKEA) – Urban Data Platform (CC0)"
)

#: Bounding box over all of Hamburg (minLon,minLat,maxLon,maxLat, WGS84) for the
#: free-text search, which has no per-station index to query.
_HH_BBOX = (9.5, 53.35, 10.4, 53.8)
#: enough recent station-days to cover every station at least once on search.
_SEARCH_LIMIT = 6000
#: recent history depth per station on fetch.
_HISTORY_LIMIT = 400
_TIMEOUT = 60


# --------------------------------------------------------------------------- #
# Pure helpers (no I/O – unit-tested against tests/fixtures/bukea_hh/*).
# --------------------------------------------------------------------------- #
def _feature_value(props: dict[str, Any]) -> float | None:
    value = props.get("wasserstand_mnhn")
    return float(value) if isinstance(value, (int, float)) else None


def _feature_name(props: dict[str, Any]) -> str:
    return (props.get("messstellenbezeichnung") or "").strip() or (
        f"Messstelle {props.get('messstellennummer')}"
    )


def latest_per_station(features: list[dict]) -> list[dict]:
    """Reduce newest-first station-day features to one record per station.

    Returns ``{station_id, name, lat, lon, value, timestamp}`` dicts; the first
    occurrence of each ``messstellennummer`` (newest, given ``sortby=-date``) wins.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for feature in features:
        props = feature.get("properties") or {}
        number = props.get("messstellennummer")
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if number is None or len(coords) < 2 or str(number) in seen:
            continue
        seen.add(str(number))
        out.append(
            {
                "station_id": str(number),
                "name": _feature_name(props),
                "lat": coords[1],
                "lon": coords[0],
                "value": _feature_value(props),
                "timestamp": props.get("datum_as_date"),
            }
        )
    return out


def parse_series(features: list[dict]) -> list[tuple[datetime, float]]:
    """Parse station-day features into chronological ``(timestamp, value)`` pairs."""
    samples: list[tuple[datetime, float]] = []
    for feature in features:
        props = feature.get("properties") or {}
        value = _feature_value(props)
        date_raw = props.get("datum_as_date")
        if value is None or not date_raw:
            continue
        try:
            when = datetime.strptime(date_raw, "%Y-%m-%d")
        except ValueError:
            continue
        samples.append((when, value))
    samples.sort(key=lambda s: s[0])
    return samples


def bbox_around(lat: float, lon: float, radius_km: float) -> str:
    """Return a WGS84 ``minLon,minLat,maxLon,maxLat`` box covering the radius."""
    d_lat = radius_km / 111.0
    d_lon = radius_km / (111.0 * max(cos(radians(lat)), 0.01))
    return f"{lon - d_lon},{lat - d_lat},{lon + d_lon},{lat + d_lat}"


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
class BukeaHhProvider(Provider):
    """Groundwater provider backed by Hamburg's OGC API – Features service."""

    domain = DOMAIN
    label = LABEL

    def __init__(self, session: ClientSession) -> None:
        """Initialise with a shared aiohttp session."""
        self._session = session

    async def async_search_radius(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[ProviderStation]:
        """Return stations within ``radius_km``, nearest first, with coordinates."""
        features = await self._get(
            bbox=bbox_around(latitude, longitude, radius_km),
            sortby="-datum_as_date",
            limit=_SEARCH_LIMIT,
        )
        matches: list[ProviderStation] = []
        for record in latest_per_station(features):
            distance = haversine_km(
                latitude, longitude, record["lat"], record["lon"]
            )
            if distance <= radius_km:
                matches.append(self._to_station(record, distance))
        matches.sort(key=lambda s: s.distance_km or 0.0)
        return matches

    async def async_search_query(self, query: str) -> list[ProviderStation]:
        """Return stations whose number or name contains ``query``."""
        features = await self._get(
            bbox=",".join(str(v) for v in _HH_BBOX),
            sortby="-datum_as_date",
            limit=_SEARCH_LIMIT,
        )
        needle = query.strip().casefold()
        matches = [
            self._to_station(record)
            for record in latest_per_station(features)
            if needle in record["station_id"].casefold()
            or needle in record["name"].casefold()
        ]
        matches.sort(key=lambda s: s.name)
        return matches

    async def async_fetch(self, station: ProviderStation) -> ProviderReading:
        """Return the latest reading and recent history for ``station``."""
        features = await self._get(
            messstellennummer=station.station_id,
            sortby="-datum_as_date",
            limit=_HISTORY_LIMIT,
        )
        history = parse_series(features)
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
    def _to_station(record: dict, distance_km: float | None = None) -> ProviderStation:
        return ProviderStation(
            provider=DOMAIN,
            station_id=record["station_id"],
            name=record["name"],
            latitude=record["lat"],
            longitude=record["lon"],
            distance_km=distance_km,
        )

    async def _get(self, **params: Any) -> list[dict]:
        """GET the items endpoint and return the GeoJSON feature list."""
        query = {"f": "json", **params}
        try:
            async with self._session.get(
                BASE_ITEMS, params=query, timeout=_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    raise ProviderError(f"HH API HTTP {resp.status}")
                payload = await resp.json(content_type=None)
        except (TimeoutError, ClientError) as err:
            raise ProviderError(f"HH API request failed: {err}") from err
        return payload.get("features") or []
