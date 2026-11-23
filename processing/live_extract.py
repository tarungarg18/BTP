"""15-day water masks from Google Earth Engine for two-date bankline comparison.

Optical water is Sentinel-2 MNDWI (B3 - B11) / (B3 + B11) > 0 after the SCL cloud mask.
Microwave water is Sentinel-1 VV darker than a corridor-validated threshold (−16 dB).
Each chosen date is the last day of a 15-day composite (not a single acquisition).
An empty start date uses the 15 days before that window. GeoTIFFs are cached on disk.

Outer banklines and corridor expansion/contraction come from processing.bankline_compare.
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
from rasterio.transform import Affine, from_origin
from rasterio.warp import Resampling, reproject

from .catalog import OVERLAY_DIR, fmt_area
from .crs import ANALYSIS_CRS, ANALYSIS_CRS_WKT, GRID_PAD_M, load_crs
from .gee_init import require_ee
from .inspect import _pixel_rc, _zone
from .watermask import (
    DEPOSITION_RGBA,
    EROSION_RGBA,
    RIVER_RGBA,
    pack_mask,
    unpack_mask,
    write_mask_png,
)

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / "data" / "live"
WINDOW_DAYS = 15  # default Mode A composite length; overridable via CompareRequest
SCALE_M = 100
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


_JOB = threading.local()
_TICKET = 0
_NEXT: tuple[str, str | None, int] | None = None
_WORKER_ON = False


def _set_progress(**fields: object) -> None:
    ticket = getattr(_JOB, "ticket", None)
    with _LOCK:
        current = _PROGRESS.get("ticket")
        if ticket is not None and current not in (None, ticket):
            return
        _PROGRESS.update(fields)


def progress_snapshot() -> dict:
    with _LOCK:
        return dict(_PROGRESS)


def parse_day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Use a date as YYYY-MM-DD") from exc


def window_ending(day: date, window_days: int = WINDOW_DAYS) -> tuple[date, date]:
    """Inclusive start and exclusive end, window_days long, ending on day."""
    start = day - timedelta(days=window_days - 1)
    return start, day + timedelta(days=1)


def resolve_windows(
    end_text: str,
    start_text: str | None,
    window_days: int = WINDOW_DAYS,
) -> tuple[tuple[date, date], tuple[date, date]]:
    """Legacy helper: Mode A two-date windows. Prefer build_compare_request()."""
    from .date_options import build_compare_request

    req = build_compare_request(
        mode="dates",
        later=end_text,
        earlier=start_text,
        window_days=window_days,
    )
    return (
        (req.earlier.start, req.earlier.end_exclusive),
        (req.later.start, req.later.end_exclusive),
    )


def _key(start: date, end_exclusive: date) -> str:
    last = end_exclusive - timedelta(days=1)
    return f"{start.isoformat()}_{last.isoformat()}"


def _label(start: date, end_exclusive: date) -> str:
    last = end_exclusive - timedelta(days=1)
    if start == last:
        return last.isoformat()
    return f"{start.isoformat()} → {last.isoformat()}"


def _cache_path(start: date, end_exclusive: date, sensor: str) -> Path:
    return LIVE_DIR / f"gee7-{sensor}_{_key(start, end_exclusive)}.npz"


def _overlay_name(start: date, end_exclusive: date, kind: str, sensor: str = "optical") -> str:
    return f"{sensor}-{_key(start, end_exclusive)}-{kind}.png"


def _grid_affine(grid: dict) -> Affine:
    return Affine(*grid["transform"])


def _base_grid() -> tuple[rasterio.Affine, int, int, dict]:
    """Fixed 100 m Assam Albers grid over the Brahmaputra ROI."""
    west, south, east, north = ROI
    bundle = load_crs()
    corner_lons = (west, west, east, east)
    corner_lats = (south, north, south, north)
    xs, ys = bundle.to_metre.transform(corner_lons, corner_lats)
    x_min = min(xs) - GRID_PAD_M
    x_max = max(xs) + GRID_PAD_M
    y_min = min(ys) - GRID_PAD_M
    y_max = max(ys) + GRID_PAD_M
    width = int(math.ceil((x_max - x_min) / SCALE_M))
    height = int(math.ceil((y_max - y_min) / SCALE_M))
    transform = from_origin(x_min, y_max, SCALE_M, SCALE_M)
    pixel_m2 = SCALE_M * SCALE_M
    grid = {
        "bounds": {"west": west, "south": south, "east": east, "north": north},
        "bounds_m": {
            "x_min": x_min,
            "y_min": y_min,
            "x_max": x_max,
            "y_max": y_max,
        },
        "width": width,
        "height": height,
        "pixel_m": SCALE_M,
        "pixel_km2": pixel_m2 / 1_000_000.0,
        "crs": ANALYSIS_CRS,
        "transform": [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f],
    }
    return transform, width, height, grid


def _river_belt(height: int, width: int, transform, metres: float = 20_000) -> np.ndarray:
    from rasterio.features import rasterize

    from .crs import load_crs, to_metres
    from .guide import load_guide_lonlat

    bundle = load_crs()
    belt = to_metres(load_guide_lonlat(), bundle).buffer(metres)
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
            .select(["VV"])
        )
        return collection, region
    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(region)
        .filterDate(start.isoformat(), end_exclusive.isoformat())
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", CLOUD_PERCENT))
        .select(["B3", "B8", "B11", "SCL"])
    )
    return collection, region


def _export_image(ee, sensor: str, collection, region):
    """Median at 100 m inside this tile. Full-resolution medians exhaust Earth Engine memory."""

    def at_scale(image):
        return image.clip(region).reproject(crs="EPSG:4326", scale=SCALE_M)

    if sensor == "microwave":
        signal = collection.map(lambda image: at_scale(image.select("VV"))).median()
        # Corridor-validated VV water threshold for Assam (calibrated GRD, dB).
        water = signal.lt(VV_DB).unmask(0).toByte().rename("water")
        method = f"VV < {VV_DB} dB (Assam corridor validated)"
    else:
        def prepare(image):
            return at_scale(_mask_clouds(image).select(["B3", "B8", "B11"]))

        # MNDWI is more stable than NDWI for turbid Brahmaputra water.
        signal = collection.map(prepare).median().normalizedDifference(["B3", "B11"]).rename("MNDWI")
        water = signal.gt(NDWI_THRESHOLD).unmask(0).toByte().rename("water")
        method = "MNDWI B3 B11 > 0"
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
            dst_crs=ANALYSIS_CRS_WKT,
            resampling=Resampling.nearest,
        )
        reproject(
            source=raw_valid,
            destination=observed,
            src_transform=source.transform,
            src_crs=source.crs,
            dst_transform=transform,
            dst_crs=ANALYSIS_CRS_WKT,
            resampling=Resampling.nearest,
        )
    return water.astype(bool), observed.astype(bool), grid


def _tiles() -> list[tuple[float, float, float, float]]:
    west, south, east, north = ROI
    columns, rows = 4, 3
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
        if "memory" in detail.lower() or "503" in detail:
            raise RuntimeError("Earth Engine ran out of memory on this tile") from exc
        raise RuntimeError(detail or "Earth Engine tile download failed") from exc


def _memory_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "memory" in text or "503" in text or "unavailable" in text


def _quarters(box: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    west, south, east, north = box
    mid_x = (west + east) / 2.0
    mid_y = (south + north) / 2.0
    return [
        (west, south, mid_x, mid_y),
        (mid_x, south, east, mid_y),
        (west, mid_y, mid_x, north),
        (mid_x, mid_y, east, north),
    ]


def _read_box(ee, sensor: str, collection, box: tuple[float, float, float, float], depth: int = 0) -> list[bytes]:
    region = ee.Geometry.Rectangle(list(box), "EPSG:4326", False)
    tile_collection = collection.filterBounds(region)
    if int(tile_collection.size().getInfo()) == 0:
        return []
    image, _method, _stamp = _export_image(ee, sensor, tile_collection, region)
    try:
        return [_download(ee, image, box)]
    except RuntimeError as exc:
        if depth >= 2 or not _memory_error(exc):
            if _memory_error(exc):
                raise RuntimeError("Earth Engine ran out of memory on this date. Press Compute again.") from exc
            raise
        print(f"  {sensor} tile too large, splitting", flush=True)
        blobs: list[bytes] = []
        for part in _quarters(box):
            blobs.extend(_read_box(ee, sensor, collection, part, depth + 1))
        return blobs


AXIS_STEP_M = 500.0
AXIS_REACH_M = 20_000.0
AXIS_SAMPLE_M = 100.0
AXIS_SHIFT = 6
BELT_HALF_M = 9_000.0


def _forward_points(points: np.ndarray, min_step: float) -> np.ndarray:
    """Drop vertices that fold the line back on itself."""
    if len(points) < 3:
        return points
    kept: list[np.ndarray] = [np.asarray(points[0], dtype=np.float64)]
    for point in points[1:]:
        current = np.asarray(point, dtype=np.float64)
        step = math.hypot(float(current[0] - kept[-1][0]), float(current[1] - kept[-1][1]))
        if step < min_step:
            continue
        if len(kept) >= 2:
            ax = float(kept[-1][0] - kept[-2][0])
            ay = float(kept[-1][1] - kept[-2][1])
            bx = float(current[0] - kept[-1][0])
            by = float(current[1] - kept[-1][1])
            na = math.hypot(ax, ay)
            nb = math.hypot(bx, by)
            if na > 0 and nb > 0 and (ax * bx + ay * by) / (na * nb) < 0:
                continue
        kept.append(current)
    end = np.asarray(points[-1], dtype=np.float64)
    if math.hypot(float(end[0] - kept[-1][0]), float(end[1] - kept[-1][1])) > 1:
        kept.append(end)
    return np.vstack(kept)


def _river_axis(score: np.ndarray, grid: dict):
    """One continuous Sadiya-to-Dhubri line through the strongest water.

    Transects are cast every 500 m across the guide line. Each transect is scored by
    the water density along it, and a dynamic-programming path picks one offset per
    transect so the line follows the water without jumping more than 800 m between
    neighbouring transects. Stretches with no detected water keep a straight course.
    """
    from scipy import ndimage as ndi
    from shapely.geometry import LineString

    from .crs import load_crs
    from .guide import load_guide_lonlat

    bundle = load_crs()
    guide = np.asarray(load_guide_lonlat().coords)
    gx, gy = bundle.to_metre.transform(guide[:, 0], guide[:, 1])
    guide_m = LineString(_forward_points(np.column_stack([gx, gy]), 800.0))
    stations = np.arange(0.0, guide_m.length, AXIS_STEP_M)
    offsets = np.arange(-AXIS_REACH_M, AXIS_REACH_M + 1.0, AXIS_SAMPLE_M)
    centre = np.array([guide_m.interpolate(d).coords[0] for d in stations])
    ahead = np.array([guide_m.interpolate(min(d + 250.0, guide_m.length)).coords[0] for d in stations])
    behind = np.array([guide_m.interpolate(max(d - 250.0, 0.0)).coords[0] for d in stations])
    tangent = ahead - behind
    tangent /= np.maximum(np.hypot(tangent[:, 0], tangent[:, 1]), 1e-9)[:, None]
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)

    xs = centre[:, 0][:, None] + normal[:, 0][:, None] * offsets[None, :]
    ys = centre[:, 1][:, None] + normal[:, 1][:, None] * offsets[None, :]
    from rasterio.transform import rowcol

    transform = _grid_affine(grid)
    cols, rows = rowcol(transform, xs.ravel(), ys.ravel())
    cols = np.floor(cols).astype(int)
    rows = np.floor(rows).astype(int)
    inside = (rows >= 0) & (rows < grid["height"]) & (cols >= 0) & (cols < grid["width"])
    values = np.zeros(rows.size, dtype=np.float32)
    values[inside] = score[rows[inside], cols[inside]]
    density = ndi.uniform_filter1d(values.reshape(xs.shape), size=11, axis=1, mode="constant")
    prior = 0.15 * np.abs(offsets) / AXIS_REACH_M
    gain = density - prior[None, :]

    count, width = gain.shape
    total = gain[0].copy()
    back = np.zeros((count, width), dtype=np.int16)
    shifts = np.arange(-AXIS_SHIFT, AXIS_SHIFT + 1)
    for index in range(1, count):
        candidates = np.full((shifts.size, width), -np.inf, dtype=np.float64)
        for slot, shift in enumerate(shifts):
            moved = np.full(width, -np.inf)
            if shift >= 0:
                moved[shift:] = total[: width - shift] if shift else total
            else:
                moved[:shift] = total[-shift:]
            candidates[slot] = moved - 0.01 * abs(int(shift))
        best = np.argmax(candidates, axis=0)
        total = candidates[best, np.arange(width)] + gain[index]
        back[index] = shifts[best]
    path = np.zeros(count, dtype=int)
    path[-1] = int(np.argmax(total))
    for index in range(count - 1, 0, -1):
        path[index - 1] = path[index] - int(back[index, path[index]])
    score_grid = values.reshape(xs.shape)
    deepest = np.argmax(score_grid, axis=1)
    has_water = score_grid.max(axis=1) > 0
    chosen = np.where(has_water, deepest, -1).astype(np.int32)
    # Prefer the DP pick when it already sits on water (smoother course).
    dp = np.clip(path, 0, width - 1)
    use_dp = has_water & (score_grid[np.arange(count), dp] > 0)
    chosen = np.where(use_dp, dp, chosen)
    # Dry transect: borrow the nearest wet station's offset, then snap onto this transect if possible.
    known = np.flatnonzero(chosen >= 0)
    if known.size < 3:
        raise RuntimeError("The centreline could not stay on the river for this date pair.")
    for index in range(count):
        if chosen[index] >= 0:
            continue
        left = known[known < index]
        right = known[known > index]
        guess = int(chosen[left[-1]]) if left.size else int(chosen[right[0]])
        if has_water[index]:
            wet = np.flatnonzero(score_grid[index] > 0)
            chosen[index] = int(wet[np.argmin(np.abs(wet - guess))])
        else:
            chosen[index] = -1
    wet_stations = np.flatnonzero(chosen >= 0)
    offset = offsets[chosen[wet_stations]].astype(np.float64)
    offset = ndi.median_filter(offset, size=7, mode="nearest")
    offset = ndi.uniform_filter1d(offset, size=5, mode="nearest")

    def _snap_pick(station: int, prefer_i: int) -> int | None:
        wet = np.flatnonzero(score_grid[station] > 0)
        if wet.size == 0:
            return None
        # Never leap more than ~1.8 km sideways — that is what drew forest spikes.
        near = wet[np.abs(wet - prefer_i) <= AXIS_SHIFT * 3]
        if not near.size:
            return None
        return int(near[np.argmax(score_grid[station, near])])

    prev_pick: int | None = None
    gap = 0
    for slot, station in enumerate(wet_stations):
        pick = int(np.clip(round((offset[slot] - offsets[0]) / AXIS_SAMPLE_M), 0, width - 1))
        if prev_pick is None or gap > 8:
            prefer = pick
            gap = 0
        else:
            prefer = prev_pick
        snapped = _snap_pick(int(station), prefer)
        if snapped is None:
            offset[slot] = np.nan
            gap += 1
            continue
        offset[slot] = offsets[snapped]
        prev_pick = snapped
        gap = 0

    wet_list = [int(s) for s in wet_stations.tolist()]
    last_pick: int | None = None
    runs: list[tuple[list[float], list[float]]] = []
    run_x: list[float] = []
    run_y: list[float] = []
    for slot, station in enumerate(wet_list):
        if not np.isfinite(offset[slot]):
            continue
        if last_pick is not None and run_x and slot > 0:
            prev_station = wet_list[slot - 1]
            for mid in range(prev_station + 1, station):
                if not has_water[mid]:
                    continue
                mid_pick = _snap_pick(mid, last_pick)
                if mid_pick is None:
                    continue
                mx = float(centre[mid, 0] + normal[mid, 0] * offsets[mid_pick])
                my = float(centre[mid, 1] + normal[mid, 1] * offsets[mid_pick])
                if math.hypot(mx - run_x[-1], my - run_y[-1]) > 5_000.0:
                    continue
                run_x.append(mx)
                run_y.append(my)
                last_pick = mid_pick
        off = float(offset[slot])
        pick = int(np.clip(round((off - offsets[0]) / AXIS_SAMPLE_M), 0, width - 1))
        x = float(centre[station, 0] + normal[station, 0] * off)
        y = float(centre[station, 1] + normal[station, 1] * off)
        if run_x and math.hypot(x - run_x[-1], y - run_y[-1]) > 5_000.0:
            if len(run_x) >= 3:
                runs.append((run_x, run_y))
            run_x, run_y = [], []
            last_pick = None
        run_x.append(x)
        run_y.append(y)
        last_pick = pick

    if len(run_x) >= 3:
        runs.append((run_x, run_y))
    runs = [(rx, ry) for rx, ry in runs if len(rx) >= 3]
    if not runs:
        raise RuntimeError("The centreline could not stay on the river for this date pair.")

    from shapely.geometry import MultiLineString

    line_parts = []
    lonlat_parts: list[list[list[float]]] = []
    flat_coords: list[list[float]] = []
    for rx, ry in runs:
        sampled = _forward_points(np.column_stack([rx, ry]), 200.0)
        if len(sampled) < 2:
            continue
        line_parts.append(LineString(sampled))
        lon_line, lat_line = bundle.to_lonlat.transform(sampled[:, 0], sampled[:, 1])
        part = [[round(float(a), 5), round(float(b), 5)] for a, b in zip(lon_line, lat_line)]
        lonlat_parts.append(part)
        flat_coords.extend(part)
    if not line_parts:
        raise RuntimeError("The centreline could not stay on the river for this date pair.")
    line_m = line_parts[0] if len(line_parts) == 1 else MultiLineString(line_parts)
    if len(lonlat_parts) == 1:
        geometry: dict = {"type": "LineString", "coordinates": lonlat_parts[0]}
    else:
        geometry = {"type": "MultiLineString", "coordinates": lonlat_parts}
    feature = {
        "type": "Feature",
        "properties": {"role": "centreline"},
        "geometry": geometry,
    }
    # Bank walk needs a flat vertex list; parts stay separate on the map.
    feature["_flat"] = flat_coords
    return feature, line_m, bundle


def _belt(line_m, bundle, shape: tuple[int, int]) -> np.ndarray:
    from rasterio.features import rasterize

    from .crs import to_lonlat

    transform, _width, _height, _grid = _base_grid()
    return rasterize(
        [(line_m.buffer(BELT_HALF_M), 1)],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype="uint8",
    ).astype(bool)


def _keep(mask: np.ndarray, pixel_km2: float, area_km2: float) -> np.ndarray:
    from skimage.morphology import remove_small_objects

    if not mask.any():
        return mask
    return remove_small_objects(mask, min_size=max(1, int(round(area_km2 / pixel_km2))))


def _fetch(sensor: str, start: date, end_exclusive: date) -> tuple[np.ndarray, np.ndarray, dict, dict]:
    ee = require_ee()
    collection, _region = _collection(ee, sensor, start, end_exclusive)
    scene_count = int(collection.size().getInfo())
    last = end_exclusive - timedelta(days=1)
    method = "VV < -16 dB" if sensor == "microwave" else "NDWI B3 B8 > 0"
    transform, width, height, grid = _base_grid()
    if scene_count == 0:
        meta = {
            "start": start.isoformat(),
            "end": last.isoformat(),
            "label": _label(start, end_exclusive),
            "sensor": sensor,
            "scene_count": 0,
            "latest_scene": None,
            "scale_m": SCALE_M,
            "project": PROJECT,
            "method": method,
            "cleaned": False,
            "water_km2": 0.0,
            "bounds": grid["bounds"],
            "source": "Google Earth Engine",
        }
        empty = np.zeros((height, width), dtype=bool)
        return empty, empty.copy(), grid, meta
    earliest = str(ee.Date(collection.aggregate_min("system:time_start")).format("yyyy-MM-dd").getInfo())
    latest = str(ee.Date(collection.aggregate_max("system:time_start")).format("yyyy-MM-dd").getInfo())
    when = str(ee.Date(collection.aggregate_max("system:time_start")).format("yyyy-MM-dd HH:mm").getInfo())
    water = np.zeros((height, width), dtype=bool)
    observed = np.zeros((height, width), dtype=bool)
    tiles = _tiles()
    for index, box in enumerate(tiles, start=1):
        _set_progress(detail=f"Downloading tile {index} of {len(tiles)}")
        blobs = _read_box(ee, sensor, collection, box)
        if not blobs:
            print(f"  {sensor} tile {index} empty", flush=True)
            continue
        for blob in blobs:
            tile_water, tile_observed, _grid = _on_grid(blob)
            water |= tile_water
            observed |= tile_observed
        _set_progress(detail=f"Cleaned tile {index} of {len(tiles)}")
        print(f"  {sensor} tile {index}/{len(tiles)} {start.isoformat()}", flush=True)
    scale = SCALE_M
    meta = {
        "start": start.isoformat(),
        "end": last.isoformat(),
        "label": _label(start, end_exclusive),
        "sensor": sensor,
        "scene_count": scene_count,
        "earliest_acquisition": earliest,
        "latest_acquisition": latest,
        "latest_scene": f"{when} UTC" if when else None,
        "scale_m": scale,
        "project": PROJECT,
        "method": method,
        "cleaned": False,
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
            transform=np.array(grid["transform"], dtype=np.float64),
            crs=np.array([grid["crs"]]),
        )
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
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
        if "transform" in data:
            grid["transform"] = [float(v) for v in data["transform"]]
            grid["crs"] = str(data["crs"][0])
            grid["pixel_m"] = float(grid["transform"][0])
            x_min = float(grid["transform"][2])
            y_max = float(grid["transform"][5])
            x_max = x_min + shape[1] * abs(grid["transform"][0])
            y_min = y_max - shape[0] * abs(grid["transform"][4])
            grid["bounds_m"] = {
                "x_min": x_min,
                "y_min": y_min,
                "x_max": x_max,
                "y_max": y_max,
            }
        else:
            # Legacy geographic cache — rebuild metric grid metadata from live _base_grid().
            _, _, _, fresh = _base_grid()
            grid.update(fresh)
    return water, observed, grid


def _write_tif(path: Path, water: np.ndarray, observed: np.ndarray, grid: dict) -> None:
    height, width = water.shape
    transform = _grid_affine(grid)
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
        crs=ANALYSIS_CRS_WKT,
        transform=transform,
        nodata=255,
        compress="lzw",
    ) as dst:
        dst.write(band, 1)


_PAIR_CACHE: dict[str, dict] = {}
OPTICAL_RGBA = RIVER_RGBA
MICROWAVE_RGBA = (124, 58, 237, 185)


def _main_body(water: np.ndarray) -> np.ndarray:
    """Report method: ~90 m opening, largest river, restore braids within ~750 m, fill bars."""
    from scipy import ndimage as ndi
    from skimage.morphology import binary_dilation, binary_opening, disk

    if int(water.sum()) < 50:
        return water
    opened = binary_opening(water, footprint=disk(1))
    labels, count = ndi.label(opened)
    if count == 0:
        return ndi.binary_fill_holes(water)
    areas = np.bincount(labels.ravel())
    areas[0] = 0
    spans = np.zeros(count + 1, dtype=np.int32)
    for label in range(1, count + 1):
        cols = np.flatnonzero((labels == label).any(axis=0))
        spans[label] = int(cols[-1] - cols[0]) if cols.size else 0
    # Prefer the long east–west body; fall back to largest area.
    long_enough = np.flatnonzero(spans >= 400)
    if long_enough.size:
        core_id = int(long_enough[np.argmax(areas[long_enough])])
    else:
        core_id = int(np.argmax(areas))
    core = labels == core_id
    river = binary_dilation(core, footprint=disk(8)) & water
    return ndi.binary_fill_holes(river)


def _rc_of(lon: float, lat: float, grid: dict) -> tuple[float, float]:
    from rasterio.transform import rowcol

    bundle = load_crs()
    x, y = bundle.to_metre.transform(lon, lat)
    row, col = rowcol(_grid_affine(grid), x, y)
    return float(row), float(col)


def _lonlat_of(row: float, col: float, grid: dict) -> tuple[float, float]:
    from rasterio.transform import xy

    bundle = load_crs()
    x, y = xy(_grid_affine(grid), row, col, offset="center")
    lon, lat = bundle.to_lonlat.transform(x, y)
    return float(lon), float(lat)


def _bank_lines(envelope: np.ndarray, grid: dict, role: str) -> list[dict]:
    """Outer boundary of the filled river, split into the two banks."""
    from skimage.measure import find_contours

    contours = find_contours(envelope.astype(np.uint8), 0.5)
    if not contours:
        return []
    contour = max(contours, key=len)
    up = _rc_of(95.67, 27.848, grid)
    down = _rc_of(89.985, 26.02, grid)

    def nearest(target: tuple[float, float]) -> int:
        distance = (contour[:, 0] - target[0]) ** 2 + (contour[:, 1] - target[1]) ** 2
        return int(np.argmin(distance))

    start = nearest(up)
    finish = nearest(down)
    if start == finish:
        return []

    def arc(a: int, b: int) -> np.ndarray:
        if a <= b:
            return contour[a : b + 1]
        return np.vstack([contour[a:], contour[: b + 1]])

    def feature(points: np.ndarray, name: str) -> dict:
        step = max(1, len(points) // 800)
        coords = []
        for row, col in points[::step]:
            lon, lat = _lonlat_of(float(row), float(col), grid)
            coords.append([round(lon, 5), round(lat, 5)])
        return {
            "type": "Feature",
            "properties": {"role": name},
            "geometry": {"type": "LineString", "coordinates": coords},
        }

    left = arc(start, finish)
    right = arc(finish, start)
    return [feature(left, f"{role}_left"), feature(right, f"{role}_right")]


def _side_banks(
    body: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    tangent_r: np.ndarray,
    tangent_c: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Nearest outer-bank pixel on each side of the centreline."""
    from skimage.measure import find_contours

    count = len(rows)
    left = np.full(count, -1.0)
    right = np.full(count, -1.0)
    left_rc = np.zeros((count, 2), dtype=np.float64)
    right_rc = np.zeros((count, 2), dtype=np.float64)
    contours = [item for item in find_contours(body.astype(np.uint8), 0.5) if len(item) > 30]
    if not contours:
        return left, right, left_rc, right_rc
    points = np.vstack(contours)
    nearest = np.empty(len(points), dtype=np.int32)
    best = np.full(len(points), np.inf)
    for start in range(0, count, 250):
        stop = min(count, start + 250)
        distance = (points[:, 0:1] - rows[start:stop][None, :]) ** 2 + (points[:, 1:2] - cols[start:stop][None, :]) ** 2
        local = np.argmin(distance, axis=1)
        local_distance = distance[np.arange(len(points)), local]
        better = local_distance < best
        nearest[better] = local[better] + start
        best[better] = local_distance[better]
    offset_r = points[:, 0] - rows[nearest]
    offset_c = points[:, 1] - cols[nearest]
    cross = tangent_r[nearest] * offset_c - tangent_c[nearest] * offset_r
    distance = np.hypot(offset_r, offset_c)

    def keep(sign: float, dist: np.ndarray, place: np.ndarray) -> None:
        chosen = np.flatnonzero(cross * sign > 0)
        if chosen.size == 0:
            return
        order = chosen[np.argsort(distance[chosen])]
        station = nearest[order]
        _unique, first = np.unique(station, return_index=True)
        picked = order[first]
        dist[station[first]] = distance[picked]
        place[station[first]] = points[picked]

    keep(1.0, left, left_rc)
    keep(-1.0, right, right_rc)
    return left, right, left_rc, right_rc


