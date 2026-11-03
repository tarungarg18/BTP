"""Discover Sentinel-1, Sentinel-2, and Landsat scenes over the Assam corridor via GEE."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from shapely.geometry import mapping

from .aoi import CORRIDOR_BUFFER_M, mainstem_line


def study_geojson() -> dict:
    return mapping(mainstem_line().buffer(0.12))


def discover(start_date: str, end_date: str) -> list[dict]:
    """Return acquisition metadata. Requires earthengine-api + GEE_PROJECT."""
    try:
        import ee
    except ImportError as exc:
        raise RuntimeError("earthengine-api is not installed") from exc

    project = os.environ.get("GEE_PROJECT")
    if not project:
        raise RuntimeError("Set GEE_PROJECT to a Google Cloud / Earth Engine project id")

    ee.Initialize(project=project)
    geom = ee.Geometry.Polygon(study_geojson()["coordinates"])
    rows: list[dict] = []

    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geom)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
    )
    s1 = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(geom)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
    )
    ls = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
        .filterBounds(geom)
        .filterDate(start_date, end_date)
    )

    def collect(col, sensor: str) -> None:
        size = col.size().getInfo()
        if size == 0:
            return
        info = col.limit(80).getInfo()
        for feat in info.get("features", []):
            props = feat.get("properties", {})
            rows.append(
                {
                    "sensor": sensor,
                    "scene_id": feat.get("id"),
                    "start_time": props.get("system:time_start"),
                    "cloud_percent": props.get("CLOUDY_PIXEL_PERCENTAGE")
                    or props.get("CLOUD_COVER"),
                    "orbit": props.get("orbitProperties_pass") or props.get("orbit"),
                    "status": "discovered",
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    collect(s2, "sentinel-2")
    collect(s1, "sentinel-1")
    collect(ls, "landsat")
    return rows


if __name__ == "__main__":
    import json

    print(json.dumps({"aoi_note": "Assam main stem buffer", "count_requires_gee": True}, indent=2))
