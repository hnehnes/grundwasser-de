"""Tests for the NIWIS coordinator and sensors."""

from __future__ import annotations

import re

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.niwis.const import (
    CONF_SCAN_INTERVAL,
    CONF_STATION_MESSGROESSEN,
    CONF_STATION_NAME,
    CONF_STATION_NUMMER,
    CONF_STATIONS,
    DOMAIN,
)

# A surface station present in both WASSERSTAND and ABFLUSS fixtures.
_WS_NUMMER = "DESM_DEBY16607001"
_GW_NUMMER = "DEGM_DEBY83614"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="NIWIS",
        unique_id=DOMAIN,
        data={
            CONF_STATIONS: [
                {
                    CONF_STATION_NUMMER: _WS_NUMMER,
                    CONF_STATION_NAME: "Inkofen",
                    CONF_STATION_MESSGROESSEN: ["WASSERSTAND", "ABFLUSS"],
                },
                {
                    CONF_STATION_NUMMER: _GW_NUMMER,
                    CONF_STATION_NAME: "Obersinn",
                    CONF_STATION_MESSGROESSEN: ["GRUNDWASSER"],
                },
            ]
        },
        options={CONF_SCAN_INTERVAL: 3},
    )


async def test_setup_and_sensor_values(
    hass: HomeAssistant, mock_niwis_api: AiohttpClientMocker
) -> None:
    """Coordinator loads and sensors reflect the captured payloads."""
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    # Value sensor (Wasserstand, cm). Device name comes from Stammdaten:
    # name "Inkofen" + gewaesser "Amper" -> "Inkofen (Amper)".
    state = hass.states.get("sensor.inkofen_amper_wasserstand")
    assert state is not None
    assert state.state == "37.0"
    assert state.attributes["unit_of_measurement"] == "cm"

    # Low-water class sensor -> German text
    klasse = hass.states.get(
        "sensor.inkofen_amper_niedrigwasserklasse_wasserstand"
    )
    assert klasse is not None
    assert klasse.state == "extrem niedrig"
    assert "kein Niedrigwasser" in klasse.attributes["options"]

    # Trend sensor -> German text
    trend = hass.states.get("sensor.inkofen_amper_trend_wasserstand")
    assert trend is not None
    assert trend.state == "gleichbleibend"

    # Groundwater device uses its Ortslage ("Obersinn") as the speaking name.
    gw = hass.states.get("sensor.obersinn_grundwasserstand")
    assert gw is not None
    assert gw.state == "194.4"


async def test_update_failed_marks_unavailable(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A failing API leads to ConfigEntryNotReady / not-loaded."""
    aioclient_mock.get(re.compile(r".*/karte/messstelle/.*"), status=502)
    entry = _entry()
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_only_needed_messgroessen_are_polled(
    hass: HomeAssistant, mock_niwis_api: AiohttpClientMocker
) -> None:
    """Only measurement types of selected stations are requested."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="NIWIS",
        unique_id=DOMAIN,
        data={
            CONF_STATIONS: [
                {
                    CONF_STATION_NUMMER: _GW_NUMMER,
                    CONF_STATION_NAME: "Obersinn",
                    CONF_STATION_MESSGROESSEN: ["GRUNDWASSER"],
                }
            ]
        },
        options={CONF_SCAN_INTERVAL: 3},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    requested = [str(call[1]) for call in mock_niwis_api.mock_calls]
    assert any("GRUNDWASSER" in url for url in requested)
    assert not any("WASSERSTAND" in url for url in requested)
    assert not any("ABFLUSS" in url for url in requested)