def _fill_bank_gaps(dist: np.ndarray, place: np.ndarray, limit: int = 4) -> None:
    known = np.flatnonzero(dist >= 0)
    if len(known) < 2:
        return
    for start, stop in zip(known[:-1], known[1:]):
        gap = int(stop - start)
        if gap < 2 or gap > limit:
            continue
        for index in range(int(start) + 1, int(stop)):
            weight = (index - start) / gap
            dist[index] = (1.0 - weight) * dist[start] + weight * dist[stop]
            place[index] = (1.0 - weight) * place[start] + weight * place[stop]


def _smooth_bank(dist: np.ndarray, place: np.ndarray, rows: np.ndarray, cols: np.ndarray, size: int = 7) -> None:
    """Steady the bank so a one-pixel mask wobble is not drawn as change."""
    from scipy.ndimage import median_filter

    valid = np.flatnonzero(dist >= 0)
    if valid.size < size:
        return
    dist[valid] = median_filter(dist[valid], size=size, mode="nearest")
    for index in valid:
        step = float(dist[index])
        vector_r = float(place[index, 0] - rows[index])
        vector_c = float(place[index, 1] - cols[index])
        length = math.hypot(vector_r, vector_c)
        if length < 1e-6:
            continue
        place[index, 0] = rows[index] + vector_r / length * step
        place[index, 1] = cols[index] + vector_c / length * step


