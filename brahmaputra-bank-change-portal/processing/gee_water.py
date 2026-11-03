"""Water masks from Google Earth Engine (S2 MNDWI, S1 VV). Same math as the STAC path."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from shapely.geometry import mapping

from .crs import CrsBundle
from .gee_init import require_ee


def _s2_mask(ee, image):
    scl = image.select("SCL")
    clear = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(0))
    return image.updateMask(clear).divide(10000.0)


def s2_water_image(geom, start: str, end: str):
    ee = require_ee()
    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geom)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
        .map(lambda img: _s2_mask(ee, img))
    )
    median = col.median()
    mndwi = median.normalizedDifference(["B3", "B11"])
    return mndwi.gt(0.1).rename("water"), {
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "method": "MNDWI",
        "threshold": 0.1,
        "sensor": "sentinel-2",
        "scene_count": int(col.size().getInfo()),
    }


def s1_water_image(geom, start: str, end: str):
    ee = require_ee()
    col = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(geom)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .select("VV")
    )
    median = col.median()
    return median.lt(-16.0).rename("water"), {
        "collection": "COPERNICUS/S1_GRD",
        "method": "VV_backscatter_threshold",
        "threshold_db": -16.0,
        "sensor": "sentinel-1",
        "scene_count": int(col.size().getInfo()),
    }


def download_mask(image, region, scale: float, crs_wkt: str) -> tuple[np.ndarray, rasterio.Affine]:
    """Download a small water-mask GeoTIFF via getDownloadURL."""
    url = image.toByte().getDownloadURL(
        {
            "scale": scale,
            "crs": crs_wkt,
            "region": region,
            "format": "GEO_TIFF",
            "maxPixels": 1e9,
        }
    )
    import urllib.request

    with urllib.request.urlopen(url, timeout=180) as response:
        blob = response.read()
    with MemoryFile(blob) as mem, mem.open() as src:
        arr = src.read(1)
        return arr, src.transform


def fetch_water_mask_gee(
    bounds_m: tuple[float, float, float, float],
    bundle: CrsBundle,
    start: str,
    end: str,
    sensor: str,
    pixel_m: float,
    out_tif: Path,
) -> dict:
    ee = require_ee()
    minx, miny, maxx, maxy = bounds_m
    corners = [
        bundle.to_lonlat.transform(minx, miny),
        bundle.to_lonlat.transform(maxx, miny),
        bundle.to_lonlat.transform(maxx, maxy),
        bundle.to_lonlat.transform(minx, maxy),
    ]
    region = ee.Geometry.Polygon([[[x, y] for x, y in corners]], proj="EPSG:4326", evenOdd=True)
    if sensor == "sentinel-1":
        image, meta = s1_water_image(region, start, end)
    else:
        image, meta = s2_water_image(region, start, end)
    arr, transform = download_mask(image, region, pixel_m, bundle.projected.to_wkt())
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_tif,
        "w",
        driver="GTiff",
        height=arr.shape[0],
        width=arr.shape[1],
        count=1,
        dtype="uint8",
        crs=bundle.projected.to_wkt(),
        transform=transform,
        compress="lzw",
    ) as dst:
        dst.write(arr.astype("uint8"), 1)
    meta["backend"] = "google_earth_engine"
    meta["window"] = [start, end]
    return meta
