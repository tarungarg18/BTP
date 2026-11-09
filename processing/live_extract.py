"""15-day water masks from Google Earth Engine, same optical steps as our_btp.ipynb.

Optical water is Sentinel-2 NDWI (B3 - B8) / (B3 + B8) > 0 after the SCL cloud mask.
Microwave water is Sentinel-1 VV darker than -16 dB.
Each chosen date is the last day of a 15-day composite. An empty start date
uses the 15 days before that window. The GeoTIFF is stored and reused.
"""

from __future__ import annotations

import io
import json
import math
import threading
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from .catalog import OVERLAY_DIR, fmt_area
from .gee_init import require_ee
from .inspect import _axis_feature, _pixel_class, _pixel_rc, _ranked_patches, _zone
from .watermask import (
    DEPOSITION_RGBA,
    EROSION_RGBA,
    RIVER_RGBA,
    change_masks,
    pack_mask,
    unpack_mask,
    write_mask_png,
)

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / "data" / "live"
WINDOW_DAYS = 15
SCALE_M = 100
PIXEL_DEG = 100 / 111_320.0
PROJECT = "community-hero-5c501"
ROI = (89.5, 25.5, 96.0, 28.5)
NDWI_THRESHOLD = 0.0
CLOUD_PERCENT = 90
VV_DB = -16.0
_LOCK = threading.Lock()
_INFLIGHT: dict[str, threading.Event] = {}
_FAILED: dict[str, BaseException] = {}
_PROGRESS: dict[str, object] = {
    "running": False,
    "step": "",
    "detail": "",
    "done": False,
    "error": None,
    "change": None,
    "points": None,
}


def _set_progress(**fields: object) -> None:
    with _LOCK:
        _PROGRESS.update(fields)


def progress_snapshot() -> dict:
    with _LOCK:
        return dict(_PROGRESS)


def parse_day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Use a date as YYYY-MM-DD") from exc


def window_ending(day: date) -> tuple[date, date]:
    """Inclusive start and exclusive end, 15 days long, ending on day."""
    start = day - timedelta(days=WINDOW_DAYS - 1)
    return start, day + timedelta(days=1)


def resolve_windows(end_text: str, start_text: str | None) -> tuple[tuple[date, date], tuple[date, date]]:
    end_day = parse_day(end_text)
    later = window_ending(end_day)
    if start_text:
        start_day = parse_day(start_text)
        if start_day >= end_day:
            raise ValueError("Start date has to be before the end date")
        earlier = window_ending(start_day)
    else:
        earlier = window_ending(end_day - timedelta(days=WINDOW_DAYS))
    return earlier, later


def _key(start: date, end_exclusive: date) -> str:
    last = end_exclusive - timedelta(days=1)
    return f"{start.isoformat()}_{last.isoformat()}"


def _label(start: date, end_exclusive: date) -> str:
    return (end_exclusive - timedelta(days=1)).isoformat()


def _cache_path(start: date, end_exclusive: date, sensor: str) -> Path:
    return LIVE_DIR / f"gee4-{sensor}_{_key(start, end_exclusive)}.npz"


def _overlay_name(start: date, end_exclusive: date, kind: str, sensor: str = "optical") -> str:
    return f"{sensor}-{_key(start, end_exclusive)}-{kind}.png"


def _base_grid() -> tuple[rasterio.Affine, int, int, dict]:
    west, south, east, north = ROI
    width = int(round((east - west) / PIXEL_DEG))
    height = int(round((north - south) / PIXEL_DEG))
    transform = from_origin(west, north, PIXEL_DEG, PIXEL_DEG)
    mid = math.radians((south + north) / 2.0)
    metres_x = PIXEL_DEG * 111_320.0 * math.cos(mid)
    metres_y = PIXEL_DEG * 110_540.0
    grid = {
        "bounds": {"west": west, "south": south, "east": east, "north": north},
        "width": width,
        "height": height,
        "pixel_km2": (metres_x * metres_y) / 1_000_000.0,
    }
    return transform, width, height, grid


