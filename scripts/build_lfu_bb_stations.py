#!/usr/bin/env python3
"""Regenerate the bundled LfU-Brandenburg station list for the lfu_bb provider.

Combines two sources:

1. **Coordinates & names** — the LfU groundwater base-network shapefile
   ``gw_basis_mn.zip`` (EPSG:25833 → WGS84).
2. **Fetchability** — the APW (apw.brandenburg.de) attribute layer L305: which
   stations actually carry a *groundwater-level* series, plus their internal
   ``msid``. A station is level-bearing iff its map hit exposes a non-empty
   ``QURPRM_NHN_NW`` (the NW statistic); pure water-quality wells and stations
   absent from APW have it empty / are missing.

Only level-bearing stations are written (``custom_components/grundwasser_de/
providers/lfu_bb_stations.json``), each as ``{mkz, name, lat, lon, msid}`` — so
the radius search offers only stations that return data, and fetch can skip the
msid-resolution round-trip.

Usage (needs network + `pip install pyshp pyproj`):
    python scripts/build_lfu_bb_stations.py path/to/gw_basis_mn[.shp]

This is a maintenance script, not shipped/imported at runtime.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"
BASE = "https://apw.brandenburg.de"
THEME_ID = "256.397"
FILTER_TYPE = (
    "IDU.Core.Web.Controls.SelectionTools.IwanQueryEditor.AxTypes."
    "AxIOComparisonFilterString, IDU.Core, Version=1.0.0.0, "
    "Culture=neutral, PublicKeyToken=107e611434a88619"
)
SEL_URL = (
    f"{BASE}/ajaxpro/IDU.cardoMap3.WebV2.Controls.SelectionTools."
    "SelectionControl.SelectionControl,cardo.Map3Lib.ashx"
)
OUT = (
    Path(__file__).resolve().parent.parent
    / "custom_components/grundwasser_de/providers/lfu_bb_stations.json"
)

_STATION_RE = re.compile(r"Messstelle:\s*<b>\s*([^,<]+)")
_MSID_RE = re.compile(r"id_messstelle=(\d+)")
_NHN_NW_RE = re.compile(r"QURPRM_NHN_NW=([^&\"]*)")


def _curl(cookies: Path, method: str, body: str) -> str:
    return subprocess.run(
        ["curl", "-s", "-m", "90", "-A", UA, "-b", str(cookies),
         "-H", f"X-AjaxPro-Method: {method}",
         "-H", "Content-Type: text/plain; charset=UTF-8",
         "-e", f"{BASE}/?th=ZR_GW_ME", "--data", body, SEL_URL],
        capture_output=True, text=True, check=True,
    ).stdout


def _query_prefix(cookies: Path, prefix: str) -> dict[str, dict]:
    """Return ``{nummer: {msid, has_level}}`` for all APW stations under prefix."""
    body = json.dumps(
        {"themeIds": [THEME_ID], "filter": {
            "__type": FILTER_TYPE, "columnName": "nummer",
            "compareOperator": "Like", "values": [f"{prefix}%"]}}
    )
    payload = json.loads(_curl(cookies, "AxExecuteQuery", body))
    value = payload.get("value") or {}
    results: dict[str, dict] = {}
    for theme in value.get("singleThemeResult") or []:
        for hit in theme.get("Hits") or []:
            text = hit.get("Text") or ""
            nummer = _STATION_RE.search(text)
            if not nummer:
                continue
            msid = _MSID_RE.search(text)
            nhn_nw = _NHN_NW_RE.search(text)
            results[nummer.group(1).strip()] = {
                "msid": int(msid.group(1)) if msid else None,
                "has_level": bool(nhn_nw and nhn_nw.group(1).strip()),
            }
    return results


def _read_shapefile(path: Path) -> list[dict]:
    import shapefile  # pyshp
    from pyproj import Transformer

    tf = Transformer.from_crs("EPSG:25833", "EPSG:4326", always_xy=True)
    reader = shapefile.Reader(str(path.with_suffix("")))
    fields = [f[0] for f in reader.fields[1:]]
    out: list[dict] = []
    for sr in reader.iterShapeRecords():
        rec = dict(zip(fields, sr.record, strict=False))
        if not sr.shape.points:
            continue
        lon, lat = tf.transform(*sr.shape.points[0])
        mkz = str(rec.get("MKZ") or "").strip()
        name = (str(rec.get("MENA") or "").strip()
                or str(rec.get("LAGE") or "").strip())
        if mkz:
            out.append({"mkz": mkz, "name": name,
                        "lat": round(lat, 5), "lon": round(lon, 5)})
    return out


def main() -> None:
    """Build the bundled LfU-BB station list from shapefile + APW classification."""
    if len(sys.argv) < 2:
        sys.exit("usage: build_lfu_bb_stations.py path/to/gw_basis_mn[.shp]")
    cookies = Path("cookies.txt").resolve()
    subprocess.run(["curl", "-s", "-c", str(cookies), "-A", UA,
                    f"{BASE}/?th=ZR_GW_ME", "-o", "/dev/null"], check=True)

    shape = _read_shapefile(Path(sys.argv[1]))
    prefixes = sorted({s["mkz"][:2] for s in shape})
    apw: dict[str, dict] = {}
    for prefix in prefixes:
        found = _query_prefix(cookies, prefix)
        apw.update(found)
        print(f"  prefix {prefix}: {len(found)} APW-Stationen "
              f"({sum(v['has_level'] for v in found.values())} mit Wasserstand)")
        time.sleep(0.3)

    stations: list[dict] = []
    for st in shape:
        info = apw.get(st["mkz"])
        if info and info["has_level"] and info["msid"] is not None:
            stations.append({**st, "msid": info["msid"]})
    stations.sort(key=lambda s: s["mkz"])

    OUT.write_text(
        json.dumps(stations, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"\n{len(shape)} Shapefile-Stellen → {len(stations)} mit abrufbarem "
          f"Wasserstand geschrieben nach {OUT}")


if __name__ == "__main__":
    main()
