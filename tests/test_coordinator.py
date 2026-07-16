"""Tests for the provider-neutral coordinator and sensors."""

from __future__ import annotations

import re

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.grundwasser_de.const import (
    CONF_PROVIDER,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_STATIONS,
    DOMAIN,
)

# Groundwater station in tests/fixtures/list_grundwasser.json.
_GW_NUMMER = "DEGM_DEBY83614"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Grundwasser",
        unique_id=DOMAIN,
        data={
            CONF_STATIONS: [
                {
                    CONF_PROVIDER: "niwis",
                    CONF_STATION_ID: _GW_NUMMER,
                    CONF_STATION_NAME: "Obersinn",
                }
            ]
        },
        options={CONF_SCAN_INTERVAL: 3},
    )


async def test_setup_and_sensor_values(
    hass: HomeAssistant, mock_niwis_api: AiohttpClientMocker
) -> None:
    """A NIWIS groundwater station yields value, class and trend sensors."""
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    value = hass.states.get("sensor.obersinn_grundwasserstand")
    assert value is not None
    assert value.state == "194.4"
    assert value.attributes["unit_of_measurement"] == "m"

    klasse = hass.states.get("sensor.obersinn_niedrigwasserklasse")
    assert klasse is not None
    assert klasse.state == "sehr niedrig"
    assert "kein Niedrigwasser" in klasse.attributes["options"]

    # Trend sensor exists (NIWIS-only metadata).
    assert hass.states.get("sensor.obersinn_trend") is not None


async def test_update_failed_marks_retry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When the only station's source fails, setup is retried."""
    aioclient_mock.get(re.compile(r".*/karte/messstelle/.*"), status=502)
    entry = _entry()
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
