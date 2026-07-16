"""Tests for the LfU Brandenburg (APW) groundwater provider.

The parse helpers run against **real captured payloads** in
``tests/fixtures/lfu_bb/`` (see ``docs/research/apw-brandenburg.md``). The fetch
integration test drives the provider through a tiny fake aiohttp session, since
two of the AjaxPro calls share one URL and are only distinguished by the
``X-AjaxPro-Method`` header.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import pytest

from custom_components.niwis.providers.base import (
    ProviderError,
    ProviderStation,
)
from custom_components.niwis.providers.lfu_bb import (
    DEFAULT_NHN_PARAMETER,
    LfuBbProvider,
    extract_messreihen_from_zip,
    parse_messreihen_csv,
    parse_query_hits,
    parse_wcf_date,
    pick_nhn_parameter,
    to_wcf_date,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "lfu_bb"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _load_json(name: str) -> dict:
    return json.loads(_load(name))


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_parse_query_hits_extracts_mkz_name_msid() -> None:
    """The AxExecuteQuery reply yields the MKZ, name and internal msid."""
    hits = parse_query_hits(_load_json("axexecutequery_25500006.json"))
    assert len(hits) == 1
    assert hits[0] == {"nummer": "25500006", "name": "Grimme", "msid": "8449"}


def test_pick_nhn_parameter_prefers_nhn() -> None:
    """The NHN (height-system) water-level parameter is selected."""
    assert pick_nhn_parameter(_load_json("axparameterchoice_8449.json")) == 50503000


def test_pick_nhn_parameter_falls_back() -> None:
    """An empty choice falls back to the known default parameter id."""
    assert pick_nhn_parameter({"value": {"parameterAuswahl": []}}) == (
        DEFAULT_NHN_PARAMETER
    )


def test_parse_messreihen_csv_real_series() -> None:
    """The real 1962–2024 series parses to chronological (date, value) pairs."""
    samples = parse_messreihen_csv(_load("messreihen_25500006.csv"))
    assert len(samples) == 2768
    assert samples[0] == (datetime(1962, 11, 1), 26.32)
    assert samples[-1] == (datetime(2024, 7, 3), 25.19)
    # chronological
    assert all(a[0] <= b[0] for a, b in pairwise(samples))
    # German decimal comma handled
    assert samples[1][1] == 26.38


def test_parse_messreihen_csv_skips_gaps_and_headers() -> None:
    """Header/summary lines and empty values are ignored."""
    text = (
        '﻿;"Mengendaten"\r\n'
        '"Zeitpunkt";"Wasserstand(NHN) [mNHN]"\r\n'
        '01.03.2024;"25"\r\n'
        '02.03.2024;""\r\n'  # gap
        '03.03.2024;"25,5"\r\n'
    )
    samples = parse_messreihen_csv(text)
    assert samples == [
        (datetime(2024, 3, 1), 25.0),
        (datetime(2024, 3, 3), 25.5),
    ]


def test_wcf_date_roundtrip() -> None:
    """WCF /Date(ms)/ formatting and parsing are inverse."""
    dt = datetime(2024, 1, 1, tzinfo=UTC)
    assert to_wcf_date(dt) == "/Date(1704067200000)/"
    assert parse_wcf_date("/Date(1704067200000)/") == dt


def test_parse_wcf_date_from_fixture() -> None:
    """The captured Zeitraum decodes to the expected span."""
    zr = _load_json("axgetzeitraum_8449.json")["value"]
    assert parse_wcf_date(zr["anfang"]).date().isoformat() == "1962-11-01"
    assert parse_wcf_date(zr["ende"]).date().isoformat() == "2024-07-03"


def test_extract_messreihen_from_zip() -> None:
    """The messreihen CSV is located and decoded from an export ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("25500006,Grimme/Metadaten.csv", "x")
        zf.writestr(
            "25500006,Grimme/25500006,Grimme_messreihen.csv",
            _load("messreihen_25500006.csv").encode("utf-8"),
        )
    text = extract_messreihen_from_zip(buf.getvalue())
    assert "Zeitpunkt" in text
    assert len(parse_messreihen_csv(text)) == 2768


