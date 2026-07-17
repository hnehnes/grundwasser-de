"""Tests for the North Rhine-Westphalia (LANUK) groundwater provider.

Pure helpers run against a **real captured** OpenHygrisC water-level sample
(``tests/fixtures/lanuk_nw/wasserstand_sample.csv``); search runs against the
shipped station bundle; the download path runs through a tiny fake session that
serves a ZIP of the sample.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import custom_components.grundwasser_de.providers.lanuk_nw as lanuk_nw
from custom_components.grundwasser_de.providers.base import ProviderStation
from custom_components.grundwasser_de.providers.lanuk_nw import (
    LanukNwProvider,
    parse_date,
    parse_value,
    reduce_latest,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "lanuk_nw"
_SAMPLE_CSV = (_FIXTURES / "wasserstand_sample.csv").read_text(encoding="utf-8")

# A real, shipped station near Cologne (from lanuk_nw_stations.json).
_KOELN = (50.94, 6.96)
_WAISENHAUS_ID = "070167217"
_KOELN363_ID = "279576511"


def _reset_snapshot() -> None:
    lanuk_nw._snapshot = None
    lanuk_nw._snapshot_time = None
    lanuk_nw._snapshot_last_modified = None


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_parse_value_handles_comma_and_gaps() -> None:
    """German decimal comma parses; empty / ``-`` become None."""
    assert parse_value("37,67") == 37.67
    assert parse_value(" 38,00 ") == 38.0
    assert parse_value("") is None
    assert parse_value("-") is None
    assert parse_value("x") is None


def test_parse_date_iso() -> None:
    """``datum_messung`` is ISO ``YYYY-MM-DD``."""
    assert parse_date("2026-05-27") == datetime(2026, 5, 27)
    assert parse_date("nonsense") is None


def test_reduce_latest_keeps_newest_and_skips_empty() -> None:
    """Reduction keeps the newest dated value per station, ignoring gaps."""
    latest = reduce_latest(io.StringIO(_SAMPLE_CSV))
    assert set(latest) == {_KOELN363_ID, _WAISENHAUS_ID}
    # 279576511's newest *valued* row is 2026-05-27/37.67; the later
    # 2026-07-01 "trocken" row has an empty value and must not win.
    assert latest[_KOELN363_ID] == (datetime(2026, 5, 27), 37.67)
    assert latest[_WAISENHAUS_ID] == (datetime(2026, 5, 26), 37.62)


def test_reduce_zip_file_roundtrip(tmp_path: Path) -> None:
    """A ZIP of the sample CSV reduces the same as the raw CSV."""
    zip_path = tmp_path / "w.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("OpenHygrisC_gw-wasserstand_2020-2029.csv", _SAMPLE_CSV)
    latest = lanuk_nw.reduce_zip_file(str(zip_path))
    assert latest[_KOELN363_ID] == (datetime(2026, 5, 27), 37.67)


# --------------------------------------------------------------------------- #
# Search (shipped bundle, no network)
# --------------------------------------------------------------------------- #
async def test_search_radius_finds_cologne_station() -> None:
    """A 5 km search around Cologne returns nearby stations, nearest first."""
    provider = LanukNwProvider(session=None)  # type: ignore[arg-type]
    stations = await provider.async_search_radius(*_KOELN, 5)
    assert stations, "expected NRW stations near Cologne"
    ids = {s.station_id for s in stations}
    assert _WAISENHAUS_ID in ids
    # nearest-first ordering + populated coordinates/provider tag.
    dists = [s.distance_km for s in stations]
    assert dists == sorted(dists)
    assert stations[0].provider == "lanuk_nw"
    assert stations[0].latitude is not None


async def test_search_query_matches_id() -> None:
    """A free-text search matches a station id substring."""
    provider = LanukNwProvider(session=None)  # type: ignore[arg-type]
    stations = await provider.async_search_query(_WAISENHAUS_ID)
    assert _WAISENHAUS_ID in {s.station_id for s in stations}


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
async def test_fetch_reads_from_snapshot() -> None:
    """With a warm snapshot, fetch returns the latest value in m ü. NHN."""
    _reset_snapshot()
    lanuk_nw._snapshot = {_KOELN363_ID: (datetime(2026, 5, 27), 37.67)}
    lanuk_nw._snapshot_time = datetime.now(UTC)
    try:
        provider = LanukNwProvider(session=None)  # type: ignore[arg-type]
        reading = await provider.async_fetch(
            ProviderStation(provider="lanuk_nw", station_id=_KOELN363_ID, name="x")
        )
        assert reading.value == 37.67
        assert reading.unit == "m"
        assert reading.timestamp == datetime(2026, 5, 27)
        assert "LANUK" in reading.attribution
    finally:
        _reset_snapshot()


async def test_fetch_unknown_station_returns_none() -> None:
    """A station absent from the snapshot yields value None, not an error."""
    _reset_snapshot()
    lanuk_nw._snapshot = {}
    lanuk_nw._snapshot_time = datetime.now(UTC)
    try:
        provider = LanukNwProvider(session=None)  # type: ignore[arg-type]
        reading = await provider.async_fetch(
            ProviderStation(provider="lanuk_nw", station_id="000000000", name="x")
        )
        assert reading.value is None
        assert reading.unit == "m"
    finally:
        _reset_snapshot()


class _FakeContent:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def iter_chunked(self, size: int):
        for start in range(0, len(self._data), size):
            yield self._data[start : start + size]


class _FakeResponse:
    def __init__(self, data: bytes = b"", last_modified: str = "lm-1") -> None:
        self.status = 200
        self.content = _FakeContent(data)
        self.headers = {"Last-Modified": last_modified}

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSession:
    """Serves a ZIP of the sample CSV for the bulk download, and HEAD metadata."""

    def __init__(self, data: bytes, last_modified: str = "lm-1") -> None:
        self.calls = 0  # GET (download) count
        self.head_calls = 0
        self._data = data
        self._last_modified = last_modified

    def get(self, url: str, **_: object) -> _FakeResponse:
        self.calls += 1
        return _FakeResponse(self._data, self._last_modified)

    def head(self, url: str, **_: object) -> _FakeResponse:
        self.head_calls += 1
        return _FakeResponse(b"", self._last_modified)


async def test_fetch_downloads_and_reduces_bulk() -> None:
    """Cold cache: fetch streams the ZIP, reduces it, then serves from cache."""
    _reset_snapshot()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("OpenHygrisC_gw-wasserstand_2020-2029.csv", _SAMPLE_CSV)
    session = _FakeSession(buffer.getvalue())
    try:
        provider = LanukNwProvider(session)  # type: ignore[arg-type]
        reading = await provider.async_fetch(
            ProviderStation(provider="lanuk_nw", station_id=_WAISENHAUS_ID, name="x")
        )
        assert reading.value == 37.62
        assert reading.timestamp == datetime(2026, 5, 26)
        # a second station is served from the warm snapshot (no new download).
        again = await provider.async_fetch(
            ProviderStation(provider="lanuk_nw", station_id=_KOELN363_ID, name="x")
        )
        assert again.value == 37.67
        assert session.calls == 1
    finally:
        _reset_snapshot()


async def test_stale_snapshot_skips_download_when_unchanged() -> None:
    """After the TTL, an unchanged Last-Modified reuses the snapshot (no download)."""
    _reset_snapshot()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("OpenHygrisC_gw-wasserstand_2020-2029.csv", _SAMPLE_CSV)
    session = _FakeSession(buffer.getvalue(), last_modified="lm-A")
    try:
        provider = LanukNwProvider(session)  # type: ignore[arg-type]
        # cold fetch downloads once and records Last-Modified "lm-A".
        await provider.async_fetch(
            ProviderStation(provider="lanuk_nw", station_id=_KOELN363_ID, name="x")
        )
        assert session.calls == 1
        # force the TTL to expire; the file is unchanged (same Last-Modified).
        lanuk_nw._snapshot_time = datetime(2000, 1, 1, tzinfo=UTC)
        await provider.async_fetch(
            ProviderStation(provider="lanuk_nw", station_id=_KOELN363_ID, name="x")
        )
        # HEAD was re-checked, but the 244 MB GET did NOT run again.
        assert session.calls == 1
        assert session.head_calls >= 1
    finally:
        _reset_snapshot()
