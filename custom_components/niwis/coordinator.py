"""DataUpdateCoordinator for the NIWIS integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NiwisApiClient, NiwisApiError, Station, build_display_name
from .const import (
    CONF_KLASSIFIKATIONSART,
    CONF_SCAN_INTERVAL,
    CONF_STATION_MESSGROESSEN,
    CONF_STATION_NAME,
    CONF_STATION_NUMMER,
    CONF_STATIONS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    KLASS_DYNAMISCH,
)

_LOGGER = logging.getLogger(__name__)

type NiwisConfigEntry = ConfigEntry[NiwisCoordinator]


class NiwisCoordinator(DataUpdateCoordinator[dict[str, dict[str, Station]]]):
    """Polls every selected station in a single batch per measurement type."""

    config_entry: NiwisConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NiwisConfigEntry) -> None:
        """Initialise the coordinator from a config entry."""
        options = entry.options
        klass = options.get(CONF_KLASSIFIKATIONSART, KLASS_DYNAMISCH)
        hours = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_HOURS)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(hours=hours),
        )
        self.client = NiwisApiClient(
            async_get_clientsession(hass), klassifikationsart=klass
        )
        # Per-station master data (Stammdaten) for speaking device names,
        # loaded once at setup: {nummer: {"name": str, "details": dict}}.
        self.station_meta: dict[str, dict] = {}

    async def async_load_metadata(self) -> None:
        """Fetch master data for the selected stations to build device names.

        Best-effort and non-fatal: a station without reachable Stammdaten
        keeps its map name. Runs once per setup, not on every poll.
        """
        meta: dict[str, dict] = {}
        for station in self.selected_stations:
            nummer = station[CONF_STATION_NUMMER]
            messgroessen = station.get(CONF_STATION_MESSGROESSEN, [])
            fallback = station.get(CONF_STATION_NAME, nummer)
            details: dict = {}
            if messgroessen:
                details = await self.client.async_get_station_details(
                    messgroessen[0], nummer
                )
            meta[nummer] = {
                "name": build_display_name(details, fallback, messgroessen),
                "details": details,
            }
        self.station_meta = meta

    def station_name(self, nummer: str, fallback: str) -> str:
        """Return the speaking name for a station, or the fallback."""
        return self.station_meta.get(nummer, {}).get("name") or fallback

    @property
    def _needed_messgroessen(self) -> list[str]:
        """Return the union of measurement types across all selected stations."""
        needed: set[str] = set()
        for station in self.config_entry.data.get(CONF_STATIONS, []):
            needed.update(station.get(CONF_STATION_MESSGROESSEN, []))
        return sorted(needed)

    async def _async_update_data(self) -> dict[str, dict[str, Station]]:
        """Fetch all needed measurement-type lists once and index by station."""
        messgroessen = self._needed_messgroessen
        if not messgroessen:
            return {}
        try:
            return await self.client.async_get_stations_map(messgroessen)
        except NiwisApiError as err:
            raise UpdateFailed(str(err)) from err

    def get_station(self, messgroesse: str, nummer: str) -> Station | None:
        """Return the current reading for a station, if present in the data."""
        return (self.data or {}).get(messgroesse, {}).get(nummer)

    @property
    def selected_stations(self) -> list[dict]:
        """Return the configured station descriptors."""
        return list(self.config_entry.data.get(CONF_STATIONS, []))

    def known_nummern(self) -> set[str]:
        """Return the set of configured station numbers."""
        return {
            s[CONF_STATION_NUMMER]
            for s in self.config_entry.data.get(CONF_STATIONS, [])
        }
