"""Config and options flow for the groundwater integration.

Searches every active provider (NIWIS, LfU-BB, …) in one go — by radius around
the Home Assistant location or by a free-text query — merges the candidates
across sources, and lets the user pick stations. A picked station is stored as
``{provider, station_id, name}``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_PROVIDER,
    CONF_QUERY,
    CONF_RADIUS,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_STATIONS,
    DEFAULT_RADIUS_KM,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    MIN_SCAN_INTERVAL_HOURS,
)
from .coordinator import PROVIDER_FACTORIES, build_providers
from .providers import Provider, ProviderError, ProviderStation

_LOGGER = logging.getLogger(__name__)

#: human-readable label per provider domain (for candidate labels).
PROVIDER_LABELS = {cls.domain: cls.label for cls in PROVIDER_FACTORIES.values()}


@dataclass(slots=True)
class Candidate:
    """A selectable station discovered via a provider search."""

    provider: str
    station_id: str
    name: str
    latitude: float | None = None
    longitude: float | None = None
    distance_km: float | None = None

    @property
    def key(self) -> str:
        """Return the stable option key ``provider:station_id``."""
        return f"{self.provider}:{self.station_id}"


def _from_station(station: ProviderStation) -> Candidate:
    return Candidate(
        provider=station.provider,
        station_id=station.station_id,
        name=station.name,
        latitude=station.latitude,
        longitude=station.longitude,
        distance_km=station.distance_km,
    )


async def _gather(coros: list) -> list[list[ProviderStation]]:
    """Run per-provider searches concurrently, dropping ones that error."""
    results = await asyncio.gather(*coros, return_exceptions=True)
    out: list[list[ProviderStation]] = []
    for result in results:
        if isinstance(result, Exception):
            _LOGGER.debug("provider search skipped: %s", result)
            continue
        out.append(result)
    return out


async def search_radius(
    providers: dict[str, Provider], lat: float, lon: float, radius_km: float
) -> dict[str, Candidate]:
    """Aggregate radius searches across all providers, keyed by candidate key."""
    lists = await _gather(
        [p.async_search_radius(lat, lon, radius_km) for p in providers.values()]
    )
    return _merge(lists)


async def search_query(
    providers: dict[str, Provider], query: str
) -> dict[str, Candidate]:
    """Aggregate free-text searches across all providers, keyed by candidate key."""
    lists = await _gather(
        [p.async_search_query(query) for p in providers.values()]
    )
    return _merge(lists)


def _merge(lists: list[list[ProviderStation]]) -> dict[str, Candidate]:
    candidates: dict[str, Candidate] = {}
    for stations in lists:
        for station in stations:
            candidate = _from_station(station)
            candidates.setdefault(candidate.key, candidate)
    return candidates


def _sorted(candidates: dict[str, Candidate]) -> list[Candidate]:
    return sorted(
        candidates.values(),
        key=lambda c: (
            c.distance_km if c.distance_km is not None else float("inf"),
            c.name,
        ),
    )


def _options(candidates: list[Candidate]) -> list[SelectOptionDict]:
    options: list[SelectOptionDict] = []
    for cand in candidates:
        label = f"{cand.name} · {PROVIDER_LABELS.get(cand.provider, cand.provider)}"
        if cand.distance_km is not None:
            label = f"{label} · {cand.distance_km:.1f} km"
        options.append(SelectOptionDict(value=cand.key, label=label))
    return options


class GwConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the groundwater config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._candidates: dict[str, Candidate] = {}
        self._filtered: list[Candidate] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> GwOptionsFlow:
        """Return the options flow handler."""
        return GwOptionsFlow()

    def _providers(self) -> dict[str, Provider]:
        return build_providers(async_get_clientsession(self.hass))

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point – offer radius or name/ID search."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_show_menu(step_id="user", menu_options=["radius", "query"])

    async def async_step_radius(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search stations within a radius around the HA location."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._candidates = await search_radius(
                    self._providers(),
                    self.hass.config.latitude,
                    self.hass.config.longitude,
                    user_input[CONF_RADIUS],
                )
            except ProviderError:
                errors["base"] = "cannot_connect"
            else:
                self._filtered = _sorted(self._candidates)
                if not self._filtered:
                    errors["base"] = "no_stations"
                else:
                    return await self.async_step_select()

        return self.async_show_form(
            step_id="radius", data_schema=_radius_schema(), errors=errors
        )

    async def async_step_query(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search stations by name or station id."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._candidates = await search_query(
                    self._providers(), user_input[CONF_QUERY]
                )
            except ProviderError:
                errors["base"] = "cannot_connect"
            else:
                self._filtered = _sorted(self._candidates)
                if not self._filtered:
                    errors["base"] = "no_stations"
                else:
                    return await self.async_step_select()

        schema = vol.Schema({vol.Required(CONF_QUERY): TextSelector()})
        return self.async_show_form(step_id="query", data_schema=schema, errors=errors)

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick stations from the search results."""
        if user_input is not None:
            stations = [
                _descriptor(self._candidates[key])
                for key in user_input[CONF_STATIONS]
            ]
            return self.async_create_entry(
                title="Grundwasser",
                data={CONF_STATIONS: stations},
                options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL_HOURS},
            )

        return self.async_show_form(
            step_id="select", data_schema=_select_schema(self._filtered)
        )


