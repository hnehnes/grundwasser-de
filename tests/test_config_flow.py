"""Tests for the provider-neutral config and options flow."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.niwis.const import (
    CONF_PROVIDER,
    CONF_QUERY,
    CONF_RADIUS,
    CONF_STATION_ID,
    CONF_STATIONS,
    DOMAIN,
)

_GW_NUMMER = "DEGM_DEBY83614"  # NIWIS groundwater fixture station "NBS-H/W KB 11/1"


@pytest.fixture
def _hoppegarten(hass: HomeAssistant) -> None:
    """Place the HA instance near Hoppegarten (Brandenburg) for radius search."""
    hass.config.latitude = 52.507
    hass.config.longitude = 13.664


async def test_query_flow_niwis(
    hass: HomeAssistant, mock_niwis_api: AiohttpClientMocker
) -> None:
    """A name query surfaces the matching NIWIS station and creates an entry.

    The LfU-BB query hits the (unmocked) APW backend and is silently dropped,
    so only the NIWIS candidate remains — exercising cross-provider tolerance.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "query"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_QUERY: "NBS"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: [f"niwis:{_GW_NUMMER}"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    stations = result["data"][CONF_STATIONS]
    assert stations == [
        {
            CONF_PROVIDER: "niwis",
            CONF_STATION_ID: _GW_NUMMER,
            "name": "NBS-H/W KB 11/1",
        }
    ]


async def test_radius_flow_lfu(
    hass: HomeAssistant, mock_niwis_api: AiohttpClientMocker, _hoppegarten: None
) -> None:
    """A radius search near Hoppegarten finds LfU-BB stations from bundled data."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "radius"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RADIUS: 25}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select"

    # Münchehofe/Hoppegarten (~2 km) is bundled; pick it.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: ["lfu_bb:35480874"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    stations = result["data"][CONF_STATIONS]
    assert stations[0][CONF_PROVIDER] == "lfu_bb"
    assert stations[0][CONF_STATION_ID] == "35480874"


async def test_query_no_results(
    hass: HomeAssistant, mock_niwis_api: AiohttpClientMocker
) -> None:
    """A query matching nothing shows the no_stations error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "query"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_QUERY: "zzzzzzzz"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_stations"}


async def test_single_instance_only(
    hass: HomeAssistant, mock_niwis_api: AiohttpClientMocker
) -> None:
    """A second config flow aborts (single hub instance)."""
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
