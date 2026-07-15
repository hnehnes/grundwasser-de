"""Config and options flow for the NIWIS integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
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

from .api import NiwisApiClient, NiwisApiError, haversine_km
from .const import (
    CONF_KLASSIFIKATIONSART,
    CONF_QUERY,
    CONF_RADIUS,
    CONF_SCAN_INTERVAL,
    CONF_STATION_MESSGROESSEN,
    CONF_STATION_NAME,
    CONF_STATION_NUMMER,
    CONF_STATIONS,
    DEFAULT_RADIUS_KM,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    KLASS_DYNAMISCH,
    KLASSIFIKATIONSARTEN,
    MESSGROESSEN,
    MIN_SCAN_INTERVAL_HOURS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Candidate:
    """A selectable station aggregated across measurement types."""

    nummer: str
    name: str
    messgroessen: list[str] = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    distance_km: float | None = None


async def _build_candidates(client: NiwisApiClient) -> dict[str, Candidate]:
    """Fetch every measurement type and aggregate stations by number."""
    data = await client.async_get_stations_map(list(MESSGROESSEN))
    candidates: dict[str, Candidate] = {}
    for messgroesse, stations in data.items():
        for nummer, station in stations.items():
            cand = candidates.get(nummer)
            if cand is None:
                cand = Candidate(
                    nummer=nummer,
                    name=station.name,
                    latitude=station.latitude,
                    longitude=station.longitude,
                )
                candidates[nummer] = cand
            if messgroesse not in cand.messgroessen:
                cand.messgroessen.append(messgroesse)
    return candidates


def _messgroessen_label(messgroessen: list[str]) -> str:
    """Return a human label for the covered measurement types."""
    names = {
        "GRUNDWASSER": "Grundwasser",
        "QUELLSCHUETTUNG": "Quellschüttung",
        "WASSERSTAND": "Wasserstand",
        "ABFLUSS": "Abfluss",
    }
    return ", ".join(names.get(m, m) for m in messgroessen)


def _candidate_options(candidates: list[Candidate]) -> list[SelectOptionDict]:
    """Build select options (value = station number) from candidates."""
    options: list[SelectOptionDict] = []
    for cand in candidates:
        label = f"{cand.name} · {_messgroessen_label(cand.messgroessen)}"
        if cand.distance_km is not None:
            label = f"{label} · {cand.distance_km:.1f} km"
        options.append(SelectOptionDict(value=cand.nummer, label=label))
    return options


class NiwisConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the NIWIS config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._candidates: dict[str, Candidate] = {}
        self._filtered: list[Candidate] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> NiwisOptionsFlow:
        """Return the options flow handler."""
        return NiwisOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point – offer radius or name/ID search."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_show_menu(
            step_id="user", menu_options=["radius", "query"]
        )

    async def async_step_radius(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search stations within a radius around the HA location."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._ensure_candidates()
            except NiwisApiError:
                errors["base"] = "cannot_connect"
            else:
                self._filtered = self._within_radius(user_input[CONF_RADIUS])
                if not self._filtered:
                    errors["base"] = "no_stations"
                else:
                    return await self.async_step_select()

        schema = vol.Schema(
            {
                vol.Required(CONF_RADIUS, default=DEFAULT_RADIUS_KM): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=500, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="km",
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="radius", data_schema=schema, errors=errors
        )

    async def async_step_query(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search stations by name or station number."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._ensure_candidates()
            except NiwisApiError:
                errors["base"] = "cannot_connect"
            else:
                self._filtered = self._matching(user_input[CONF_QUERY])
                if not self._filtered:
                    errors["base"] = "no_stations"
                else:
                    return await self.async_step_select()

        schema = vol.Schema({vol.Required(CONF_QUERY): TextSelector()})
        return self.async_show_form(
            step_id="query", data_schema=schema, errors=errors
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick stations from the search results."""
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input[CONF_STATIONS]
            stations = [
                {
                    CONF_STATION_NUMMER: self._candidates[nummer].nummer,
                    CONF_STATION_NAME: self._candidates[nummer].name,
                    CONF_STATION_MESSGROESSEN: self._candidates[nummer].messgroessen,
                }
                for nummer in selected
            ]
            return self.async_create_entry(
                title="NIWIS",
                data={CONF_STATIONS: stations},
                options={
                    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL_HOURS,
                    CONF_KLASSIFIKATIONSART: KLASS_DYNAMISCH,
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_STATIONS): SelectSelector(
                    SelectSelectorConfig(
                        options=_candidate_options(self._filtered),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="select", data_schema=schema, errors=errors
        )

    # --- helpers -----------------------------------------------------------
    async def _ensure_candidates(self) -> None:
        """Fetch and cache the full candidate list once."""
        if self._candidates:
            return
        client = NiwisApiClient(async_get_clientsession(self.hass))
        self._candidates = await _build_candidates(client)

    def _within_radius(self, radius_km: float) -> list[Candidate]:
        """Return candidates within ``radius_km`` of the HA location, sorted."""
        lat = self.hass.config.latitude
        lon = self.hass.config.longitude
        matches: list[Candidate] = []
        for cand in self._candidates.values():
            if cand.latitude is None or cand.longitude is None:
                continue
            dist = haversine_km(lat, lon, cand.latitude, cand.longitude)
            if dist <= radius_km:
                cand.distance_km = dist
                matches.append(cand)
        matches.sort(key=lambda c: c.distance_km or 0.0)
        return matches

    def _matching(self, query: str) -> list[Candidate]:
        """Return candidates whose name or number contains ``query``."""
        needle = query.strip().casefold()
        matches = [
            cand
            for cand in self._candidates.values()
            if needle in cand.name.casefold() or needle in cand.nummer.casefold()
        ]
        matches.sort(key=lambda c: c.name)
        return matches


class NiwisOptionsFlow(OptionsFlow):
    """Handle NIWIS options: settings and adding more stations."""

    def __init__(self) -> None:
        """Initialise options flow state."""
        self._candidates: dict[str, Candidate] = {}
        self._filtered: list[Candidate] = []

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
        """Configure scan interval and classification type."""
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
                ),
                vol.Required(
                    CONF_KLASSIFIKATIONSART,
                    default=options.get(CONF_KLASSIFIKATIONSART, KLASS_DYNAMISCH),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=k, label=k.capitalize())
                            for k in KLASSIFIKATIONSARTEN
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
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
                await self._ensure_candidates()
            except NiwisApiError:
                errors["base"] = "cannot_connect"
            else:
                self._filtered = self._within_radius(user_input[CONF_RADIUS])
                if not self._filtered:
                    errors["base"] = "no_stations"
                else:
                    return await self.async_step_add_select()

        schema = vol.Schema(
            {
                vol.Required(CONF_RADIUS, default=DEFAULT_RADIUS_KM): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=500, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="km",
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="add_radius", data_schema=schema, errors=errors
        )

    async def async_step_add_query(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add stations found by name or number."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._ensure_candidates()
            except NiwisApiError:
                errors["base"] = "cannot_connect"
            else:
                self._filtered = self._matching(user_input[CONF_QUERY])
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
        existing = {
            s[CONF_STATION_NUMMER]
            for s in self.config_entry.data.get(CONF_STATIONS, [])
        }
        if user_input is not None:
            new_stations = [
                {
                    CONF_STATION_NUMMER: self._candidates[nummer].nummer,
                    CONF_STATION_NAME: self._candidates[nummer].name,
                    CONF_STATION_MESSGROESSEN: self._candidates[nummer].messgroessen,
                }
                for nummer in user_input[CONF_STATIONS]
                if nummer not in existing
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

        # Do not offer already-configured stations again.
        available = [c for c in self._filtered if c.nummer not in existing]
        if not available:
            return self.async_abort(reason="no_new_stations")

        schema = vol.Schema(
            {
                vol.Required(CONF_STATIONS): SelectSelector(
                    SelectSelectorConfig(
                        options=_candidate_options(available),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="add_select", data_schema=schema)

    # --- helpers (shared logic with the config flow) -----------------------
    async def _ensure_candidates(self) -> None:
        client = NiwisApiClient(async_get_clientsession(self.hass))
        if not self._candidates:
            self._candidates = await _build_candidates(client)

    def _within_radius(self, radius_km: float) -> list[Candidate]:
        lat = self.hass.config.latitude
        lon = self.hass.config.longitude
        matches: list[Candidate] = []
        for cand in self._candidates.values():
            if cand.latitude is None or cand.longitude is None:
                continue
            dist = haversine_km(lat, lon, cand.latitude, cand.longitude)
            if dist <= radius_km:
                cand.distance_km = dist
                matches.append(cand)
        matches.sort(key=lambda c: c.distance_km or 0.0)
        return matches

    def _matching(self, query: str) -> list[Candidate]:
        needle = query.strip().casefold()
        matches = [
            cand
            for cand in self._candidates.values()
            if needle in cand.name.casefold() or needle in cand.nummer.casefold()
        ]
        matches.sort(key=lambda c: c.name)
        return matches
