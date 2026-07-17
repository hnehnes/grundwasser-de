"""Tests for the Schleswig-Holstein (LfU) groundwater provider.

Pure helpers run against **real captured** responses in
``tests/fixtures/lfu_sh/`` (a trimmed ``app:gwmn`` WFS GeoJSON, an Open-Data
descriptor and a groundwater-level CSV); the async methods run through a tiny
fake session.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from custom_components.grundwasser_de.providers.base import ProviderStation
from custom_components.grundwasser_de.providers.lfu_sh import (
    LfuShProvider,
    ms_nr_from_link,
    parse_csv,
    parse_stations,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "lfu_sh"


def _load_json(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _load_text(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_ms_nr_from_link_strips_leading_space() -> None:
    """The WFS ``Link`` embeds ``ms_nr`` (with a stray space) -> extract it."""
    link = (
        "https://umweltanwendungen.schleswig-holstein.de/db/dbnuis"
        "?thema=lgdms&ms_nr= 10L02016001&ubs=ja&kopf"
    )
    assert ms_nr_from_link(link) == "10L02016001"
    assert ms_nr_from_link(None) is None
    assert ms_nr_from_link("no-ms-here") is None


def test_parse_stations_maps_wfs_features() -> None:
    """WFS GeoJSON features map to station dicts with lon/lat and ms_nr."""
    records = parse_stations(_load_json("wfs_stations_kiel.json")["features"])
    by_id = {r["station_id"]: r for r in records}
    assert "6377" in by_id  # Kurznummer "6377.0" -> "6377"
    poppenrade = by_id["6377"]
    assert poppenrade["ms_nr"] == "10L02016001"
    assert poppenrade["name"] == "KIEL-ELLERBEK POPPENRADE"
    assert 54.0 < poppenrade["lat"] < 55.0
    assert 9.0 < poppenrade["lon"] < 11.0


def test_parse_csv_is_chronological_de_format() -> None:
    """German ``Datum;Messwert`` rows parse to ascending (timestamp, value)."""
    series = parse_csv(_load_text("ganglinie_10L02016001.csv"))
    assert series[-1] == (datetime(2026, 3, 12, 6, 0, 0), 9.94)
    assert all(a[0] <= b[0] for a, b in zip(series, series[1:], strict=False))
    assert all(isinstance(v, float) for _, v in series)


# --------------------------------------------------------------------------- #
# Provider (fake session)
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, *, payload: dict | None = None, text: str = "") -> None:
        self._payload = payload
        self._text = text
        self.status = 200

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def json(self, **_: object) -> dict | None:
        return self._payload

    async def text(self, **_: object) -> str:
        return self._text


class _FakeSession:
    """Serves the WFS fixture for search, descriptor + CSV for fetch."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> _FakeResponse:
        self.calls.append(url)
        if "WFS_UWAT" in url:
            return _FakeResponse(payload=_load_json("wfs_stations_kiel.json"))
        if "hsi-sh.de" in url:
            return _FakeResponse(payload=_load_json("descriptor_10L02016001.json"))
        # the CSV path resolved from the descriptor
        return _FakeResponse(text=_load_text("ganglinie_10L02016001.csv"))


async def test_search_radius_returns_nearby_stations() -> None:
    """Radius search around Kiel maps WFS features to nearest-first stations."""
    provider = LfuShProvider(_FakeSession())  # type: ignore[arg-type]
    stations = await provider.async_search_radius(54.32, 10.13, 15)
    assert stations
    assert all(s.provider == "lfu_sh" for s in stations)
    assert all(s.latitude and s.longitude for s in stations)
    assert all(
        (a.distance_km or 0) <= (b.distance_km or 0)
        for a, b in zip(stations, stations[1:], strict=False)
    )
    # the ms_nr is carried through for a later fetch
    assert any(s.extra.get("ms_nr") for s in stations)


async def test_fetch_returns_latest_and_history() -> None:
    """Fetch resolves the descriptor, parses the CSV, returns newest m ü. NN."""
    provider = LfuShProvider(_FakeSession())  # type: ignore[arg-type]
    reading = await provider.async_fetch(
        ProviderStation(
            provider="lfu_sh",
            station_id="6377",
            name="x",
            extra={"ms_nr": "10L02016001"},
        )
    )
    assert reading.value == 9.94
    assert reading.unit == "m"
    assert reading.timestamp == datetime(2026, 3, 12, 6, 0, 0)
    assert len(reading.history) >= 2
    assert "Schleswig-Holstein" in reading.attribution


async def test_fetch_missing_descriptor_is_graceful() -> None:
    """A station whose descriptor 404s yields value None, not a crash."""

    class _NoDescriptorSession:
        def get(self, url: str, **_: object) -> _FakeResponse:
            resp = _FakeResponse(payload={})
            if "hsi-sh.de" in url:
                resp.status = 404
            return resp

    provider = LfuShProvider(_NoDescriptorSession())  # type: ignore[arg-type]
    reading = await provider.async_fetch(
        ProviderStation(
            provider="lfu_sh", station_id="9999", name="x",
            extra={"ms_nr": "10L99999999"},
        )
    )
    assert reading.value is None
    assert reading.history == []
