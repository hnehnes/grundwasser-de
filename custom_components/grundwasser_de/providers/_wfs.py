"""Minimal async client for OGC **WFS 2.0.0** ``GetFeature`` queries.

Several state groundwater portals expose their station networks as a public,
unauthenticated WFS (Schleswig-Holstein, Rheinland-Pfalz, Mecklenburg-Vorpommern,
…). Many of these run **deegree** or **GeoServer**, which can serve
``application/geo+json`` and reproject to WGS84 on the fly (``srsName=EPSG:4326``),
so callers need neither a GML parser nor ``pyproj``.

This helper wraps the ``GetFeature`` request: it builds the URL, follows WFS
result paging (``count`` + ``startIndex``) and returns the raw GeoJSON feature
list (``[{"type": "Feature", "properties": {...}, "geometry": {...}}, …]``).

Keep it generic (base URL, ``type_name``, ``bbox``, ``srs_name``,
``output_format``) so RLP/MV can reuse it unchanged.

.. note:: WFS 2.0.0 with a URN CRS (``urn:ogc:def:crs:EPSG::4326``) uses
    **lat/lon** axis order, both for the ``BBOX`` argument and for returned
    GeoJSON coordinates on some servers. deegree (used by SH) honours GeoJSON's
    lon/lat convention for the returned geometry but expects lat/lon in the
    ``BBOX`` value — so callers building a ``bbox`` should pass it as
    ``minLat,minLon,maxLat,maxLon,<urn-crs>`` (see :func:`bbox_urn_4326`).
"""

from __future__ import annotations

from math import cos, radians
from typing import Any

from aiohttp import ClientError, ClientSession

from .base import ProviderError

_TIMEOUT = 60
_PAGE_SIZE = 1000
_MAX_FEATURES = 5000

#: URN form of WGS84 that makes WFS 2.0 reproject and use lat/lon axis order.
CRS_URN_4326 = "urn:ogc:def:crs:EPSG::4326"
#: GeoServer/deegree GeoJSON output format token.
OUTPUT_GEOJSON = "application/geo+json"


def bbox_urn_4326(lat: float, lon: float, radius_km: float) -> str:
    """Return a WFS-2.0 ``BBOX`` string around a point, in URN-4326 axis order.

    Axis order for ``urn:ogc:def:crs:EPSG::4326`` is **lat,lon**, so the value is
    ``minLat,minLon,maxLat,maxLon,<crs>``.
    """
    d_lat = radius_km / 111.0
    d_lon = radius_km / (111.0 * max(cos(radians(lat)), 0.01))
    return (
        f"{lat - d_lat},{lon - d_lon},{lat + d_lat},{lon + d_lon},{CRS_URN_4326}"
    )


async def get_features(
    session: ClientSession,
    base_url: str,
    type_name: str,
    *,
    srs_name: str = CRS_URN_4326,
    output_format: str = OUTPUT_GEOJSON,
    bbox: str | None = None,
    page_size: int = _PAGE_SIZE,
    max_features: int = _MAX_FEATURES,
    extra_params: dict[str, Any] | None = None,
) -> list[dict]:
    """Run a WFS 2.0 ``GetFeature`` and return its GeoJSON features.

    Follows result paging (``count`` + ``startIndex``) until a short page is
    returned or ``max_features`` is reached. Raises :class:`ProviderError` on any
    network error, non-200 status, or a non-JSON body (e.g. an XML
    ``ExceptionReport``).
    """
    features: list[dict] = []
    start_index = 0
    while True:
        params: dict[str, Any] = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": type_name,
            "outputFormat": output_format,
            "srsName": srs_name,
            "count": page_size,
            "startIndex": start_index,
        }
        if bbox is not None:
            params["bbox"] = bbox
        if extra_params:
            params.update(extra_params)
        try:
            async with session.get(
                base_url, params=params, timeout=_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    raise ProviderError(f"WFS HTTP {resp.status}")
                payload = await resp.json(content_type=None)
        except (TimeoutError, ClientError) as err:
            raise ProviderError(f"WFS request failed: {err}") from err
        except ValueError as err:  # non-JSON body (XML exception report)
            raise ProviderError(f"WFS returned non-JSON body: {err}") from err

        batch = (payload or {}).get("features") or []
        features.extend(batch)
        if len(batch) < page_size or len(features) >= max_features:
            break
        start_index += len(batch)
    return features[:max_features]
