"""Unit tests for the NIWIS API helpers."""

from __future__ import annotations

from custom_components.grundwasser_de.api import (
    Station,
    build_display_name,
    haversine_km,
)


def test_missing_value_sentinel_becomes_none() -> None:
    """The -777 gap sentinel is treated as no value; real lows are kept."""
    gap = Station.from_payload(
        "WASSERSTAND", {"nummer": "X", "aktuellerMesswert": -777.0}
    )
    assert gap.aktueller_messwert is None

    real = Station.from_payload(
        "WASSERSTAND", {"nummer": "Y", "aktuellerMesswert": -1.0}
    )
    assert real.aktueller_messwert == -1.0


def test_display_name_groundwater_uses_ortslage() -> None:
    """Groundwater stations prefer the location over a bare number."""
    details = {"name": "5308", "ortslage": "Niederschönhausen (Pankow)"}
    assert (
        build_display_name(details, "5308", ["GRUNDWASSER"])
        == "Niederschönhausen (Pankow)"
    )


def test_display_name_surface_appends_gewaesser() -> None:
    """Surface stations get their gauge name plus the water body."""
    details = {"name": "Woltersdorf OP", "gewaesser": "Rüdersdorfer"}
    assert (
        build_display_name(details, "Woltersdorf OP", ["WASSERSTAND"])
        == "Woltersdorf OP (Rüdersdorfer)"
    )


def test_display_name_no_duplicate_gewaesser() -> None:
    """A gauge name that already contains the water body is not duplicated."""
    details = {
        "name": "Berlin-Köpenick (Spree-Oder-Wasserstraße)",
        "gewaesser": "Spree-Oder-Wasserstraße",
    }
    assert (
        build_display_name(details, "x", ["WASSERSTAND"])
        == "Berlin-Köpenick (Spree-Oder-Wasserstraße)"
    )


def test_display_name_falls_back_when_no_details() -> None:
    """Without master data the map name is kept."""
    assert build_display_name({}, "Inkofen (Amper)", ["ABFLUSS"]) == "Inkofen (Amper)"


def test_haversine_known_distance() -> None:
    """Sanity-check the haversine helper against a known distance."""
    # Hoppegarten -> Berlin center is roughly 20 km.
    dist = haversine_km(52.5174, 13.6416, 52.5200, 13.4050)
    assert 14 < dist < 20
