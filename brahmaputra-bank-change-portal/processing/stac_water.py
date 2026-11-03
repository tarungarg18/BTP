"""Copernicus Sentinel water via Planetary Computer STAC.

This is the same Sentinel-2 L2A / Sentinel-1 radar family that GEE serves as
COPERNICUS/S2_SR_HARMONIZED and COPERNICUS/S1_GRD. Used when GEE_PROJECT is unset.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import planetary_computer as pc
import rasterio
from pystac_client import Client
from rasterio.crs import CRS as RioCRS
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window
from rasterio.windows import transform as window_transform

from .crs import CrsBundle

CATALOG = "https://planetarycomputer.microsoft.com/api/stac/v1"
SCL_CLOUD = {3, 8, 9, 10}
MNDWI_THRESHOLD = 0.1
VV_DB_THRESHOLD = -16.0


def _catalog():
    return Client.open(CATALOG, modifier=pc.sign_inplace)


def _dest_grid(bounds_m: tuple[float, float, float, float], pixel_m: float):
    minx, miny, maxx, maxy = bounds_m
    minx = np.floor(minx / pixel_m) * pixel_m
    miny = np.floor(miny / pixel_m) * pixel_m
    maxx = np.ceil(maxx / pixel_m) * pixel_m
    maxy = np.ceil(maxy / pixel_m) * pixel_m
    width = int(round((maxx - minx) / pixel_m))
    height = int(round((maxy - miny) / pixel_m))
    transform = from_origin(minx, maxy, pixel_m, pixel_m)
    return (minx, miny, maxx, maxy), transform, width, height


def _lonlat_bbox(bounds_m, bundle: CrsBundle) -> list[float]:
    minx, miny, maxx, maxy = bounds_m
    pts = [
        bundle.to_lonlat.transform(minx, miny),
        bundle.to_lonlat.transform(maxx, miny),
        bundle.to_lonlat.transform(maxx, maxy),
        bundle.to_lonlat.transform(minx, maxy),
    ]
    xs, ys = zip(*pts)
    return [min(xs), min(ys), max(xs), max(ys)]


def _dest_window(item_bbox, transform, width: int, height: int, dst_crs, pad_px: int = 8) -> Window | None:
    minx, miny, maxx, maxy = transform_bounds("EPSG:4326", dst_crs, *item_bbox, densify_pts=8)
    col0, row0 = ~transform * (minx, maxy)
    col1, row1 = ~transform * (maxx, miny)
    c0, c1 = int(np.floor(min(col0, col1))) - pad_px, int(np.ceil(max(col0, col1))) + pad_px
    r0, r1 = int(np.floor(min(row0, row1))) - pad_px, int(np.ceil(max(row0, row1))) + pad_px
    c0, r0 = max(c0, 0), max(r0, 0)
    c1, r1 = min(c1, width), min(r1, height)
    if c1 <= c0 or r1 <= r0:
        return None
    return Window(c0, r0, c1 - c0, r1 - r0)


def _read_band(href: str, dst: np.ndarray, transform, dst_crs, resampling) -> None:
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff"):
        with rasterio.open(href) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=dst,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=dst_crs,
                resampling=resampling,
                src_nodata=src.nodata,
                dst_nodata=np.nan,
            )


def _best_s2_items(bbox, start: str, end: str, max_cloud: float = 35.0):
    catalog = _catalog()
    items = list(
        catalog.search(
            collections=["sentinel-2-l2a"],
            bbox=bbox,
            datetime=f"{start}/{end}",
            query={"eo:cloud_cover": {"lt": max_cloud}},
        ).items()
    )
    by_tile: dict[str, list] = defaultdict(list)
    for item in items:
        tile = item.properties.get("s2:mgrs_tile") or item.id
        by_tile[tile].append(item)
    chosen = []
    for group in by_tile.values():
        group.sort(key=lambda it: (it.properties.get("eo:cloud_cover", 99), it.datetime or ""))
        chosen.extend(group[:1])
    chosen.sort(key=lambda it: it.properties.get("eo:cloud_cover", 99))
    return chosen


def mosaic_s2_water(
    bounds_m: tuple[float, float, float, float],
    bundle: CrsBundle,
    start: str,
    end: str,
    pixel_m: float,
    out_tif: Path,
) -> dict:
    bbox = _lonlat_bbox(bounds_m, bundle)
    items = _best_s2_items(bbox, start, end)
    if not items:
        raise RuntimeError(f"No Sentinel-2 scenes for {start}–{end}")

    _, transform, width, height = _dest_grid(bounds_m, pixel_m)
    dst_crs = RioCRS.from_wkt(bundle.projected.to_wkt())
    sum_m = np.zeros((height, width), dtype=np.float32)
    count = np.zeros((height, width), dtype=np.uint8)

    used = []
    print(f"S2 mosaic {len(items)} MGRS tiles → {width}x{height} @ {pixel_m} m", flush=True)
    for item in items:
        assets = item.assets
        if "B03" not in assets or "B11" not in assets or not item.bbox:
            continue
        win = _dest_window(item.bbox, transform, width, height, dst_crs)
        if win is None:
            continue
        r0, c0 = int(win.row_off), int(win.col_off)
        rh, cw = int(win.height), int(win.width)
        win_t = window_transform(win, transform)
        green = np.full((rh, cw), np.nan, dtype=np.float32)
        swir = np.full((rh, cw), np.nan, dtype=np.float32)
        scl = np.full((rh, cw), np.nan, dtype=np.float32)
        try:
            _read_band(assets["B03"].href, green, win_t, dst_crs, Resampling.bilinear)
            _read_band(assets["B11"].href, swir, win_t, dst_crs, Resampling.bilinear)
            if "SCL" in assets:
                _read_band(assets["SCL"].href, scl, win_t, dst_crs, Resampling.nearest)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {item.id}: {exc}")
            continue
        valid = np.isfinite(green) & np.isfinite(swir) & (green > 0) & (swir > 0)
        if "SCL" in assets:
            scl_i = np.nan_to_num(scl, nan=0).astype(np.int16)
            valid &= ~np.isin(scl_i, list(SCL_CLOUD))
        mndwi = (green - swir) / (green + swir + 1e-6)
        block_sum = sum_m[r0 : r0 + rh, c0 : c0 + cw]
        block_cnt = count[r0 : r0 + rh, c0 : c0 + cw]
        block_sum[valid] += mndwi[valid]
        block_cnt[valid] += 1
        used.append(
            {
                "id": item.id,
                "date": item.datetime.date().isoformat() if item.datetime else None,
                "cloud_percent": item.properties.get("eo:cloud_cover"),
                "mgrs": item.properties.get("s2:mgrs_tile"),
            }
        )
        print(f"  S2 {item.id} cloud={item.properties.get('eo:cloud_cover')} valid={int(valid.sum())}", flush=True)

    if not used or int(count.max()) == 0:
        raise RuntimeError("Sentinel-2 mosaic produced no valid pixels")

    mean = np.divide(sum_m, count, out=np.zeros_like(sum_m), where=count > 0)
    water = ((count > 0) & (mean > MNDWI_THRESHOLD)).astype(np.uint8)
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_tif,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint8",
        crs=dst_crs,
        transform=transform,
        compress="lzw",
    ) as dst:
        dst.write(water, 1)
        dst.update_tags(method="MNDWI", threshold=str(MNDWI_THRESHOLD), scenes=str(len(used)))

    return {
        "backend": "planetary_computer_stac",
        "collection": "sentinel-2-l2a (same satellite as GEE COPERNICUS/S2_SR_HARMONIZED)",
        "method": "MNDWI",
        "threshold": MNDWI_THRESHOLD,
        "sensor": "sentinel-2",
        "scene_count": len(used),
        "scenes": used[:40],
        "window": [start, end],
        "valid_pixels": int((count > 0).sum()),
        "water_pixels": int(water.sum()),
    }


def mosaic_s1_water(
    bounds_m: tuple[float, float, float, float],
    bundle: CrsBundle,
    start: str,
    end: str,
    pixel_m: float,
    out_tif: Path,
) -> dict:
    bbox = _lonlat_bbox(bounds_m, bundle)
    catalog = _catalog()
    items = list(
        catalog.search(collections=["sentinel-1-rtc"], bbox=bbox, datetime=f"{start}/{end}").items()
    )
    if not items:
        raise RuntimeError(f"No Sentinel-1 RTC scenes for {start}–{end}")

    _, transform, width, height = _dest_grid(bounds_m, pixel_m)
    dst_crs = RioCRS.from_wkt(bundle.projected.to_wkt())
    sum_v = np.zeros((height, width), dtype=np.float32)
    count = np.zeros((height, width), dtype=np.uint8)
    used = []
    for item in items:
        if "vv" not in item.assets:
            continue
        vv = np.full((height, width), np.nan, dtype=np.float32)
        try:
            _read_band(item.assets["vv"].href, vv, transform, dst_crs, Resampling.bilinear)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {item.id}: {exc}")
            continue
        valid = np.isfinite(vv) & (vv > 0)
        db = 10.0 * np.log10(np.clip(vv, 1e-8, None))
        sum_v[valid] += db[valid]
        count[valid] += 1
        used.append({"id": item.id, "date": item.datetime.date().isoformat() if item.datetime else None})
        print(f"  S1 {item.id} valid={int(valid.sum())}", flush=True)

    if not used:
        raise RuntimeError("Sentinel-1 mosaic produced no valid pixels")
    mean = np.divide(sum_v, count, out=np.zeros_like(sum_v), where=count > 0)
    water = ((count > 0) & (mean < VV_DB_THRESHOLD)).astype(np.uint8)
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_tif,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint8",
        crs=dst_crs,
        transform=transform,
        compress="lzw",
    ) as dst:
        dst.write(water, 1)

    return {
        "backend": "planetary_computer_stac",
        "collection": "sentinel-1-rtc (same radar family as GEE COPERNICUS/S1_GRD)",
        "method": "VV_backscatter_threshold",
        "threshold_db": VV_DB_THRESHOLD,
        "sensor": "sentinel-1",
        "scene_count": len(used),
        "scenes": used[:40],
        "window": [start, end],
        "water_pixels": int(water.sum()),
    }