def _ribbons(
    centre: list[list[float]],
    earlier_body: np.ndarray,
    later_body: np.ndarray,
    grid: dict,
) -> tuple[np.ndarray, np.ndarray, list[dict], list[dict], int, int]:
    """Colour only the strip between one date's bank and the other date's bank."""
    from skimage.draw import polygon

    height, width = later_body.shape
    blank = np.zeros((height, width), dtype=bool)
    if len(centre) < 4:
        return blank, blank.copy(), [], [], 0, 0

    rows = np.array([_rc_of(lon, lat, grid)[0] for lon, lat in centre], dtype=np.float64)
    cols = np.array([_rc_of(lon, lat, grid)[1] for lon, lat in centre], dtype=np.float64)
    tangent_r = np.gradient(rows)
    tangent_c = np.gradient(cols)
    scale = np.maximum(np.hypot(tangent_r, tangent_c), 1e-6)
    tangent_r /= scale
    tangent_c /= scale

    start_left, start_right, start_left_rc, start_right_rc = _side_banks(earlier_body, rows, cols, tangent_r, tangent_c)
    end_left, end_right, end_left_rc, end_right_rc = _side_banks(later_body, rows, cols, tangent_r, tangent_c)
    for dist, place in (
        (start_left, start_left_rc),
        (start_right, start_right_rc),
        (end_left, end_left_rc),
        (end_right, end_right_rc),
    ):
        _fill_bank_gaps(dist, place)
        _smooth_bank(dist, place, rows, cols)

    erosion_id = np.zeros((height, width), dtype=np.int32)
    deposition_id = np.zeros((height, width), dtype=np.int32)
    next_id = {"erosion": 1, "deposition": 1}
    located: dict[str, dict[int, tuple[float, float, float]]] = {"erosion": {}, "deposition": {}}
    sides = (
        (start_left, end_left, start_left_rc, end_left_rc),
        (start_right, end_right, start_right_rc, end_right_rc),
    )
    for start_dist, end_dist, start_rc, end_rc in sides:
        current: str | None = None
        current_id = 0
        for index in range(len(centre) - 1):
            shift = float(end_dist[index] - start_dist[index])
            shift_next = float(end_dist[index + 1] - start_dist[index + 1])
            ready = (
                start_dist[index] >= 0
                and end_dist[index] >= 0
                and start_dist[index + 1] >= 0
                and end_dist[index + 1] >= 0
                and abs(shift) >= 4
                and abs(shift_next) >= 4
                and abs(shift) <= 50
                and abs(shift_next) <= 50
                and (shift > 0) == (shift_next > 0)
            )
            if ready:
                start_vector = start_rc[index] - np.array([rows[index], cols[index]])
                end_vector = end_rc[index] - np.array([rows[index], cols[index]])
                ready = bool(np.dot(start_vector, end_vector) > 0)
            if not ready:
                current = None
                continue
            kind = "erosion" if shift > 0 else "deposition"
            layer = erosion_id if kind == "erosion" else deposition_id
            if kind != current:
                current = kind
                current_id = next_id[kind]
                next_id[kind] += 1
                located[kind][current_id] = (*_lonlat_of(float(start_rc[index, 0]), float(start_rc[index, 1]), grid), abs(shift))
            elif abs(shift) > located[kind][current_id][2]:
                located[kind][current_id] = (*_lonlat_of(float(start_rc[index, 0]), float(start_rc[index, 1]), grid), abs(shift))
            painted_rows, painted_cols = polygon(
                [start_rc[index, 0], start_rc[index + 1, 0], end_rc[index + 1, 0], end_rc[index, 0]],
                [start_rc[index, 1], start_rc[index + 1, 1], end_rc[index + 1, 1], end_rc[index, 1]],
                shape=(height, width),
            )
            layer[painted_rows, painted_cols] = current_id

    erosion = erosion_id > 0
    deposition = deposition_id > 0
    erosion &= later_body & ~earlier_body
    deposition &= earlier_body & ~later_body
    erosion_id = np.where(erosion, erosion_id, 0)
    deposition_id = np.where(deposition, deposition_id, 0)

    def ranked(kind: str, labels: np.ndarray) -> tuple[list[dict], int]:
        counts = np.bincount(labels.ravel())
        rows_out = []
        for label, (lon, lat, _shift) in located[kind].items():
            if label >= len(counts) or counts[label] == 0:
                continue
            area = round(int(counts[label]) * float(grid["pixel_km2"]), 2)
            if area < 0.1:
                continue
            chosen = np.argwhere(labels == label)
            row, col = _rc_of(lon, lat, grid)
            nearest = int(np.argmin((chosen[:, 0] - row) ** 2 + (chosen[:, 1] - col) ** 2))
            hit_lon, hit_lat = _lonlat_of(float(chosen[nearest, 0]) + 0.5, float(chosen[nearest, 1]) + 0.5, grid)
            rows_out.append(
                {
                    "area_km2": area,
                    "area_display": fmt_area(area),
                    "latitude": round(hit_lat, 5),
                    "longitude": round(hit_lon, 5),
                }
            )
        rows_out.sort(key=lambda item: item["area_km2"], reverse=True)
        shown = []
        for rank, item in enumerate(rows_out[:25], start=1):
            item["rank"] = rank
            shown.append(item)
        return shown, len(rows_out)

    erosion_rows, erosion_count = ranked("erosion", erosion_id)
    deposition_rows, deposition_count = ranked("deposition", deposition_id)
    return erosion, deposition, erosion_rows, deposition_rows, erosion_count, deposition_count