def _river_belt(height: int, width: int, transform, metres: float = 20_000) -> np.ndarray:
    from rasterio.features import rasterize

    from .crs import load_crs, to_lonlat, to_metres
    from .guide import load_guide_lonlat

    bundle = load_crs()
    belt = to_lonlat(to_metres(load_guide_lonlat(), bundle).buffer(metres), bundle)
    painted = rasterize([(belt, 1)], out_shape=(height, width), transform=transform, fill=0, dtype="uint8")
    return painted.astype(bool)


def _rectangle(ee):
    west, south, east, north = ROI
    return ee.Geometry.Rectangle([west, south, east, north])


def _mask_clouds(image):
    scl = image.select("SCL")
    clear = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
    return image.updateMask(clear)


def _collection(ee, sensor: str, start: date, end_exclusive: date):
    region = _rectangle(ee)
    if sensor == "microwave":
        collection = (
            ee.ImageCollection("COPERNICUS/S1_GRD")
            .filterBounds(region)
            .filterDate(start.isoformat(), end_exclusive.isoformat())
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        )
        return collection, region
    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(region)
        .filterDate(start.isoformat(), end_exclusive.isoformat())
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", CLOUD_PERCENT))
        .map(_mask_clouds)
    )
    return collection, region


def _export_image(ee, sensor: str, collection, region):
    if sensor == "microwave":
        signal = collection.select("VV").median().clip(region)
        water = signal.lt(VV_DB).unmask(0).toByte().rename("water")
        method = "VV < -16 dB"
    else:
        signal = collection.median().clip(region).normalizedDifference(["B3", "B8"]).rename("NDWI")
        water = signal.gt(NDWI_THRESHOLD).unmask(0).toByte().rename("water")
        method = "NDWI B3 B8 > 0"
    valid = signal.mask().unmask(0).toByte().rename("valid")
    image = water.addBands(valid)
    stamp = ee.Date(collection.aggregate_max("system:time_start")).format("yyyy-MM-dd HH:mm")
    return image, method, stamp


def _tiff_bytes(blob: bytes) -> bytes:
    if blob[:2] != b"PK":
        return blob
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith((".tif", ".tiff"))]
        if not names:
            raise RuntimeError("Earth Engine returned no GeoTIFF")
        if len(names) == 1:
            return archive.read(names[0])
        arrays = []
        transform = None
        crs = None
        for name in sorted(names):
            with MemoryFile(archive.read(name)) as memory, memory.open() as source:
                arrays.append(source.read(1))
                transform = source.transform
                crs = source.crs
        stacked = np.stack(arrays, axis=0)
        buffer = io.BytesIO()
        with rasterio.open(
            buffer,
            "w",
            driver="GTiff",
            height=stacked.shape[1],
            width=stacked.shape[2],
            count=stacked.shape[0],
            dtype=stacked.dtype,
            crs=crs,
            transform=transform,
        ) as dataset:
            dataset.write(stacked)
        return buffer.getvalue()


def _on_grid(blob: bytes) -> tuple[np.ndarray, np.ndarray, dict]:
    transform, _width, _height, grid = _base_grid()
    water = np.zeros((_height, _width), dtype=np.uint8)
    observed = np.zeros((_height, _width), dtype=np.uint8)
    with MemoryFile(_tiff_bytes(blob)) as memory, memory.open() as source:
        raw_water = source.read(1)
        raw_valid = source.read(2) if source.count > 1 else np.ones(raw_water.shape, dtype=np.uint8)
        reproject(
            source=raw_water,
            destination=water,
            src_transform=source.transform,
            src_crs=source.crs,
            dst_transform=transform,
            dst_crs="EPSG:4326",
            resampling=Resampling.nearest,
        )
        reproject(
            source=raw_valid,
            destination=observed,
            src_transform=source.transform,
            src_crs=source.crs,
            dst_transform=transform,
            dst_crs="EPSG:4326",
            resampling=Resampling.nearest,
        )
    return water.astype(bool), observed.astype(bool), grid


def _tiles() -> list[tuple[float, float, float, float]]:
    west, south, east, north = ROI
    columns, rows = 3, 2
    width = (east - west) / columns
    height = (north - south) / rows
    boxes = []
    for row in range(rows):
        for col in range(columns):
            boxes.append(
                (
                    west + col * width,
                    south + row * height,
                    west + (col + 1) * width,
                    south + (row + 1) * height,
                )
            )
    return boxes


