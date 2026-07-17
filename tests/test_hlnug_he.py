"""Tests for the Hesse (HLNUG) ArcGIS groundwater provider."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from custom_components.grundwasser_de.providers.base import ProviderStation
from custom_components.grundwasser_de.providers.hlnug_he import (
    HlnugHeProvider,
    parse_series,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "hlnug_he"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_series_epoch_ms_to_dates() -> None:
    """ArcGIS MESSDATUM (epoch ms) + MESSWERT parse to chronological pairs."""
    series = parse_series(_load("series_12817.json")["features"])
    assert len(series) == 6
    assert series[-1] == (datetime(2026, 7, 16), 151.85)
    assert all(a[0] <= b[0] for a, b in zip(series, series[1:], strict=False))


# --------------------------------------------------------------------------- #
# Provider (fake session)
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status = 200

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def json(self, **_: object) -> dict:
        return self._payload


class _FakeSession:
    """Serves the series fixture for the time-series layer, stations otherwise."""

    def get(self, url: str, *, params: dict, **_: object) -> _FakeResponse:
        if "Auswertung" in url:
            return _FakeResponse(_load("series_12817.json"))
        return _FakeResponse(_load("stations_darmstadt.json"))


async def test_search_radius_maps_arcgis_stations() -> None:
    """Radius search maps ArcGIS features to stations with WGS84 coords."""
    provider = HlnugHeProvider(_FakeSession())  # type: ignore[arg-type]
    stations = await provider.async_search_radius(49.872, 8.651, 3)
    assert stations
    assert all(s.provider == "hlnug_he" for s in stations)
    assert all(s.latitude and s.longitude for s in stations)
    # nearest-first
    assert all(
        (a.distance_km or 0) <= (b.distance_km or 0)
        for a, b in zip(stations, stations[1:], strict=False)
    )


async def test_fetch_returns_latest_and_history() -> None:
    """Fetch returns the newest NN value (m ü. NN) and the recent series."""
    provider = HlnugHeProvider(_FakeSession())  # type: ignore[arg-type]
    reading = await provider.async_fetch(
        ProviderStation(provider="hlnug_he", station_id="12817", name="x")
    )
    assert reading.value == 151.85
    assert reading.unit == "m"
    assert reading.timestamp == datetime(2026, 7, 16)
    assert len(reading.history) == 6
    assert "HLNUG" in reading.attribution


async def test_fetch_non_numeric_id_is_graceful() -> None:
    """A non-numeric station id yields value None instead of a bad query."""
    provider = HlnugHeProvider(_FakeSession())  # type: ignore[arg-type]
    reading = await provider.async_fetch(
        ProviderStation(provider="hlnug_he", station_id="abc", name="x")
    )
    assert reading.value is None
    assert reading.history == []
