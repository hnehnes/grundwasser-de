"""Tests for the Berlin (Wasserportal) groundwater provider.

Pure helpers run against a **real captured** daily CSV in
``tests/fixtures/wasserportal_be/``; the async methods run through a tiny fake
session and the bundled station list.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from custom_components.grundwasser_de.providers.base import ProviderStation
from custom_components.grundwasser_de.providers.wasserportal_be import (
    WasserportalBeProvider,
    build_csv_url,
    parse_gws_csv,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "wasserportal_be"
_CSV_BYTES = (_FIXTURES / "station_1_gws.csv").read_bytes()


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_parse_gws_csv_is_chronological_and_typed() -> None:
    """The captured CSV parses to ascending (timestamp, value) pairs in m NHN."""
    text = _CSV_BYTES.decode("iso-8859-15")
    series = parse_gws_csv(text)
    assert series  # non-empty
    assert all(isinstance(v, float) for _, v in series)
    assert all(a[0] <= b[0] for a, b in zip(series, series[1:], strict=False))
    # first and last rows of the fixture (station 1, June–July 2026)
    assert series[0] == (datetime(2026, 6, 1), 33.48)
    assert series[-1] == (datetime(2026, 7, 13), 33.41)


def test_parse_gws_csv_skips_metadata_and_gaps() -> None:
    """Metadata/header lines and empty/`-` values never become samples."""
    text = (
        'Messstellennummer;1\r\n'
        'Bezirk;Reinickendorf\r\n'
        'Datum;"GW-Stand (m ü. NHN)"\r\n'
        "01.06.2026;33,48\r\n"
        "02.06.2026;\r\n"       # empty value -> skipped
        "03.06.2026;-\r\n"      # missing marker -> skipped
        "04.06.2026;33,50\r\n"
    )
    series = parse_gws_csv(text)
    assert series == [
        (datetime(2026, 6, 1), 33.48),
        (datetime(2026, 6, 4), 33.50),
    ]


def test_build_csv_url_has_expected_params() -> None:
    """The export URL carries the station id and the German date range."""
    url = build_csv_url("15156", datetime(2025, 1, 2), datetime(2026, 3, 4))
    assert "station=15156" in url
    assert "thema=gws" in url
    assert "smode=c" in url
    assert "sdatum=02.01.2025" in url
    assert "senddatum=04.03.2026" in url


# --------------------------------------------------------------------------- #
# Provider (fake session / bundled station list)
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.status = 200

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def read(self) -> bytes:
        return self._body


class _FakeSession:
    """Serves the captured CSV for every GET and records the URLs."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.urls: list[str] = []

    def get(self, url: str, **_: object) -> _FakeResponse:
        self.urls.append(url)
        return _FakeResponse(self._body)


async def test_search_radius_returns_nearby_stations() -> None:
    """Search around station 1's location returns it (nearest) from the bundle."""
    provider = WasserportalBeProvider(_FakeSession(_CSV_BYTES))  # type: ignore[arg-type]
    stations = await provider.async_search_radius(52.62308, 13.29247, 5)
    assert stations, "expected at least one station near station 1"
    assert stations[0].station_id == "1"
    assert stations[0].provider == "wasserportal_be"
    assert stations[0].distance_km is not None and stations[0].distance_km < 0.1
    # nearest-first ordering
    dists = [s.distance_km for s in stations]
    assert dists == sorted(dists)


async def test_search_query_matches_id_and_name() -> None:
    """A free-text query matches station id / name substrings from the bundle."""
    provider = WasserportalBeProvider(_FakeSession(_CSV_BYTES))  # type: ignore[arg-type]
    by_id = await provider.async_search_query("1")
    assert any(s.station_id == "1" for s in by_id)
    by_name = await provider.async_search_query("Reinickendorf")
    assert by_name and all("Reinickendorf" in s.name for s in by_name)


async def test_fetch_returns_latest_and_history() -> None:
    """Fetch returns the newest value (m ü. NHN) and the recent series."""
    session = _FakeSession(_CSV_BYTES)
    provider = WasserportalBeProvider(session)  # type: ignore[arg-type]
    reading = await provider.async_fetch(
        ProviderStation(provider="wasserportal_be", station_id="1", name="GWM 1")
    )
    assert reading.value == 33.41
    assert reading.unit == "m"
    assert reading.timestamp == datetime(2026, 7, 13)
    assert len(reading.history) > 1
    assert "Wasserportal Berlin" in reading.attribution
    # the fetch hit the daily CSV export for station 1
    assert session.urls and "station=1" in session.urls[0]