def _download(ee, image, box: tuple[float, float, float, float]) -> bytes:
    import urllib.error
    import urllib.request

    region = ee.Geometry.Rectangle(list(box))
    url = image.clip(region).getDownloadURL(
        {
            "scale": SCALE_M,
            "crs": "EPSG:4326",
            "region": region,
            "format": "GEO_TIFF",
            "maxPixels": 1e9,
        }
    )
    try:
        with urllib.request.urlopen(url, timeout=600) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(detail or "Earth Engine tile download failed") from exc


def _clip_microwave(sar: np.ndarray, optical: np.ndarray, pixel_km2: float) -> np.ndarray:
    from scipy import ndimage as ndi

    pixel_m = math.sqrt(pixel_km2 * 1_000_000.0)
    near = ndi.distance_transform_edt(~optical) <= (800.0 / pixel_m)
    return sar & near


def _river_core(water: np.ndarray, pixel_km2: float, height: int, width: int, transform) -> np.ndarray:
    """Main channel and nearby braids, plus a disconnected upstream reach inside the corridor."""
    from scipy import ndimage as ndi

    if not water.any():
        return water
    labels, count = ndi.label(water)
    if count == 0:
        return water
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    main = labels == int(sizes.argmax())
    pixel_m = math.sqrt(pixel_km2 * 1_000_000.0)
    near = ndi.distance_transform_edt(~main) <= (2_000.0 / pixel_m)
    belt = _river_belt(height, width, transform, 12_000)
    big = sizes >= max(1, int(round(5.0 / pixel_km2)))
    big[0] = False
    return (water & near) | (big[labels] & water & belt)


def _fetch(sensor: str, start: date, end_exclusive: date) -> tuple[np.ndarray, np.ndarray, dict, dict]:
    ee = require_ee()
    collection, _region = _collection(ee, sensor, start, end_exclusive)
    scene_count = int(collection.size().getInfo())
    last = end_exclusive - timedelta(days=1)
    if scene_count == 0:
        raise RuntimeError(f"No {sensor} scenes from {start.isoformat()} to {last.isoformat()}")
    when = str(ee.Date(collection.aggregate_max("system:time_start")).format("yyyy-MM-dd HH:mm").getInfo())
    transform, width, height, grid = _base_grid()
    water = np.zeros((height, width), dtype=bool)
    observed = np.zeros((height, width), dtype=bool)
    method = "VV < -16 dB" if sensor == "microwave" else "NDWI B3 B8 > 0"
    tiles = _tiles()
    for index, box in enumerate(tiles, start=1):
        tile_region = ee.Geometry.Rectangle(list(box))
        tile_collection = collection.filterBounds(tile_region)
        if int(tile_collection.size().getInfo()) == 0:
            print(f"  {sensor} tile {index} empty", flush=True)
            continue
        _set_progress(detail=f"Downloading tile {index} of {len(tiles)}")
        image, method, _stamp = _export_image(ee, sensor, tile_collection, tile_region)
        blob = _download(ee, image, box)
        tile_water, tile_observed, _grid = _on_grid(blob)
        water |= tile_water
        observed |= tile_observed
        _set_progress(detail=f"Cleaned tile {index} of {len(tiles)}")
        print(f"  {sensor} tile {index}/{len(tiles)} {start.isoformat()}", flush=True)
    _set_progress(detail="Cleaning the river mask")
    if sensor == "optical":
        water = _river_core(water, grid["pixel_km2"], height, width, transform)
    else:
        min_pixels = max(1, int(round(0.5 / grid["pixel_km2"])))
        if water.any():
            from skimage.morphology import remove_small_objects

            water = remove_small_objects(water, min_size=min_pixels)
    scale = SCALE_M
    meta = {
        "start": start.isoformat(),
        "end": last.isoformat(),
        "label": _label(start, end_exclusive),
        "sensor": sensor,
        "scene_count": scene_count,
        "latest_scene": f"{when} UTC" if when else None,
        "scale_m": scale,
        "project": PROJECT,
        "method": method,
        "cleaned": True,
        "water_km2": round(float(water.sum()) * grid["pixel_km2"], 2),
        "bounds": grid["bounds"],
        "source": "Google Earth Engine",
    }
    return water, observed, grid, meta