def _piece_line(mask: np.ndarray, grid: dict) -> list[list[float]]:
    """Centre of one channel piece, ordered from its east end to its west end."""
    from scipy import ndimage as ndi
    from skimage.graph import MCP_Geometric
    from skimage.morphology import binary_closing, disk, medial_axis

    linked = ndi.binary_fill_holes(binary_closing(mask, footprint=disk(6)))
    skeleton = medial_axis(linked)
    if int(skeleton.sum()) < 20:
        return []
    selected = np.column_stack(np.nonzero(skeleton))
    east = selected[int(np.argmax(selected[:, 1]))]
    west = selected[int(np.argmin(selected[:, 1]))]
    start = (int(east[0]), int(east[1]))
    finish = (int(west[0]), int(west[1]))
    if start == finish:
        return []
    finder = MCP_Geometric(np.where(skeleton, 1.0, np.inf), fully_connected=True)
    finder.find_costs([start])
    try:
        route = finder.traceback(finish)
    except ValueError:
        return []
    coords = []
    for row, col in route[::8]:
        lon, lat = _lonlat_of(float(row), float(col), grid)
        coords.append([round(lon, 5), round(lat, 5)])
    if len(coords) >= 2 and coords[0][0] < coords[-1][0]:
        coords.reverse()
    return coords


