"""Fixtures for NIWIS tests."""

from __future__ import annotations

import re

import pytest
from pytest_homeassistant_custom_component.common import load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.niwis.const import MESSGROESSEN

pytest_plugins = "pytest_homeassistant_custom_component"

_FIXTURE_BY_MG = {
    "GRUNDWASSER": "list_grundwasser.json",
    "WASSERSTAND": "list_wasserstand.json",
    "ABFLUSS": "list_abfluss.json",
    "QUELLSCHUETTUNG": "list_quellschuettung.json",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom integration in every test."""
    yield


_DETAIL_FIXTURES = {
    "wasserstand/DESM_DEBY16607001": "detail_ws.json",
    "abfluss/DESM_DEBY16607001": "detail_ab.json",
    "grundwasser/DEGM_DEBY83614": "detail_gw.json",
}


@pytest.fixture
def mock_niwis_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock the NIWIS list and detail endpoints with real captured payloads."""
    for messgroesse in MESSGROESSEN:
        aioclient_mock.get(
            re.compile(rf".*/karte/messstelle/{messgroesse}(\?.*)?$"),
            text=load_fixture(_FIXTURE_BY_MG[messgroesse]),
            headers={"Content-Type": "application/json"},
        )
    # Master-data (Stammdaten) endpoints for speaking device names.
    for path, fixture in _DETAIL_FIXTURES.items():
        aioclient_mock.get(
            re.compile(rf".*/karte/{path}(\?.*)?$"),
            text=load_fixture(fixture),
            headers={"Content-Type": "application/json"},
        )
    # Any other detail lookup returns an empty object (graceful fallback).
    aioclient_mock.get(
        re.compile(r".*/karte/(grundwasser|wasserstand|abfluss)/.*"),
        text="{}",
        headers={"Content-Type": "application/json"},
    )
    return aioclient_mock