def latest_report() -> dict:
    end = date.today().isoformat()
    return {
        "optical": {"date": end, "when": None},
        "microwave": {"date": end, "when": None},
        "end": end,
        "source": "Google Earth Engine",
    }


def _cached(start: date, end_exclusive: date, sensor: str) -> dict | None:
    path = _cache_path(start, end_exclusive, sensor)
    meta_path = path.with_suffix(".json")
    if not path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    water, observed, grid = _load(path)
    png = OVERLAY_DIR / _overlay_name(start, end_exclusive, "river", sensor)
    if not png.exists():
        color = (124, 58, 237, 185) if sensor == "microwave" else RIVER_RGBA
        write_mask_png(water, color, png)
    return {"water": water, "observed": observed, "grid": grid, "meta": meta}


def extract_window(start: date, end_exclusive: date, sensor: str = "optical", stage: str = "") -> dict:
    if stage:
        _set_progress(step=stage, detail="Checking the saved GeoTIFF")
    ready = _cached(start, end_exclusive, sensor)
    if ready is not None:
        return ready
    key = f"{sensor}_{_key(start, end_exclusive)}"
    with _LOCK:
        ready = _cached(start, end_exclusive, sensor)
        if ready is not None:
            return ready
        event = _INFLIGHT.get(key)
        if event is None:
            event = threading.Event()
            _INFLIGHT[key] = event
            _FAILED.pop(key, None)
            owner = True
        else:
            owner = False
    if not owner:
        event.wait(timeout=1200)
        ready = _cached(start, end_exclusive, sensor)
        if ready is not None:
            return ready
        failure = _FAILED.get(key)
        if failure is not None:
            raise failure
        raise RuntimeError(f"The extract for {key} did not finish")

    path = _cache_path(start, end_exclusive, sensor)
    meta_path = path.with_suffix(".json")
    try:
        water, observed, grid, meta = _fetch(sensor, start, end_exclusive)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            water=pack_mask(water),
            observed=pack_mask(observed),
            shape=np.array(water.shape, dtype=np.int32),
            pixel_km2=np.array([grid["pixel_km2"]], dtype=np.float64),
            bounds=np.array([grid["bounds"]["west"], grid["bounds"]["south"], grid["bounds"]["east"], grid["bounds"]["north"]]),
        )
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        png = OVERLAY_DIR / _overlay_name(start, end_exclusive, "river", sensor)
        color = (124, 58, 237, 185) if sensor == "microwave" else RIVER_RGBA
        write_mask_png(water, color, png)
        _write_tif(path.with_suffix(".tif"), water, observed, grid)
        return {"water": water, "observed": observed, "grid": grid, "meta": meta}
    except Exception as exc:
        _FAILED[key] = exc
        raise
    finally:
        with _LOCK:
            _INFLIGHT.pop(key, None)
        event.set()


def _load(path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    with np.load(path) as data:
        shape = (int(data["shape"][0]), int(data["shape"][1]))
        water = unpack_mask(data["water"], shape)
        observed = unpack_mask(data["observed"], shape)
        west, south, east, north = [float(v) for v in data["bounds"]]
        grid = {
            "bounds": {"west": west, "south": south, "east": east, "north": north},
            "width": shape[1],
            "height": shape[0],
            "pixel_km2": float(data["pixel_km2"][0]),
        }
    return water, observed, grid


def _write_tif(path: Path, water: np.ndarray, observed: np.ndarray, grid: dict) -> None:
    bounds = grid["bounds"]
    height, width = water.shape
    transform = rasterio.transform.from_bounds(bounds["west"], bounds["south"], bounds["east"], bounds["north"], width, height)
    band = np.where(water, 1, np.where(observed, 0, 255)).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
        nodata=255,
        compress="lzw",
    ) as dst:
        dst.write(band, 1)


