"""Provider-neutral DataUpdateCoordinator for the groundwater integration.

Each configured station names a ``provider`` (NIWIS, LfU-BB, …) and a native
``station_id``; the coordinator fans out one :meth:`Provider.async_fetch` per
station and indexes the resulting :class:`ProviderReading` by
``(provider, station_id)``. A single station failing does not fail the update.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_PROVIDER,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_STATIONS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
)
from .providers import (
    BukeaHhProvider,
    HlnugHeProvider,
    LfuBbProvider,
    LfuShProvider,
    NiwisProvider,
    Provider,
    ProviderError,
    ProviderReading,
    ProviderStation,
    WasserportalBeProvider,
)

_LOGGER = logging.getLogger(__name__)

#: Factory per provider domain. Adding a Bundesland network = one entry here.
PROVIDER_FACTORIES = {
    NiwisProvider.domain: NiwisProvider,
    LfuBbProvider.domain: LfuBbProvider,
    BukeaHhProvider.domain: BukeaHhProvider,
    HlnugHeProvider.domain: HlnugHeProvider,
    WasserportalBeProvider.domain: WasserportalBeProvider,
    LfuShProvider.domain: LfuShProvider,
}


def build_providers(session) -> dict[str, Provider]:
    """Instantiate every known provider with the shared aiohttp session."""
    return {name: factory(session) for name, factory in PROVIDER_FACTORIES.items()}


type GwConfigEntry = ConfigEntry[GwCoordinator]


class GwCoordinator(DataUpdateCoordinator[dict[tuple[str, str], ProviderReading]]):
    """Fetch every selected station via its provider, once per interval."""

    config_entry: GwConfigEntry

    def __init__(self, hass: HomeAssistant, entry: GwConfigEntry) -> None:
        """Initialise the coordinator from a config entry."""
        hours = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_HOURS)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(hours=hours),
        )
        self.providers = build_providers(async_get_clientsession(hass))

    @property
    def selected_stations(self) -> list[dict]:
        """Return the configured station descriptors."""
        return list(self.config_entry.data.get(CONF_STATIONS, []))

    @staticmethod
    def _to_provider_station(descriptor: dict) -> ProviderStation:
        return ProviderStation(
            provider=descriptor[CONF_PROVIDER],
            station_id=descriptor[CONF_STATION_ID],
            name=descriptor.get(CONF_STATION_NAME) or descriptor[CONF_STATION_ID],
        )

    async def _async_update_data(self) -> dict[tuple[str, str], ProviderReading]:
        """Fetch all selected stations concurrently, tolerating single failures."""
        descriptors = self.selected_stations

        async def _fetch(descriptor: dict) -> ProviderReading | None:
            provider = self.providers.get(descriptor[CONF_PROVIDER])
            if provider is None:
                _LOGGER.warning("unknown provider %r", descriptor[CONF_PROVIDER])
                return None
            try:
                return await provider.async_fetch(
                    self._to_provider_station(descriptor)
                )
            except ProviderError as err:
                _LOGGER.warning(
                    "fetch %s/%s failed: %s",
                    descriptor[CONF_PROVIDER],
                    descriptor[CONF_STATION_ID],
                    err,
                )
                return None

        results = await asyncio.gather(*(_fetch(d) for d in descriptors))
        data: dict[tuple[str, str], ProviderReading] = {}
        for descriptor, reading in zip(descriptors, results, strict=True):
            if reading is not None:
                key = (descriptor[CONF_PROVIDER], descriptor[CONF_STATION_ID])
                data[key] = reading

        if descriptors and not data:
            raise UpdateFailed("no station returned data")
        return data

    def get_reading(
        self, provider: str, station_id: str
    ) -> ProviderReading | None:
        """Return the current reading for a station, if present."""
        return (self.data or {}).get((provider, station_id))