class GwOptionsFlow(OptionsFlow):
    """Handle options: settings and adding more stations."""

    def __init__(self) -> None:
        """Initialise options flow state."""
        self._candidates: dict[str, Candidate] = {}
        self._filtered: list[Candidate] = []

    def _providers(self) -> dict[str, Provider]:
        return build_providers(async_get_clientsession(self.hass))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "add_radius", "add_query"]
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the scan interval."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_HOURS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL_HOURS,
                        max=24,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="h",
                    )
                )
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_add_radius(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add stations found within a radius."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._candidates = await search_radius(
                    self._providers(),
                    self.hass.config.latitude,
                    self.hass.config.longitude,
                    user_input[CONF_RADIUS],
                )
            except ProviderError:
                errors["base"] = "cannot_connect"
            else:
                self._filtered = self._available(_sorted(self._candidates))
                if not self._filtered:
                    errors["base"] = "no_stations"
                else:
                    return await self.async_step_add_select()

        return self.async_show_form(
            step_id="add_radius", data_schema=_radius_schema(), errors=errors
        )

    async def async_step_add_query(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add stations found by name or id."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._candidates = await search_query(
                    self._providers(), user_input[CONF_QUERY]
                )
            except ProviderError:
                errors["base"] = "cannot_connect"
            else:
                self._filtered = self._available(_sorted(self._candidates))
                if not self._filtered:
                    errors["base"] = "no_stations"
                else:
                    return await self.async_step_add_select()

        schema = vol.Schema({vol.Required(CONF_QUERY): TextSelector()})
        return self.async_show_form(
            step_id="add_query", data_schema=schema, errors=errors
        )

    async def async_step_add_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which discovered stations to add and merge into the entry."""
        if user_input is not None:
            existing = self._existing_keys()
            new_stations = [
                _descriptor(self._candidates[key])
                for key in user_input[CONF_STATIONS]
                if key not in existing
            ]
            merged = [
                *self.config_entry.data.get(CONF_STATIONS, []),
                *new_stations,
            ]
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_STATIONS: merged},
            )
            return self.async_create_entry(data=self.config_entry.options)

        if not self._filtered:
            return self.async_abort(reason="no_new_stations")
        return self.async_show_form(
            step_id="add_select", data_schema=_select_schema(self._filtered)
        )

    def _existing_keys(self) -> set[str]:
        return {
            f"{s[CONF_PROVIDER]}:{s[CONF_STATION_ID]}"
            for s in self.config_entry.data.get(CONF_STATIONS, [])
        }

    def _available(self, candidates: list[Candidate]) -> list[Candidate]:
        existing = self._existing_keys()
        return [c for c in candidates if c.key not in existing]


def _descriptor(candidate: Candidate) -> dict[str, str]:
    return {
        CONF_PROVIDER: candidate.provider,
        CONF_STATION_ID: candidate.station_id,
        CONF_STATION_NAME: candidate.name,
    }


def _radius_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_RADIUS, default=DEFAULT_RADIUS_KM): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=500,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="km",
                )
            )
        }
    )


def _select_schema(candidates: list[Candidate]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_STATIONS): SelectSelector(
                SelectSelectorConfig(
                    options=_options(candidates),
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )
        }
    )