def compare_dates(end_text: str, start_text: str | None) -> dict:
    earlier_window, later_window = resolve_windows(end_text, start_text or None)
    earlier = extract_window(*earlier_window, "optical", "Base optical")
    later = extract_window(*later_window, "optical", "Current optical")
    microwave = extract_window(*later_window, "microwave", "Microwave")
    _set_progress(step="Difference", detail="Erosion is new water. Deposition is water that left.")
    grid = later["grid"]
    microwave_water = _clip_microwave(microwave["water"], later["water"], grid["pixel_km2"])
    write_mask_png(microwave_water, (124, 58, 237, 185), OVERLAY_DIR / _overlay_name(*later_window, "river", "microwave"))
    min_pixels = max(1, int(round(0.01 / grid["pixel_km2"])))
    erosion, deposition, persistent = change_masks(
        earlier["water"],
        later["water"],
        earlier["observed"],
        later["observed"],
        min_pixels,
    )
    pixel_km2 = grid["pixel_km2"]
    erosion_km2 = round(float(erosion.sum()) * pixel_km2, 2)
    deposition_km2 = round(float(deposition.sum()) * pixel_km2, 2)
    persistent_km2 = round(float(persistent.sum()) * pixel_km2, 2)
    net = round(erosion_km2 - deposition_km2, 2)
    later_id = parse_day(end_text).isoformat()
    earlier_id = parse_day(start_text).isoformat() if start_text else ""
    pair = f"{_key(*later_window)}__{_key(*earlier_window)}"
    erosion_name = f"{pair}-erosion.png"
    deposition_name = f"{pair}-deposition.png"
    write_mask_png(erosion, EROSION_RGBA, OVERLAY_DIR / erosion_name)
    write_mask_png(deposition, DEPOSITION_RGBA, OVERLAY_DIR / deposition_name)
    axis = _axis_feature(later["water"], grid, later_id)
    note = ""
    return {
        "available": True,
        "earlier_id": earlier_id,
        "later_id": later_id,
        "earlier_label": earlier["meta"]["label"],
        "later_label": later["meta"]["label"],
        "earlier_short": earlier["meta"]["label"],
        "later_short": later["meta"]["label"],
        "erosion_km2": erosion_km2,
        "deposition_km2": deposition_km2,
        "persistent_km2": persistent_km2,
        "erosion_display": fmt_area(erosion_km2),
        "deposition_display": fmt_area(deposition_km2),
        "persistent_display": fmt_area(persistent_km2),
        "net_water_change_km2": net,
        "net_water_change_display": f"{net:+.0f} km²" if abs(net) >= 100 else f"{net:+.1f} km²",
        "earlier_water_km2": earlier["meta"]["water_km2"],
        "later_water_km2": later["meta"]["water_km2"],
        "later_water_display": fmt_area(later["meta"]["water_km2"]),
        "microwave_water_km2": round(float(microwave_water.sum()) * pixel_km2, 2),
        "microwave_water_display": fmt_area(round(float(microwave_water.sum()) * pixel_km2, 2)),
        "microwave_png": f"/api/overlays/{_overlay_name(*later_window, 'river', 'microwave')}",
        "optical_scene": later["meta"].get("latest_scene"),
        "microwave_scene": microwave["meta"].get("latest_scene"),
        "unit": "km²",
        "validation_status": "ready",
        "disclaimer": "",
        "erosion_png": f"/api/overlays/{erosion_name}",
        "deposition_png": f"/api/overlays/{deposition_name}",
        "river_png": f"/api/overlays/{_overlay_name(*later_window, 'river')}",
        "bounds": grid["bounds"],
        "note": note,
        "rows": [],
        "centerline": axis if axis.get("geometry") else None,
        "scene_count": later["meta"]["scene_count"],
        "scale_m": SCALE_M,
        "source": "Google Earth Engine",
    }


def period_points(end_text: str, start_text: str | None) -> dict:
    earlier_window, later_window = resolve_windows(end_text, start_text or None)
    earlier = extract_window(*earlier_window, "optical")
    later = extract_window(*later_window, "optical")
    grid = later["grid"]
    min_pixels = max(1, int(round(0.01 / grid["pixel_km2"])))
    erosion, deposition, _persistent = change_masks(
        earlier["water"],
        later["water"],
        earlier["observed"],
        later["observed"],
        min_pixels,
    )
    erosion_rows, erosion_count = _ranked_patches(erosion, grid)
    deposition_rows, deposition_count = _ranked_patches(deposition, grid)
    return {
        "later_id": parse_day(end_text).isoformat(),
        "earlier_id": parse_day(start_text).isoformat() if start_text else "",
        "erosion": erosion_rows,
        "deposition": deposition_rows,
        "erosion_count": erosion_count,
        "deposition_count": deposition_count,
        "shown": len(erosion_rows),
    }