def _centre_from_body(body: np.ndarray, grid: dict) -> dict | None:
    """One centreline through every long piece of the main channel, east to west."""
    from scipy import ndimage as ndi

    if int(body.sum()) < 50:
        return None
    labels, count = ndi.label(body)
    pieces: list[tuple[float, list[list[float]]]] = []
    for label in range(1, count + 1):
        mask = labels == label
        cols = np.flatnonzero(mask.any(axis=0))
        if cols.size == 0 or int(cols[-1] - cols[0]) < 400:
            continue
        coords = _piece_line(mask, grid)
        if len(coords) >= 2:
            pieces.append((float(cols[-1]), coords))
    if not pieces:
        return None
    pieces.sort(key=lambda item: item[0], reverse=True)
    coords: list[list[float]] = []
    for _east, part in pieces:
        coords.extend(part)
    if len(coords) < 2:
        return None
    return {
        "type": "Feature",
        "properties": {"role": "centreline"},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _date_river(optical: np.ndarray, microwave: np.ndarray, observed: np.ndarray, corridor: np.ndarray) -> np.ndarray:
    """Main channel from optical water. Microwave fills only cloudy gaps beside that channel."""
    from skimage.morphology import binary_dilation, disk

    channel = _main_body(optical & corridor)
    if int(channel.sum()) < 8_000:
        return _main_body((optical | microwave) & corridor)
    cloudy = microwave & corridor & ~observed & binary_dilation(channel, footprint=disk(12))
    if not cloudy.any():
        return channel
    return _main_body(channel | cloudy)


def _fused(optical: dict, sar: dict, belt: np.ndarray, pixel_km2: float) -> tuple[np.ndarray, np.ndarray]:
    """River water on one date: Sentinel-2 or Sentinel-1 water inside the river belt."""
    water = (optical["water"] | sar["water"]) & belt
    water = _keep(water, pixel_km2, 0.2)
    observed = (optical["observed"] | sar["observed"]) & belt
    return water, observed


def _bank_shift(
    centre: list[list[float]],
    earlier_mask: np.ndarray,
    later_mask: np.ndarray,
    grid: dict,
) -> tuple[np.ndarray, np.ndarray, list[dict], list[dict], int, int, list[dict]]:
    """Outermost bank on each side; colour only the strip between the two dates' banks."""
    from scipy.ndimage import median_filter

    height, width = later_mask.shape
    erosion = np.zeros((height, width), dtype=bool)
    deposition = np.zeros((height, width), dtype=bool)
    empty: tuple[np.ndarray, np.ndarray, list[dict], list[dict], int, int, list[dict]] = (
        erosion,
        deposition,
        [],
        [],
        0,
        0,
        [],
    )
    if len(centre) < 4:
        return empty
    # One station every ~500 m (axis points are 500 m apart already).
    sample = list(range(0, len(centre), 1))
    rows = np.array([_rc_of(centre[i][0], centre[i][1], grid)[0] for i in sample])
    cols = np.array([_rc_of(centre[i][0], centre[i][1], grid)[1] for i in sample])
    tangent_r = np.gradient(rows)
    tangent_c = np.gradient(cols)
    scale = np.maximum(np.hypot(tangent_r, tangent_c), 1e-6)
    side_r = -tangent_c / scale
    side_c = tangent_r / scale
    union = earlier_mask | later_mask
    on_river = np.zeros(len(sample), dtype=bool)
    for index in range(len(sample)):
        rr, cc = int(round(rows[index])), int(round(cols[index]))
        if 0 <= rr < height and 0 <= cc < width and union[max(0, rr - 2) : rr + 3, max(0, cc - 2) : cc + 3].any():
            on_river[index] = True

    def outermost(mask: np.ndarray, index: int, sign: float) -> int:
        if not on_river[index]:
            return -1
        rr0, cc0 = int(round(rows[index])), int(round(cols[index]))
        last = 0 if (0 <= rr0 < height and 0 <= cc0 < width and mask[rr0, cc0]) else -1
        missed = 0
        for step in range(1, 121):
            rr = int(round(rows[index] + sign * side_r[index] * step))
            cc = int(round(cols[index] + sign * side_c[index] * step))
            if not (0 <= rr < height and 0 <= cc < width):
                break
            if mask[rr, cc]:
                last = step
                missed = 0
            else:
                missed += 1
                if last >= 0 and missed >= 3:
                    break
        return last

    def place(index: int, step: float, sign: float) -> list[float]:
        lon, lat = _lonlat_of(
            float(rows[index] + sign * side_r[index] * step),
            float(cols[index] + sign * side_c[index] * step),
            grid,
        )
        return [round(lon, 5), round(lat, 5)]

    def smooth_hits(hits: np.ndarray) -> np.ndarray:
        out = hits.astype(np.float64)
        known = np.flatnonzero(out >= 0)
        if known.size < 3:
            return hits
        values = median_filter(out[known], size=5, mode="nearest")
        out[known] = values
        return out

    banks: dict[str, list[list[float]]] = {
        "start_left": [],
        "start_right": [],
        "end_left": [],
        "end_right": [],
    }
    reaches: list[dict] = []
    for sign, side_name in ((1.0, "left"), (-1.0, "right")):
        start_hits = smooth_hits(np.array([outermost(earlier_mask, index, sign) for index in range(len(sample))]))
        end_hits = smooth_hits(np.array([outermost(later_mask, index, sign) for index in range(len(sample))]))
        current: dict | None = None
        for index in range(len(sample)):
            start_hit = int(round(start_hits[index])) if start_hits[index] >= 0 else -1
            end_hit = int(round(end_hits[index])) if end_hits[index] >= 0 else -1
            if start_hit >= 0:
                banks[f"start_{side_name}"].append(place(index, max(start_hit, 1), sign))
            if end_hit >= 0:
                banks[f"end_{side_name}"].append(place(index, max(end_hit, 1), sign))
            # Sideways bank movement of at least ~100 m (one pixel).
            if start_hit < 0 or end_hit < 0 or abs(end_hit - start_hit) < 1:
                if current is not None:
                    reaches.append(current)
                    current = None
                continue
            kind = "erosion" if end_hit > start_hit else "deposition"
            target = erosion if kind == "erosion" else deposition
            lo, hi = sorted((start_hit, end_hit))
            for step in range(lo, hi + 1):
                rr = int(round(rows[index] + sign * side_r[index] * step))
                cc = int(round(cols[index] + sign * side_c[index] * step))
                if 0 <= rr < height and 0 <= cc < width:
                    target[rr - 1 : rr + 2, cc - 1 : cc + 2] = True
            if current is not None and current["kind"] == kind:
                current["area"] += hi - lo
            else:
                if current is not None:
                    reaches.append(current)
                lon, lat = place(index, (start_hit + end_hit) / 2.0, sign)
                current = {"kind": kind, "area": hi - lo, "lon": lon, "lat": lat}
        if current is not None:
            reaches.append(current)

    def ranked(kind: str) -> tuple[list[dict], int]:
        rows_out = []
        for item in reaches:
            if item["kind"] != kind:
                continue
            area = round(float(item["area"]) * float(grid["pixel_km2"]), 2)
            if area < 0.1:
                continue
            rows_out.append(
                {
                    "area_km2": area,
                    "area_display": fmt_area(area),
                    "latitude": item["lat"],
                    "longitude": item["lon"],
                }
            )
        rows_out.sort(key=lambda item: item["area_km2"], reverse=True)
        shown = []
        for rank, item in enumerate(rows_out[:25], start=1):
            item["rank"] = rank
            shown.append(item)
        return shown, len(rows_out)

    features = []
    for name, line in banks.items():
        if len(line) < 2:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {"role": name},
                "geometry": {"type": "LineString", "coordinates": line},
            }
        )
    erosion_rows, erosion_count = ranked("erosion")
    deposition_rows, deposition_count = ranked("deposition")
    return erosion, deposition, erosion_rows, deposition_rows, erosion_count, deposition_count, features


