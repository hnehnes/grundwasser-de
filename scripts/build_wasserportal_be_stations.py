#!/usr/bin/env python3
"""Regenerate the bundled Berlin Wasserportal station list for wasserportal_be.

The Wasserportal station table
(``messwerte.php?anzeige=tabelle&thema=gws``) lists ~893 groundwater
(``gws``) stations but carries **no coordinates**. Each station's coordinates
live on its own info page
(``station.php?anzeige=i&thema=gws&station=<ID>``) as *Rechtswert/Hochwert
(UTM 33 N)* = EPSG:25833. This script:

1. downloads the station table and extracts every station id (+ Bezirk),
2. for each station downloads the info page and reads its UTM33 coordinates,
3. converts them **offline** to WGS84 (pyproj — used *only here*, never at
   runtime), and
4. writes ``custom_components/grundwasser_de/providers/
   wasserportal_be_stations.json`` as a compact
   ``[{station_id, name, lat, lon}]`` list.

It throttles (``time.sleep``) to stay polite to the portal. Because fetching
893 info pages is slow, ``--limit N`` restricts the run to the first N table
stations (the bundle is regenerable; a partial bundle still works). Pass
``--limit 0`` (or omit ``--limit``) for the full set.

Usage (needs network + ``pip install pyproj``):
    python scripts/build_wasserportal_be_stations.py            # all stations
    python scripts/build_wasserportal_be_stations.py --limit 150

This is a maintenance script, not shipped/imported at runtime.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://wasserportal.berlin.de"
LIST_URL = f"{BASE}/messwerte.php?anzeige=tabelle&thema=gws"
INFO_URL = f"{BASE}/station.php?anzeige=i&thema=gws&station={{id}}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"
ENCODING = "iso-8859-15"

OUT = (
    Path(__file__).resolve().parent.parent
    / "custom_components/grundwasser_de/providers/wasserportal_be_stations.json"
)

#: one table row: the station-id link followed by the Bezirk cell.
_ROW_RE = re.compile(
    r"station\.php\?anzeige=i&thema=gws&station=(\d+)'>\d+</a></td>\s*"
    r"<td>([^<]*)</td>",
    re.IGNORECASE,
)
_RECHTS_RE = re.compile(
    r"Rechtswert \(UTM 33 N\)</th>\s*<td[^>]*>\s*([\d.]+)", re.IGNORECASE
)
_HOCH_RE = re.compile(
    r"Hochwert \(UTM 33 N\)</th>\s*<td[^>]*>\s*([\d.]+)", re.IGNORECASE
)


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        return resp.read().decode(ENCODING, errors="replace")


def _parse_list(html: str) -> list[tuple[str, str]]:
    """Return ``[(station_id, bezirk)]`` from the ``gws`` station table."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for station_id, bezirk in _ROW_RE.findall(html):
        if station_id in seen:
            continue
        seen.add(station_id)
        out.append((station_id, bezirk.strip()))
    return out


def _parse_coords(html: str) -> tuple[int, int] | None:
    """Return ``(rechtswert, hochwert)`` UTM33 easting/northing, or ``None``."""
    rechts = _RECHTS_RE.search(html)
    hoch = _HOCH_RE.search(html)
    if not rechts or not hoch:
        return None
    try:
        return int(rechts.group(1).replace(".", "")), int(
            hoch.group(1).replace(".", "")
        )
    except ValueError:
        return None


def main() -> None:
    """Build the bundle: parse the table, resolve coords, write the JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="only the first N table stations (0 = all ~893)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="seconds to wait between info-page requests (politeness)",
    )
    args = parser.parse_args()

    from pyproj import Transformer  # local import: build-time dependency only

    transformer = Transformer.from_crs("EPSG:25833", "EPSG:4326", always_xy=True)

    print(f"fetching station list … {LIST_URL}")
    rows = _parse_list(_get(LIST_URL))
    print(f"  {len(rows)} groundwater stations in the table")
    if args.limit:
        rows = rows[: args.limit]
        print(f"  limited to first {len(rows)}")

    stations: list[dict] = []
    for index, (station_id, bezirk) in enumerate(rows, start=1):
        try:
            info = _get(INFO_URL.format(id=station_id))
        except OSError as err:
            print(f"  ! station {station_id}: request failed: {err}")
            continue
        coords = _parse_coords(info)
        if coords is None:
            print(f"  ! station {station_id}: no UTM33 coordinates, skipped")
            continue
        lon, lat = transformer.transform(*coords)
        name = f"GWM {station_id}" + (f" ({bezirk})" if bezirk else "")
        stations.append(
            {
                "station_id": station_id,
                "name": name,
                "lat": round(lat, 5),
                "lon": round(lon, 5),
            }
        )
        if index % 25 == 0 or index == len(rows):
            print(f"  {index}/{len(rows)} done ({len(stations)} with coords)")
        time.sleep(args.sleep)

    stations.sort(key=lambda s: int(s["station_id"]))
    OUT.write_text(
        json.dumps(stations, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"\n{len(stations)} stations written to {OUT}")


if __name__ == "__main__":
    sys.exit(main())
