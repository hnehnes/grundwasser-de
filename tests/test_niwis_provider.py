"""Tests for the NIWIS groundwater provider adapter.

Runs against the same captured NIWIS payloads as the rest of the suite via the
``mock_niwis_api`` fixture (see ``tests/conftest.py``).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.grundwasser_de.providers.base import ProviderStation
from custom_components.grundwasser_de.providers.niwis import NiwisProvider

# Groundwater station in tests/fixtures/list_grundwasser.json.
_GW_NUMMER = "DEGM_DEBY83614"  # "NBS-H/W KB 11/1", lat 50.2037 / lon 9.6218


def _provider(hass: HomeAssistant) -> NiwisProvider:
    return NiwisProvider(async_get_clientsession(hass))


async def test_search_radius_returns_sorted_stations(
    hass: HomeAssistant, mock_niwis_api: AiohttpClientMocker
) -> None:
    """A radius around the fixture station finds it with a distance."""
    provider = _provider(hass)
    stations = await provider.async_search_radius(50.2037, 9.6218, 25)
    assert stations
    nearest = stations[0]
    assert nearest.provider == "niwis"
    assert nearest.station_id == _GW_NUMMER
    assert nearest.distance_km is not None and nearest.distance_km < 1
    # sorted nearest-first
    assert all(
        (a.distance_km or 0) <= (b.distance_km or 0)
        for a, b in zip(stations, stations[1:], strict=False)
    )


async def test_search_query_matches_name(
    hass: HomeAssistant, mock_niwis_api: AiohttpClientMocker
) -> None:
    """A free-text query matches on the station name."""
    provider = _provider(hass)
    stations = await provider.async_search_query("NBS-H/W")
    assert [s.station_id for s in stations] == [_GW_NUMMER]


async def test_fetch_returns_value_class_and_trend(
    hass: HomeAssistant, mock_niwis_api: AiohttpClientMocker
) -> None:
    """Fetch returns the current value plus NIWIS low-water class and trend."""
    provider = _provider(hass)
    reading = await provider.async_fetch(
        ProviderStation(provider="niwis", station_id=_GW_NUMMER, name="x")
    )
    assert reading.value == 194.4
    assert reading.unit == "m"
    assert reading.niedrigwasser_klasse == "SEHR_NIEDRIG"
    assert "BfG" in reading.attribution or "Gewässerkunde" in reading.attribution