def _ranked_patches(mask: np.ndarray, grid: dict, limit: int = 25) -> tuple[list[dict], int]:
    from scipy import ndimage as ndi

    labels, count = ndi.label(np.asarray(mask, dtype=bool))
    if count == 0:
        return [], 0
    areas = np.bincount(labels.ravel())
    areas[0] = 0
    order = np.argsort(areas)[::-1]
    rows: list[dict] = []
    kept = 0
    for label in order:
        if label == 0 or areas[label] <= 0:
            continue
        kept += 1
        if len(rows) >= limit:
            continue
        ys, xs = np.where(labels == label)
        area = round(float(areas[label]) * float(grid["pixel_km2"]), 2)
        if area < 0.1:
            continue
        lon, lat = _lonlat_of(float(ys.mean()), float(xs.mean()), grid)
        rows.append(
            {
                "rank": len(rows) + 1,
                "area_km2": area,
                "area_display": fmt_area(area),
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
            }
        )
    return rows, kept


def _pair_from_request(req, staged: bool = False, *, fetch_both_sensors: bool | None = None) -> dict:
    """Outer-envelope bankline comparison for a CompareRequest.

    fetch_both_sensors: when True (default for staged UI runs), download optical and
    microwave for map overlays. Validation can pass False to halve EE downloads.
    """
    from .bankline_compare import (
        DEFAULT_CLOSE_M,
        BanklineQCError,
        build_date_corridor,
        compare_corridors,
        guide_search_mask,
    )
    from .date_options import MIN_VALID_FRACTION
    from .guide import load_guide_lonlat

    sensor = req.sensor
    earlier_window = (req.earlier.start, req.earlier.end_exclusive)
    later_window = (req.later.start, req.later.end_exclusive)
    cache_key = req.cache_key(close_m=DEFAULT_CLOSE_M, scale_m=SCALE_M, crs=ANALYSIS_CRS)
    # Never reuse envv1 / envv2 keys — algorithm version is part of cache_key.
    if cache_key in _PAIR_CACHE:
        return _PAIR_CACHE[cache_key]

    want_both = staged if fetch_both_sensors is None else fetch_both_sensors
    empty_meta = {"scene_count": 0, "label": "skipped", "latest_scene": None, "method": "skipped"}

    def _blank_like(ref: dict) -> dict:
        shape = ref["water"].shape
        return {
            "water": np.zeros(shape, dtype=bool),
            "observed": np.zeros(shape, dtype=bool),
            "grid": ref["grid"],
            "meta": dict(empty_meta),
        }

    if want_both:
        earlier_opt = extract_window(*earlier_window, "optical", "Base optical" if staged else "")
        earlier_sar = extract_window(*earlier_window, "microwave", "Base microwave" if staged else "")
        later_opt = extract_window(*later_window, "optical", "Current optical" if staged else "")
        later_sar = extract_window(*later_window, "microwave", "Current microwave" if staged else "")
    elif sensor == "optical":
        earlier_opt = extract_window(*earlier_window, "optical", "Base optical" if staged else "")
        later_opt = extract_window(*later_window, "optical", "Current optical" if staged else "")
        earlier_sar = _blank_like(earlier_opt)
        later_sar = _blank_like(later_opt)
    else:
        earlier_sar = extract_window(*earlier_window, "microwave", "Base microwave" if staged else "")
        later_sar = extract_window(*later_window, "microwave", "Current microwave" if staged else "")
        earlier_opt = _blank_like(earlier_sar)
        later_opt = _blank_like(later_sar)

    if sensor == "optical":
        earlier, later = earlier_opt, later_opt
        if earlier["meta"]["scene_count"] == 0:
            raise RuntimeError(f"No Sentinel-2 scenes for {earlier['meta']['label']}.")
        if later["meta"]["scene_count"] == 0:
            raise RuntimeError(f"No Sentinel-2 scenes for {later['meta']['label']}.")
        earlier_src, later_src = earlier, later
    else:
        earlier, later = earlier_sar, later_sar
        if earlier_sar["meta"]["scene_count"] == 0:
            raise RuntimeError(f"No Sentinel-1 scenes for {earlier_sar['meta']['label']}.")
        if later_sar["meta"]["scene_count"] == 0:
            raise RuntimeError(f"No Sentinel-1 scenes for {later_sar['meta']['label']}.")
        earlier_src, later_src = earlier_sar, later_sar

    if staged:
        _set_progress(step="Difference", detail="Building outer envelopes and banklines")
    grid_ref = later_src
    grid = grid_ref["grid"]
    transform, _width, _height, _grid = _base_grid()
    corridor = _river_belt(grid_ref["water"].shape[0], grid_ref["water"].shape[1], transform, 20_000)
    guide_mask = guide_search_mask(grid_ref["water"].shape[0], grid_ref["water"].shape[1], transform, 8_000.0)
    guide = load_guide_lonlat()
    try:
        earlier_corridor = build_date_corridor(
            earlier_src["water"],
            earlier_src["observed"],
            corridor,
            guide_mask,
            guide,
            transform,
            close_m=DEFAULT_CLOSE_M,
        )
        later_corridor = build_date_corridor(
            later_src["water"],
            later_src["observed"],
            corridor,
            guide_mask,
            guide,
            transform,
            close_m=DEFAULT_CLOSE_M,
        )
        elapsed_years = max((req.later.end - req.earlier.end).days / 365.25, 0.0)
        safe_key = cache_key.replace("|", "_").replace("=", "-")
        compared = compare_corridors(
            earlier_corridor,
            later_corridor,
            corridor,
            transform,
            guide,
            elapsed_years=elapsed_years,
            transect_csv=OVERLAY_DIR / f"{safe_key}-transects.csv",
        )
    except BanklineQCError as exc:
        raise RuntimeError(str(exc)) from exc

    observation = compared.get("observation") or {}
    valid_fraction = float(
        observation.get("common_valid_fraction_of_corridor")
        or compared["stats"].get("valid_fraction")
        or 0.0
    )
    partial = valid_fraction < MIN_VALID_FRACTION

    erosion = compared["erosion"]
    deposition = compared["deposition"]
    persistent = compared["persistent"]
    erosion_rows, erosion_count = _ranked_patches(erosion, grid)
    deposition_rows, deposition_count = _ranked_patches(deposition, grid)
    optical_water = later_opt["water"] & corridor
    sar_water = later_sar["water"] & corridor
    result = {
        "request": req.as_dict(),
        "earlier_window": earlier_window,
        "later_window": later_window,
        "earlier": earlier_opt if sensor == "optical" else earlier_sar,
        "later": later_opt if sensor == "optical" else later_sar,
        "later_sar": later_sar,
        "earlier_sar": earlier_sar,
        "earlier_opt": earlier_opt,
        "later_opt": later_opt,
        "grid": grid,
        "axis": None,
        "belt": corridor,
        "earlier_water": earlier_src["water"] & corridor,
        "earlier_observed": earlier_src["observed"] & corridor,
        "later_water": later_src["water"] & corridor,
        "later_observed": later_src["observed"] & corridor,
        "optical_water": optical_water,
        "sar_water": sar_water,
        "earlier_body": earlier_corridor.envelope,
        "later_body": later_corridor.envelope,
        "erosion": erosion,
        "deposition": deposition,
        "persistent": persistent,
        "banks": compared["banks"],
        "envelopes": compared["envelopes"],
        "transects": compared["transects"],
        "transect_qc": compared.get("transect_qc"),
        "observation": observation,
        "valid": compared["valid"],
        "erosion_raw": compared.get("erosion_raw"),
        "deposition_raw": compared.get("deposition_raw"),
        "stats": compared["stats"],
        "method_note": compared["method_note"],
        "sensor": sensor,
        "partial_coverage": partial,
        "requires_ack": partial and not req.acknowledge_partial,
        "min_valid_fraction": MIN_VALID_FRACTION,
        "acquisition": {
            "earlier": {
                "requested": req.earlier.label,
                "scene_count": earlier_src["meta"]["scene_count"],
                "earliest_acquisition": earlier_src["meta"].get("earliest_acquisition"),
                "latest_acquisition": earlier_src["meta"].get("latest_acquisition"),
                "latest_scene": earlier_src["meta"].get("latest_scene"),
                "method": earlier_src["meta"].get("method"),
                "sensor": sensor,
                "composite_method": earlier_src["meta"].get("method"),
                "scale_m": earlier_src["meta"].get("scale_m", SCALE_M),
            },
            "later": {
                "requested": req.later.label,
                "scene_count": later_src["meta"]["scene_count"],
                "earliest_acquisition": later_src["meta"].get("earliest_acquisition"),
                "latest_acquisition": later_src["meta"].get("latest_acquisition"),
                "latest_scene": later_src["meta"].get("latest_scene"),
                "method": later_src["meta"].get("method"),
                "sensor": sensor,
                "composite_method": later_src["meta"].get("method"),
                "scale_m": later_src["meta"].get("scale_m", SCALE_M),
            },
        },
        "erosion_rows": erosion_rows,
        "deposition_rows": deposition_rows,
        "erosion_count": erosion_count,
        "deposition_count": deposition_count,
        "key": cache_key,
        "close_m": DEFAULT_CLOSE_M,
    }
    if len(_PAIR_CACHE) >= 3:
        _PAIR_CACHE.pop(next(iter(_PAIR_CACHE)))
    _PAIR_CACHE[cache_key] = result
    return result