def test_extract_messreihen_missing_raises() -> None:
    """A ZIP without a messreihen CSV is an error."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Impressum.pdf", "x")
    with pytest.raises(ProviderError):
        extract_messreihen_from_zip(buf.getvalue())


# --------------------------------------------------------------------------- #
# Provider (fake session)
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, *, text: str = "", data: bytes = b"") -> None:
        self._text, self._data = text, data

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def text(self) -> str:
        return self._text

    async def read(self) -> bytes:
        return self._data


class _FakeSession:
    """Serves the APW chain: landing GET, AjaxPro POSTs, export ZIP download."""

    def __init__(
        self,
        zip_bytes: bytes,
        *,
        empty_zeitraum: bool = False,
        empty_query: bool = False,
    ) -> None:
        self._zip = zip_bytes
        self._empty_zeitraum = empty_zeitraum
        self._empty_query = empty_query
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> _FakeResponse:
        self.calls.append(f"GET {url.split('?')[0]}")
        if "ogc.ashx" in url:
            return _FakeResponse(data=self._zip)
        return _FakeResponse(text="<html>landing</html>")

    def post(self, url: str, *, data: str, headers: dict, **_: object) -> _FakeResponse:
        method = headers["X-AjaxPro-Method"]
        self.calls.append(f"POST {method}")
        if method == "AxExecuteQuery":
            if self._empty_query:
                return _FakeResponse(text=json.dumps({"value": {}}))
            return _FakeResponse(text=_load("axexecutequery_25500006.json"))
        if method == "AxGetAvailableParameterChoice":
            return _FakeResponse(text=_load("axparameterchoice_8449.json"))
        if method == "AxGetZeitraum":
            if self._empty_zeitraum:
                return _FakeResponse(
                    text=json.dumps({"value": {"anfang": None, "ende": None}})
                )
            return _FakeResponse(text=_load("axgetzeitraum_8449.json"))
        if method == "AxExport":
            body = json.loads(data)
            assert body["format"] == 1
            assert body["parameterIds"] == [50503000]
            return _FakeResponse(
                text=json.dumps(
                    {"value": "/cminetusr/ogc.ashx?file=x.zip&mimetype=zip"}
                )
            )
        raise AssertionError(f"unexpected method {method}")


def _export_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "25500006,Grimme/25500006,Grimme_messreihen.csv",
            _load("messreihen_25500006.csv").encode("utf-8"),
        )
    return buf.getvalue()


async def test_async_search_query_returns_station() -> None:
    """A query search returns a station carrying the resolved msid."""
    session = _FakeSession(_export_zip())
    provider = LfuBbProvider(session)  # type: ignore[arg-type]
    stations = await provider.async_search_query("25500006")
    assert len(stations) == 1
    station = stations[0]
    assert station.provider == "lfu_bb"
    assert station.station_id == "25500006"
    assert station.name == "Grimme"
    assert station.extra["msid"] == 8449


async def test_async_fetch_full_chain() -> None:
    """End-to-end fetch: resolve params, export, parse latest + history."""
    session = _FakeSession(_export_zip())
    provider = LfuBbProvider(session)  # type: ignore[arg-type]
    station = ProviderStation(
        provider="lfu_bb", station_id="25500006", name="Grimme", extra={"msid": 8449}
    )
    reading = await provider.async_fetch(station)
    assert reading.unit == "m"
    assert reading.value == 25.19
    assert reading.timestamp == datetime(2024, 7, 3)
    assert len(reading.history) == 2768
    assert "LfU" in reading.attribution
    # msid was supplied, so no attribute query was needed to resolve it
    assert "POST AxGetAvailableParameterChoice" in session.calls
    assert "POST AxExport" in session.calls


async def test_async_fetch_empty_series_returns_unknown() -> None:
    """A station whose level series is empty yields value None, no export call."""
    session = _FakeSession(_export_zip(), empty_zeitraum=True)
    provider = LfuBbProvider(session)  # type: ignore[arg-type]
    station = ProviderStation(
        provider="lfu_bb",
        station_id="35480875",
        name="Münchehofe",
        extra={"msid": 17416},
    )
    reading = await provider.async_fetch(station)
    assert reading.value is None
    assert reading.history == []
    assert "POST AxExport" not in session.calls  # short-circuited


async def test_async_fetch_unknown_mkz_is_graceful() -> None:
    """A station absent from APW's level theme yields value None, no crash."""
    session = _FakeSession(_export_zip(), empty_query=True)
    provider = LfuBbProvider(session)  # type: ignore[arg-type]
    station = ProviderStation(
        provider="lfu_bb", station_id="35480874", name="Münchehofe, Hoppegarten"
    )
    reading = await provider.async_fetch(station)
    assert reading.value is None
    assert reading.history == []
    assert reading.unit == "m"


async def test_search_radius_from_bundled_stations() -> None:
    """Radius search finds nearby stations (from the bundled coordinate list)."""
    provider = LfuBbProvider(_FakeSession(b""))  # type: ignore[arg-type]
    # Around Grimme (53.4225 / 14.1447): it must be the nearest hit.
    stations = await provider.async_search_radius(53.4225, 14.1447, 20)
    assert stations
    assert stations[0].station_id == "25500006"
    assert stations[0].name == "Grimme"
    assert stations[0].distance_km is not None and stations[0].distance_km < 1
    assert stations[0].latitude == 53.4225
    # sorted nearest-first
    assert all(
        (a.distance_km or 0) <= (b.distance_km or 0)
        for a, b in zip(stations, stations[1:], strict=False)
    )


async def test_search_radius_empty_when_far() -> None:
    """A location far from Brandenburg yields no stations."""
    provider = LfuBbProvider(_FakeSession(b""))  # type: ignore[arg-type]
    assert await provider.async_search_radius(48.0, 11.5, 10) == []
