"""Tests for the Hamburg (BUKEA) groundwater provider.

Pure helpers run against **real captured** OGC-API responses in
``tests/fixtures/bukea_hh/``; the async methods run through a tiny fake session.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from custom_components.grundwasser_de.providers.base import ProviderStation
from custom_components.grundwasser_de.providers.bukea_hh import (
    BukeaHhProvider,
    bbox_around,
    latest_per_station,
    parse_series,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "bukea_hh"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _features(name: str) -> list[dict]:
    return _load(name)["features"]


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_latest_per_station_dedupes_to_newest() -> None:
    """A bbox response (many station-days) reduces to one record per station."""
    records = latest_per_station(_features("items_bbox.json"))
    by_id = {r["station_id"]: r for r in records}
    assert set(by_id) == {"2200", "3381"}
    # newest-first input -> first seen is the latest date
    assert by_id["2200"]["timestamp"] == "2026-07-15"
    assert by_id["2200"]["value"] == 15.14
    assert by_id["2200"]["lat"] == 53.589054959708626
    assert by_id["2200"]["lon"] == 9.926085686766218


def test_parse_series_is_chronological() -> None:
    """A single station's days parse to ascending (timestamp, value) pairs."""
    series = parse_series(_features("items_station_2200.json"))
    assert len(series) == 6
    assert series[-1] == (datetime(2026, 7, 15), 15.14)
    assert all(a[0] <= b[0] for a, b in zip(series, series[1:], strict=False))


def test_bbox_around_contains_point() -> None:
    """The computed bbox brackets the centre point."""
    box = [float(v) for v in bbox_around(53.55, 9.99, 10).split(",")]
    min_lon, min_lat, max_lon, max_lat = box
    assert min_lon < 9.99 < max_lon
    assert min_lat < 53.55 < max_lat


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
    """Serves the station fixture for fetch, the bbox fixture for search."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get(self, url: str, *, params: dict, **_: object) -> _FakeResponse:
        self.calls.append(params)
        if "messstellennummer" in params:
            return _FakeResponse(_load("items_station_2200.json"))
        return _FakeResponse(_load("items_bbox.json"))


async def test_search_radius_returns_nearby_stations() -> None:
    """Search around station 2200 returns it (nearest) plus the neighbour."""
    provider = BukeaHhProvider(_FakeSession())  # type: ignore[arg-type]
    stations = await provider.async_search_radius(53.5891, 9.9261, 10)
    assert [s.station_id for s in stations][0] == "2200"
    assert {s.station_id for s in stations} == {"2200", "3381"}
    assert stations[0].provider == "bukea_hh"
    assert stations[0].distance_km is not None and stations[0].distance_km < 0.1


async def test_fetch_returns_latest_and_history() -> None:
    """Fetch returns the newest value (m ü. NHN) and the recent series."""
    provider = BukeaHhProvider(_FakeSession())  # type: ignore[arg-type]
    reading = await provider.async_fetch(
        ProviderStation(provider="bukea_hh", station_id="2200", name="x")
    )
    assert reading.value == 15.14
    assert reading.unit == "m"
    assert reading.timestamp == datetime(2026, 7, 15)
    assert len(reading.history) == 6
    assert "Hamburg" in reading.attribution