def _pair(end_text: str, start_text: str | None, staged: bool = False, sensor: str = "optical") -> dict:
    """Backward-compatible wrapper around Mode A dates."""
    from .date_options import build_compare_request

    req = build_compare_request(mode="dates", later=end_text, earlier=start_text, sensor=sensor)
    return _pair_from_request(req, staged=staged)


def compare_dates(
    end_text: str | None = None,
    start_text: str | None = None,
    sensor: str = "optical",
    *,
    request=None,
) -> dict:
    from .date_options import build_compare_request

    req = request or build_compare_request(mode="dates", later=end_text, earlier=start_text, sensor=sensor)
    pair = _pair_from_request(req, staged=True)
    grid = pair["grid"]
    later_window = pair["later_window"]
    earlier = pair["earlier"]
    later = pair["later"]
    stats = pair["stats"]
    pixel_km2 = grid["pixel_km2"]

    def display_area(mask: np.ndarray) -> float:
        return round(float(mask.sum()) * pixel_km2, 2)

    erosion_km2 = float(stats["erosion_km2"])
    deposition_km2 = float(stats["deposition_km2"])
    persistent_km2 = float(stats["persistent_km2"])
    net = float(stats["net_km2"])
    optical_km2 = display_area(pair["optical_water"])
    sar_km2 = display_area(pair["sar_water"])

    safe_key = str(pair["key"]).replace("|", "_").replace("=", "-")
    optical_name = f"{safe_key}-optical.png"
    sar_name = f"{safe_key}-microwave.png"
    erosion_name = f"{safe_key}-erosion.png"
    deposition_name = f"{safe_key}-deposition.png"
    write_mask_png(pair["optical_water"], OPTICAL_RGBA, OVERLAY_DIR / optical_name)
    write_mask_png(pair["sar_water"], MICROWAVE_RGBA, OVERLAY_DIR / sar_name)
    write_mask_png(pair["erosion"], EROSION_RGBA, OVERLAY_DIR / erosion_name)
    write_mask_png(pair["deposition"], DEPOSITION_RGBA, OVERLAY_DIR / deposition_name)
    write_mask_png(pair["later_body"], OPTICAL_RGBA, OVERLAY_DIR / _overlay_name(*later_window, "river"))

    earlier_env_name = f"{safe_key}-earlier-envelope.png"
    later_env_name = f"{safe_key}-later-envelope.png"
    write_mask_png(pair["earlier_body"], (56, 189, 248, 70), OVERLAY_DIR / earlier_env_name)
    write_mask_png(pair["later_body"], (245, 158, 11, 70), OVERLAY_DIR / later_env_name)

    req_meta = pair.get("request") or {}
    mode = req_meta.get("mode", "dates")
    window_days = req_meta.get("window_days", WINDOW_DAYS)
    if mode == "dates":
        timing_note = (
            f"Mode A: each selected date ends a {window_days}-day composite "
            f"(not a single acquisition, and not the full interval between dates)."
        )
    else:
        timing_note = (
            "Mode B: each observation is an independent period composite. "
            "The gap between periods is not filled with imagery."
        )
    tqc = pair.get("transect_qc") or {}
    obs = pair.get("observation") or {}
    return {
        "available": True,
        "earlier_id": req.earlier.end.isoformat(),
        "later_id": req.later.end.isoformat(),
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
        "earlier_water_km2": float(stats["earlier_km2"]),
        "later_water_km2": float(stats["later_km2"]),
        "earlier_envelope_km2": float(stats.get("earlier_envelope_km2", stats["earlier_km2"])),
        "later_envelope_km2": float(stats.get("later_envelope_km2", stats["later_km2"])),
        "later_water_display": fmt_area(optical_km2),
        "microwave_water_km2": sar_km2,
        "microwave_water_display": fmt_area(sar_km2),
        "microwave_png": f"/api/overlays/{sar_name}",
        "earlier_envelope_png": f"/api/overlays/{earlier_env_name}",
        "later_envelope_png": f"/api/overlays/{later_env_name}",
        "optical_scene": pair["later_opt"]["meta"].get("latest_scene") if "later_opt" in pair else later["meta"].get("latest_scene"),
        "microwave_scene": pair["later_sar"]["meta"].get("latest_scene"),
        "unit": "km²",
        "validation_status": "partial" if pair.get("partial_coverage") else "ready",
        "disclaimer": pair["method_note"],
        "erosion_png": f"/api/overlays/{erosion_name}",
        "deposition_png": f"/api/overlays/{deposition_name}",
        "river_png": f"/api/overlays/{optical_name}",
        "bounds": grid["bounds"],
        "note": (
            f"{timing_note} Sensor: {pair['sensor']}. "
            f"Valid overlap: {100 * float(stats['valid_fraction']):.1f}% of corridor. "
            f"Common-valid corridors: earlier {stats['earlier_km2']} km², later {stats['later_km2']} km² "
            f"(full envelopes {stats.get('earlier_full_km2')} / {stats.get('later_full_km2')} km²). "
            f"Transects both_ok {tqc.get('both_ok', 0)} within mutual span "
            f"{tqc.get('first_both_ok_chainage_m')}–{tqc.get('last_both_ok_chainage_m')} m "
            f"({tqc.get('pct_of_mutual_span')}% of that span)."
        ),
        "request": req_meta,
        "acquisition": pair.get("acquisition"),
        "observation": obs,
        "transect_qc": tqc,
        "partial_coverage": bool(pair.get("partial_coverage")),
        "requires_ack": bool(pair.get("partial_coverage")) and not req.acknowledge_partial,
        "min_valid_fraction": pair.get("min_valid_fraction"),
        "coverage_warning": obs.get("coverage_warning"),
        "close_m": pair.get("close_m"),
        "rows": [],
        "centerline": None,
        "banks": {"type": "FeatureCollection", "features": pair["banks"]},
        "envelopes": {
            "type": "FeatureCollection",
            "features": [pair["envelopes"]["earlier"], pair["envelopes"]["later"]],
        },
        "valid_fraction": float(stats["valid_fraction"]),
        "valid_pixels": int(stats["valid_pixels"]),
        "sensor": pair["sensor"],
        "scene_count": later["meta"]["scene_count"],
        "scale_m": SCALE_M,
        "source": "Google Earth Engine",
    }