def period_identify(lon: float, lat: float, end_text: str, start_text: str | None) -> dict:
    earlier_window, later_window = resolve_windows(end_text, start_text or None)
    earlier = extract_window(*earlier_window, "optical")
    later = extract_window(*later_window, "optical")
    grid = later["grid"]
    earlier_label = earlier["meta"]["label"]
    later_label = later["meta"]["label"]
    row_f, col_f = _pixel_rc(lon, lat, grid)
    row, col = int(np.floor(row_f)), int(np.floor(col_f))
    name = _pixel_class(row, col, earlier["water"], earlier["observed"], later["water"], later["observed"])
    labels = {
        "corridor_expansion": "Erosion",
        "corridor_contraction": "Deposition",
        "persistent_water": "Water in both periods",
        "land": "Land in both periods",
        "nodata": "No clear Sentinel-2 observation",
        "outside": "Outside the extract",
    }
    zone = None
    if name == "corridor_expansion":
        min_pixels = max(1, int(round(0.01 / grid["pixel_km2"])))
        erosion, _deposition, _persistent = change_masks(
            earlier["water"], later["water"], earlier["observed"], later["observed"], min_pixels,
        )
        if 0 <= row < erosion.shape[0] and 0 <= col < erosion.shape[1] and erosion[row, col]:
            zone = _zone(erosion, row, col, grid, name, earlier_label, later_label)
    elif name == "corridor_contraction":
        min_pixels = max(1, int(round(0.01 / grid["pixel_km2"])))
        _erosion, deposition, _persistent = change_masks(
            earlier["water"], later["water"], earlier["observed"], later["observed"], min_pixels,
        )
        if 0 <= row < deposition.shape[0] and 0 <= col < deposition.shape[1] and deposition[row, col]:
            zone = _zone(deposition, row, col, grid, name, earlier_label, later_label)
    return {
        "longitude": lon,
        "latitude": lat,
        "inside": name != "outside",
        "pixel_class": name,
        "pixel_label": labels.get(name, name),
        "zone": zone,
        "section": None,
        "distance_m": None,
    }


def list_periods() -> list[dict]:
    if not LIVE_DIR.exists():
        return []
    rows = []
    for path in sorted(LIVE_DIR.glob("gee4-*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        key = path.stem
        tif = LIVE_DIR / f"{key}.tif"
        rows.append(
            {
                "id": key,
                "label": meta.get("label"),
                "water_display": fmt_area(meta.get("water_km2")),
                "scene_count": meta.get("scene_count"),
                "scale_m": meta.get("scale_m"),
                "file": f"/api/periods/{key}/file" if tif.is_file() else None,
                "png": f"/api/overlays/{meta.get('sensor', 'optical')}-{key.split('_', 1)[-1]}-river.png" if "_" in key else None,
            }
        )
    return rows


def period_tif(key: str) -> Path:
    import re

    if not re.fullmatch(r"[a-z0-9_-]+", key):
        raise KeyError(key)
    path = LIVE_DIR / f"{key}.tif"
    if not path.is_file():
        raise FileNotFoundError(key)
    return path


def roi_bounds() -> dict:
    west, south, east, north = ROI
    return {"west": west, "south": south, "east": east, "north": north}


def _run_compute(later: str, earlier: str | None) -> None:
    try:
        change = compare_dates(later, earlier)
        _set_progress(step="Points", detail="Ranking erosion and deposition")
        points = period_points(later, earlier)
        _set_progress(running=False, done=True, error=None, change=change, points=points, step="Done", detail="Ready")
    except Exception as exc:  # noqa: BLE001
        _set_progress(running=False, done=True, error=str(exc), step="Done", detail="")


def begin_compute(later: str, earlier: str | None) -> bool:
    with _LOCK:
        if bool(_PROGRESS.get("running")):
            return False
        _PROGRESS.update(
            {
                "running": True,
                "done": False,
                "error": None,
                "change": None,
                "points": None,
                "step": "Base optical",
                "detail": "Starting",
            }
        )
    threading.Thread(target=_run_compute, args=(later, earlier), daemon=True).start()
    return True
