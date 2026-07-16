"""NIWIS/BfG groundwater provider.

Thin adapter that exposes the existing :class:`~custom_components.niwis.api.
NiwisApiClient` through the common :class:`~.base.Provider` interface, focused on
groundwater (``GRUNDWASSER``). NIWIS is nationwide and — unlike a bare state
network — additionally publishes a low-water *class* and a trend, carried through
in :class:`~.base.ProviderReading`.

Unlike LfU-BB, the NIWIS list endpoint returns coordinates and the current value
for every station in one call, so this provider can serve a radius search
directly (and has no per-station history).
"""

from __future__ import annotations

from ..api import NiwisApiClient, Station, haversine_km
from ..const import ATTRIBUTION, MG_GRUNDWASSER, UNIT_BY_MESSGROESSE
from .base import Provider, ProviderError, ProviderReading, ProviderStation

DOMAIN = "niwis"
LABEL = "NIWIS (Bundesanstalt für Gewässerkunde)"
_UNIT = UNIT_BY_MESSGROESSE[MG_GRUNDWASSER]


def _to_station(station: Station, distance_km: float | None = None) -> ProviderStation:
    """Map an api-layer :class:`Station` to a source-neutral ProviderStation."""
    return ProviderStation(
        provider=DOMAIN,
        station_id=station.nummer,
        name=station.name,
        latitude=station.latitude,
        longitude=station.longitude,
        distance_km=distance_km,
        extra={"messgroesse": MG_GRUNDWASSER},
    )


class NiwisProvider(Provider):
    """Groundwater provider backed by the public NIWIS REST API."""

    domain = DOMAIN
    label = LABEL

    def __init__(self, session) -> None:
        """Initialise with a shared aiohttp session."""
        self._client = NiwisApiClient(session)

    async def _groundwater(self) -> list[Station]:
        return await self._client.async_get_stations(MG_GRUNDWASSER)

    async def async_search_radius(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[ProviderStation]:
        """Return groundwater stations within ``radius_km``, nearest first."""
        matches: list[ProviderStation] = []
        for station in await self._groundwater():
            if station.latitude is None or station.longitude is None:
                continue
            distance = haversine_km(
                latitude, longitude, station.latitude, station.longitude
            )
            if distance <= radius_km:
                matches.append(_to_station(station, distance))
        matches.sort(key=lambda s: s.distance_km or 0.0)
        return matches

    async def async_search_query(self, query: str) -> list[ProviderStation]:
        """Return groundwater stations whose name or number matches ``query``."""
        needle = query.strip().casefold()
        return [
            _to_station(station)
            for station in await self._groundwater()
            if needle in station.name.casefold()
            or needle in station.nummer.casefold()
        ]

    async def async_fetch(self, station: ProviderStation) -> ProviderReading:
        """Return the current groundwater reading (value, class, trend)."""
        for candidate in await self._groundwater():
            if candidate.nummer == station.station_id:
                return ProviderReading(
                    value=candidate.aktueller_messwert,
                    unit=_UNIT,
                    niedrigwasser_klasse=candidate.niedrigwasser_klasse,
                    entwicklung=candidate.entwicklung,
                    attribution=ATTRIBUTION,
                )
        raise ProviderError(f"no NIWIS groundwater station {station.station_id}")