def period_points(end_text: str, start_text: str | None) -> dict:
    pair = _pair(end_text, start_text)
    grid = pair["grid"]
    erosion_rows, erosion_count = pair["erosion_rows"], pair["erosion_count"]
    deposition_rows, deposition_count = pair["deposition_rows"], pair["deposition_count"]
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
    pair = _pair(end_text, start_text)
    grid = pair["grid"]
    earlier_label = pair["earlier"]["meta"]["label"]
    later_label = pair["later"]["meta"]["label"]
    row_f, col_f = _pixel_rc(lon, lat, grid)
    row, col = int(np.floor(row_f)), int(np.floor(col_f))
    inside = 0 <= row < grid["height"] and 0 <= col < grid["width"]
    if not inside:
        name = "outside"
    elif pair["erosion"][row, col]:
        name = "corridor_expansion"
    elif pair["deposition"][row, col]:
        name = "corridor_contraction"
    elif pair["earlier_body"][row, col] and pair["later_body"][row, col]:
        name = "persistent_water"
    elif pair["earlier_body"][row, col] or pair["later_body"][row, col]:
        name = "river"
    else:
        name = "land"
    labels = {
        "corridor_expansion": "Corridor expansion (erosion candidate)",
        "corridor_contraction": "Corridor contraction (deposition candidate)",
        "persistent_water": "Persistent corridor",
        "river": "River corridor",
        "land": "Outside corridor",
        "nodata": "No observation",
        "outside": "Outside the map",
    }
    zone = None
    if name == "corridor_expansion":
        zone = _zone(pair["erosion"], row, col, grid, name, earlier_label, later_label)
    elif name == "corridor_contraction":
        zone = _zone(pair["deposition"], row, col, grid, name, earlier_label, later_label)
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
    for path in sorted(LIVE_DIR.glob("gee5-*.json")):
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


def _corridor_observed_fraction(start: date, end_exclusive: date, sensor: str) -> float | None:
    """Observed pixels / river-belt pixels from an on-disk gee7 cache, if present."""
    cached = _cached(start, end_exclusive, sensor)
    if cached is None:
        return None
    transform, _width, height, _grid = _base_grid()
    width = cached["water"].shape[1]
    corridor = _river_belt(height, width, transform, 20_000)
    observed_in_corridor = cached["observed"] & corridor
    denom = int(corridor.sum())
    if denom == 0:
        return None
    return float(observed_in_corridor.sum()) / denom


def _preflight_corridor_coverage(request) -> dict:
    """Scene count ≠ corridor coverage; use cached masks when available (no EE download)."""
    from .date_options import CLASSIFICATION, MASKING

    note = (
        "Scene counts show catalogue availability only; they do not equal usable "
        "corridor coverage after cloud/shadow masking and period compositing."
    )
    e_start, e_end = request.earlier.start, request.earlier.end_exclusive
    l_start, l_end = request.later.start, request.later.end_exclusive
    sensor = request.sensor
    earlier_frac = _corridor_observed_fraction(e_start, e_end, sensor)
    later_frac = _corridor_observed_fraction(l_start, l_end, sensor)
    base = {
        "corridor_coverage_note": note,
        "classification": CLASSIFICATION[sensor],
        "masking": MASKING[sensor],
    }
    if earlier_frac is None and later_frac is None:
        return {
            **base,
            "coverage_status": "scenes_only",
            "coverage_detail": (
                "No cached composites for these windows; final valid overlap along "
                "the corridor is computed after extract."
            ),
        }
    out = {**base, "earlier_corridor_observed_fraction": earlier_frac, "later_corridor_observed_fraction": later_frac}
    earlier_cached = _cached(e_start, e_end, sensor)
    later_cached = _cached(l_start, l_end, sensor)
    if earlier_cached is not None and later_cached is not None:
        transform, _width, height, _grid = _base_grid()
        width = earlier_cached["water"].shape[1]
        corridor = _river_belt(height, width, transform, 20_000)
        common = (earlier_cached["observed"] & later_cached["observed"] & corridor).sum()
        denom = int(corridor.sum())
        common_frac = float(common) / denom if denom else None
        out["coverage_status"] = "cached_estimate"
        out["estimated_common_observed_fraction"] = common_frac
        out["coverage_detail"] = (
            "Cached mask fractions along the 20 km river belt "
            f"(earlier {100 * earlier_frac:.1f}%, later {100 * later_frac:.1f}%"
            + (f", common {100 * common_frac:.1f}%)" if common_frac is not None else ").")
            + " Final bankline valid overlap is still computed after extract."
        )
        return out
    out["coverage_status"] = "cached_partial"
    known = []
    if earlier_frac is not None:
        known.append(f"earlier {100 * earlier_frac:.1f}%")
    if later_frac is not None:
        known.append(f"later {100 * later_frac:.1f}%")
    out["coverage_detail"] = (
        f"Only one window has a cached composite ({', '.join(known)} along the river belt). "
        "Final valid overlap is computed after extract."
    )
    return out


def preflight_availability(request) -> dict:
    """Check EE scene availability before a long compute."""
    ee = require_ee()
    region = _rectangle(ee)
    from .date_options import probe_collection

    earlier = probe_collection(ee, request.sensor, request.earlier, region)
    later = probe_collection(ee, request.sensor, request.later, region)
    coverage = _preflight_corridor_coverage(request)
    ok = bool(earlier.get("ok") and later.get("ok"))
    return {
        "ok": ok,
        "sensor": request.sensor,
        "mode": request.mode,
        "window_days": request.window_days,
        "request": request.as_dict(),
        "earlier": earlier,
        "later": later,
        "archive_start": (
            "2017-03-28" if request.sensor == "optical" else "2014-10-03"
        ),
        **coverage,
        "detail": None if ok else (earlier.get("detail") if not earlier.get("ok") else later.get("detail")),
    }


def _compute_worker() -> None:
    global _WORKER_ON, _NEXT
    while True:
        with _LOCK:
            job = _NEXT
            _NEXT = None
            if job is None:
                _WORKER_ON = False
                return
        request, ticket = job
        _JOB.ticket = ticket
        try:
            change = compare_dates(request=request)
            with _LOCK:
                if _PROGRESS.get("ticket") != ticket:
                    continue
            _set_progress(step="Points", detail="Ranking expansion and contraction patches")
            pair = _pair_from_request(request, staged=False)
            points = {
                "later_id": request.later.end.isoformat(),
                "earlier_id": request.earlier.end.isoformat(),
                "erosion": pair["erosion_rows"],
                "deposition": pair["deposition_rows"],
                "erosion_count": pair["erosion_count"],
                "deposition_count": pair["deposition_count"],
                "shown": len(pair["erosion_rows"]),
            }
            with _LOCK:
                if _PROGRESS.get("ticket") != ticket:
                    continue
                _PROGRESS.update(
                    running=False,
                    done=True,
                    error=None,
                    change=change,
                    points=points,
                    step="Done",
                    detail="Ready",
                )
        except Exception as exc:  # noqa: BLE001
            with _LOCK:
                if _PROGRESS.get("ticket") != ticket:
                    continue
                _PROGRESS.update(running=False, done=True, error=str(exc), step="Done", detail="")


def begin_compute(later: str | None = None, earlier: str | None = None, **options) -> bool:
    """Start this pair. A newer click replaces one that is still running."""
    global _TICKET, _NEXT, _WORKER_ON
    from .date_options import build_compare_request

    request = options.get("request") or build_compare_request(
        mode=options.get("mode", "dates"),
        sensor=options.get("sensor", "optical"),
        window_days=int(options.get("window_days", WINDOW_DAYS)),
        later=later or options.get("later"),
        earlier=earlier or options.get("earlier"),
        earlier_start=options.get("earlier_start"),
        earlier_end=options.get("earlier_end"),
        later_start=options.get("later_start"),
        later_end=options.get("later_end"),
        acknowledge_partial=bool(options.get("acknowledge_partial", False)),
    )
    from .bankline_compare import DEFAULT_CLOSE_M as _CLOSE

    fingerprint = request.cache_key(close_m=_CLOSE, scale_m=SCALE_M, crs=ANALYSIS_CRS)
    with _LOCK:
        same = bool(_PROGRESS.get("running")) and _PROGRESS.get("fingerprint") == fingerprint
        if same:
            return True
        _TICKET += 1
        ticket = _TICKET
        _NEXT = (request, ticket)
        _PROGRESS.update(
            {
                "running": True,
                "done": False,
                "error": None,
                "change": None,
                "points": None,
                "step": "Base optical",
                "detail": "Starting",
                "ticket": ticket,
                "later": request.later.end.isoformat(),
                "earlier": request.earlier.end.isoformat(),
                "fingerprint": fingerprint,
                "request": request.as_dict(),
            }
        )
        launch = not _WORKER_ON
        _WORKER_ON = True
    if launch:
        threading.Thread(target=_compute_worker, daemon=True).start()
    return True
