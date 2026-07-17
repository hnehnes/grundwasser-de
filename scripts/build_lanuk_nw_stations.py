#!/usr/bin/env python3
"""Regenerate the bundled NRW (LANUK) station list for the lanuk_nw provider.

Combines the two OpenHygrisC bulk files (opengeodata.nrw.de, dl-de/zero-2.0):

1. **Coordinates & names** — ``OpenHygrisC_gw-messstelle_…zip`` (~29 MB): one row
   per station with ``E32``/``N32`` in EPSG:25832 (→ WGS84), ``name`` and
   ``gemeinde_name``. Kept only if the station is a water-level station whose
   *location* and *level values* are both released for publication and whose
   coordinates are not anonymised (Güte wells on private ground get their last
   two coordinate digits replaced by ``xx``).
2. **Fetchability** — ``OpenHygrisC_gw-wasserstand_2020-2029_…zip`` (~255 MB):
   only stations that actually carry a value in the current-decade file are kept,
   so the radius search offers only stations that return data (mirrors lfu_bb).

Only surviving stations are written (``custom_components/grundwasser_de/providers/
lanuk_nw_stations.json``) as ``{id, name, lat, lon, gemeinde}``. pyproj is used
here only, at build time — never at runtime.

Usage (needs network + ``pip install pyproj``; downloads ~284 MB):
    python scripts/build_lanuk_nw_stations.py

This is a maintenance script, not shipped/imported at runtime.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
import zipfile
from pathlib import Path

BASE = (
    "https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/grundwasser/hygrisc"
)
MESSSTELLE_URL = f"{BASE}/OpenHygrisC_gw-messstelle_EPSG25832_CSV.zip"
WASSERSTAND_URL = f"{BASE}/OpenHygrisC_gw-wasserstand_2020-2029_EPSG25832_CSV.zip"

OUT = (
    Path(__file__).resolve().parent.parent
    / "custom_components/grundwasser_de/providers/lanuk_nw_stations.json"
)

_UA = "Mozilla/5.0 (compatible; build-lanuk-nw/1.0)"


def _download(url: str) -> bytes:
    print(f"  downloading {url} …")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})  # noqa: S310
    with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310
        return resp.read()


def _open_only_csv(data: bytes) -> io.TextIOWrapper:
    archive = zipfile.ZipFile(io.BytesIO(data))
    member = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
    return io.TextIOWrapper(archive.open(member), encoding="utf-8", newline="")


def _stations_with_values() -> set[str]:
    """Return the set of station ids present in the current-decade level file."""
    ids: set[str] = set()
    reader = csv.DictReader(_open_only_csv(_download(WASSERSTAND_URL)), delimiter=";")
    for row in reader:
        value = (row.get("wasserstd_m") or "").strip()
        if value and value != "-":
            ids.add((row.get("messstelle_id") or "").strip())
    return ids


def _usable_stations(have_value: set[str]) -> list[dict]:
    from pyproj import Transformer

    tf = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
    out: list[dict] = []
    reader = csv.DictReader(_open_only_csv(_download(MESSSTELLE_URL)), delimiter=";")
    for row in reader:
        if (row.get("wasserstandsmessstelle") or "").strip().lower() != "ja":
            continue
        if (row.get("freigabe_wstd") or "").strip().lower() != "ja":
            continue
        if (row.get("freigabe_lage") or "").strip().lower() != "ja":
            continue
        east = (row.get("e32") or "").strip()
        north = (row.get("n32") or "").strip()
        if not east or not north or "X" in east.upper() or "X" in north.upper():
            continue  # anonymised coordinates
        station_id = (row.get("messstelle_id") or "").strip()
        if station_id not in have_value:
            continue
        try:
            lon, lat = tf.transform(float(east), float(north))
        except (ValueError, OverflowError):
            continue
        out.append(
            {
                "id": station_id,
                "name": (row.get("name") or "").strip() or station_id,
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "gemeinde": (row.get("gemeinde_name") or "").strip(),
            }
        )
    out.sort(key=lambda s: s["id"])
    return out


def main() -> None:
    """Build the bundled NRW station list from the two OpenHygrisC files."""
    print("1/2 collecting stations with a current water-level value …")
    have_value = _stations_with_values()
    print(f"     {len(have_value)} stations carry a value in 2020-2029 file")
    print("2/2 filtering messstelle master data + reprojecting to WGS84 …")
    stations = _usable_stations(have_value)
    OUT.write_text(
        json.dumps(stations, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {len(stations)} stations to {OUT}")


if __name__ == "__main__":
    main()
