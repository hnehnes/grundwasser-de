"""Asynchronous client for the NIWIS REST backend.

Thin wrapper around the verified endpoints documented in :mod:`.const`. The
client never manages its own session – it is handed the shared Home Assistant
``aiohttp`` session by the caller.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import (
    API_BASE,
    API_TIMEOUT,
    DETAIL_PATH_BY_MESSGROESSE,
    KLASS_DYNAMISCH,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
    "Referer": "https://niwis-online.de/",
}


class NiwisApiError(Exception):
    """Raised when the NIWIS API cannot be reached or returns an error."""


@dataclass(slots=True)
class Station:
    """A NIWIS measuring station reading for a single measurement type."""

    nummer: str
    name: str
    messgroesse: str
    latitude: float | None
    longitude: float | None
    aktueller_messwert: float | None
    niedrigwasser_klasse: str | None
    entwicklung: str | None
    pegel_unter_glw: float | None = None
    anzahl_tage_unter_glw: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, messgroesse: str, data: dict[str, Any]) -> Station:
        """Build a :class:`Station` from a raw list-endpoint object."""
        koord = data.get("koordinate") or {}
        return cls(
            nummer=data["nummer"],
            name=data.get("anzeigeName") or data["nummer"],
            messgroesse=messgroesse,
            latitude=koord.get("y"),
            longitude=koord.get("x"),
            aktueller_messwert=data.get("aktuellerMesswert"),
            niedrigwasser_klasse=data.get("niedrigwasserKlasse"),
            entwicklung=data.get("entwicklung"),
            pegel_unter_glw=data.get("pegelUnterGlw"),
            anzahl_tage_unter_glw=data.get("anzahlTageUnterGlw"),
            raw=data,
        )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two WGS84 points in kilometres."""
    r = 6371.0088
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return 2 * r * asin(sqrt(a))


def build_display_name(
    details: dict[str, Any], fallback: str, messgroessen: list[str]
) -> str:
    """Build a human-friendly station name from its master data (Stammdaten).

    * Groundwater / spring stations often carry only a bare number as their
      map label, so the location (``ortslage``) is far more descriptive.
    * Surface-water stations get their gauge name plus the water body
      (``gewaesser``), e.g. ``"Woltersdorf OP (Rüdersdorfer)"``.

    Falls back to the map name if the master data lacks the relevant fields.
    """
    ortslage = (details.get("ortslage") or "").strip()
    gewaesser = (details.get("gewaesser") or "").strip()
    base = (details.get("name") or fallback or "").strip()
    is_groundwater = any(
        mg in ("GRUNDWASSER", "QUELLSCHUETTUNG") for mg in messgroessen
    )

    if is_groundwater and ortslage:
        return ortslage
    if gewaesser and gewaesser.casefold() not in base.casefold():
        return f"{base} ({gewaesser})"
    return base or fallback


class NiwisApiClient:
    """Client for the public NIWIS REST API."""

    def __init__(
        self,
        session: ClientSession,
        klassifikationsart: str = KLASS_DYNAMISCH,
    ) -> None:
        """Initialise the client with a shared aiohttp session."""
        self._session = session
        self._klassifikationsart = klassifikationsart

    async def _get_json(self, path: str, **params: Any) -> Any:
        """Perform a GET request and return the decoded JSON body."""
        url = f"{API_BASE}/{path}"
        try:
            async with self._session.get(
                url,
                params=params or None,
                headers=_HEADERS,
                timeout=API_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise NiwisApiError(
                        f"GET {url} -> HTTP {resp.status}: {text[:200]}"
                    )
                return await resp.json(content_type=None)
        except (TimeoutError, ClientError) as err:
            raise NiwisApiError(f"GET {url} failed: {err}") from err

    async def async_get_config(self) -> dict[str, Any]:
        """Return the backend configuration (reference period, defaults)."""
        return await self._get_json("config")

    async def async_get_stations(self, messgroesse: str) -> list[Station]:
        """Return every station of ``messgroesse`` with its current reading."""
        payload = await self._get_json(
            f"karte/messstelle/{messgroesse}",
            klassifikationsart=self._klassifikationsart,
        )
        if not isinstance(payload, list):
            raise NiwisApiError(
                f"Unexpected payload for {messgroesse}: {type(payload).__name__}"
            )
        return [Station.from_payload(messgroesse, item) for item in payload]

    async def async_get_stations_map(
        self, messgroessen: list[str]
    ) -> dict[str, dict[str, Station]]:
        """Fetch several measurement types concurrently.

        Returns a mapping ``{messgroesse: {nummer: Station}}``.
        """
        results = await asyncio.gather(
            *(self.async_get_stations(mg) for mg in messgroessen)
        )
        return {
            mg: {station.nummer: station for station in stations}
            for mg, stations in zip(messgroessen, results, strict=True)
        }

    async def async_get_station_details(
        self, messgroesse: str, nummer: str
    ) -> dict[str, Any]:
        """Return the static master data (Stammdaten) for a station."""
        segment = DETAIL_PATH_BY_MESSGROESSE.get(messgroesse)
        if segment is None:
            return {}
        try:
            return await self._get_json(f"karte/{segment}/{nummer}")
        except NiwisApiError as err:
            # Details are best-effort enrichment only.
            _LOGGER.debug("No details for %s/%s: %s", messgroesse, nummer, err)
            return {}
