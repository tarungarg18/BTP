"""Identify a map click and measure corridor width on the stored water masks.

Chainage follows the Natural Earth Brahmaputra centreline from Sadiya toward Dhubri.
Widths are read from the extracted river masks. Nothing here is a placeholder value.
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
from pyproj import Geod
from shapely.geometry import Point, box

from .catalog import CACHE_DIR, CATALOG_PATH, fmt_area, get_change, load_catalog
from .crs import load_crs, to_lonlat, to_metres
from .guide import load_guide_lonlat
from .watermask import change_masks, load_mask_cache

SECTION_M = 300.0
REACH_M = 5_000.0
SEARCH_M = 12_000.0
TRANSECT_M = 12_000.0
TOLERANCE_M = 60.0
PROFILE_DIR = Path(__file__).resolve().parents[1] / "data" / "profiles"
PATCH_DIR = Path(__file__).resolve().parents[1] / "data" / "patches"
AXIS_DIR = Path(__file__).resolve().parents[1] / "data" / "centerlines"
PATCH_LIMIT = 25
_GEOD = Geod(ellps="WGS84")
_LOCK = threading.Lock()
_PAIR: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}


def _grid() -> dict:
    catalog = load_catalog()
    if not catalog:
        raise FileNotFoundError("Water-mask catalog has not been built.")
    return catalog["grid"]


def _pixel_rc(lon: float, lat: float, grid: dict) -> tuple[float, float]:
    bounds = grid["bounds"]
    col = (lon - bounds["west"]) / ((bounds["east"] - bounds["west"]) / grid["width"])
    row = (bounds["north"] - lat) / ((bounds["north"] - bounds["south"]) / grid["height"])
    return row, col


def _lonlat(row: float, col: float, grid: dict) -> tuple[float, float]:
    bounds = grid["bounds"]
    lon = bounds["west"] + col * ((bounds["east"] - bounds["west"]) / grid["width"])
    lat = bounds["north"] - row * ((bounds["north"] - bounds["south"]) / grid["height"])
    return lon, lat


def mask_centerline(mask_id: str) -> dict | None:
    """One line through the middle of this mask's water. Not the Natural Earth guide."""
    AXIS_DIR.mkdir(parents=True, exist_ok=True)
    path = AXIS_DIR / f"{mask_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    npz = CACHE_DIR / f"{mask_id}.npz"
    if not npz.exists():
        return None
    river, _observed, _full = load_mask_cache(npz)
    feature = _axis_feature(river, _grid(), mask_id)
    path.write_text(json.dumps(feature), encoding="utf-8")
    return feature


def _axis_feature(river: np.ndarray, grid: dict, mask_id: str) -> dict:
    stride = 4
    cols = np.arange(0, river.shape[1], stride)
    rows = np.full(cols.size, np.nan)
    for index, col in enumerate(cols):
        hit = np.flatnonzero(river[:, int(col)])
        if hit.size >= 4:
            rows[index] = float(np.median(hit))
    smooth = rows.copy()
    for index in range(rows.size):
        window = rows[max(0, index - 4) : index + 5]
        good = window[np.isfinite(window)]
        if good.size >= 3:
            smooth[index] = float(np.median(good))
    lines: list[list[list[float]]] = []
    run: list[list[float]] = []
    previous: float | None = None
    for index, col in enumerate(cols):
        guess = smooth[index]
        hit = np.flatnonzero(river[:, int(col)])
        if not np.isfinite(guess) or hit.size == 0:
            if len(run) >= 4:
                lines.append(run)
            run = []
            previous = None
            continue
        nearest = float(hit[int(np.argmin(np.abs(hit.astype(float) - float(guess))))])
        if abs(nearest - float(guess)) > 8 or (previous is not None and abs(nearest - previous) > 30):
            if len(run) >= 4:
                lines.append(run)
            run = []
            if abs(nearest - float(guess)) > 8:
                previous = None
                continue
        lon, lat = _lonlat(nearest + 0.5, float(col) + 0.5, grid)
        run.append([round(lon, 5), round(lat, 5)])
        previous = nearest
    if len(run) >= 4:
        lines.append(run)
    return {
        "type": "Feature",
        "properties": {"role": "mask_centerline", "mask_id": mask_id},
        "geometry": {"type": "MultiLineString", "coordinates": lines} if lines else None,
    }


def _inside(lon: float, lat: float, grid: dict) -> bool:
    bounds = grid["bounds"]
    return bounds["west"] <= lon <= bounds["east"] and bounds["south"] <= lat <= bounds["north"]


@lru_cache(maxsize=1)
def reference_sections() -> tuple[dict, ...]:
    catalog = load_catalog()
    if not catalog:
        return ()
    grid = catalog["grid"]
    bundle = load_crs()
    line_m = to_metres(load_guide_lonlat(), bundle)
    footprint = box(
        grid["bounds"]["west"],
        grid["bounds"]["south"],
        grid["bounds"]["east"],
        grid["bounds"]["north"],
    )
    sections: list[dict] = []
    distance = 0.0
    length = line_m.length
    while distance <= length:
        point = line_m.interpolate(distance)
        ahead = line_m.interpolate(min(distance + 80.0, length))
        lon, lat = to_lonlat(Point(point.x, point.y), bundle).coords[0]
        if footprint.covers(Point(lon, lat)):
            tx, ty = ahead.x - point.x, ahead.y - point.y
            norm = float(np.hypot(tx, ty)) or 1.0
            sections.append(
                {
                    "section_id": f"S{int(round(distance / SECTION_M)):04d}",
                    "reach_id": f"R{int(distance // REACH_M) + 1:03d}",
                    "chainage_m": round(distance, 1),
                    "lon": round(lon, 6),
                    "lat": round(lat, 6),
                    "x": point.x,
                    "y": point.y,
                    "nx": -ty / norm,
                    "ny": tx / norm,
                }
            )
        distance += SECTION_M
    return tuple(sections)


def _load_pair(
    earlier_id: str, later_id: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    key = f"{later_id}__{earlier_id}"
    with _LOCK:
        cached = _PAIR.get(key)
        if cached is not None:
            return cached
        earlier, earlier_obs, _full_a = load_mask_cache(CACHE_DIR / f"{earlier_id}.npz")
        later, later_obs, _full_b = load_mask_cache(CACHE_DIR / f"{later_id}.npz")
        catalog = load_catalog() or {}
        min_pixels = int((catalog.get("method") or {}).get("min_patch_pixels") or 1)
        erosion, deposition, _persistent = change_masks(earlier, later, earlier_obs, later_obs, min_pixels)
        _PAIR.clear()
        _PAIR[key] = (earlier, earlier_obs, later, later_obs, erosion, deposition)
        return _PAIR[key]


def _ray(section: dict, grid: dict, metres: float = 200.0) -> tuple[float, float, float, float, float]:
    bundle = load_crs()
    lon2, lat2 = to_lonlat(Point(section["x"] + section["nx"] * metres, section["y"] + section["ny"] * metres), bundle).coords[0]
    row0, col0 = _pixel_rc(section["lon"], section["lat"], grid)
    row1, col1 = _pixel_rc(lon2, lat2, grid)
    dr, dc = row1 - row0, col1 - col0
    step_px = float(np.hypot(dr, dc)) or 1.0
    return row0, col0, dr / step_px, dc / step_px, metres / step_px


def _outer(mask: np.ndarray, row0: float, col0: float, dr: float, dc: float, sign: int, metres_per_px: float) -> int | None:
    steps = int(TRANSECT_M / metres_per_px)
    index = np.arange(0, steps + 1)
    rows = np.rint(row0 + sign * dr * index).astype(np.int32)
    cols = np.rint(col0 + sign * dc * index).astype(np.int32)
    valid = (rows >= 0) & (rows < mask.shape[0]) & (cols >= 0) & (cols < mask.shape[1])
    if not valid.all():
        cut = int(np.argmax(~valid))
        if cut == 0:
            return None
        rows, cols, index = rows[:cut], cols[:cut], index[:cut]
    water = mask[rows, cols]
    if not bool(water.any()):
        return None
    return int(index[water][-1])


def _measure(mask: np.ndarray, section: dict, grid: dict) -> dict:
    row0, col0, dr, dc, metres_per_px = _ray(section, grid)
    left = _outer(mask, row0, col0, dr, dc, 1, metres_per_px)
    right = _outer(mask, row0, col0, dr, dc, -1, metres_per_px)
    if left is None or right is None:
        return {"width_m": None, "left_m": None, "right_m": None, "left_ll": None, "right_ll": None, "qc": "missing_intersection"}
    left_m = round(left * metres_per_px, 1)
    right_m = round(right * metres_per_px, 1)
    left_lon, left_lat = _lonlat(row0 + dr * left, col0 + dc * left, grid)
    right_lon, right_lat = _lonlat(row0 - dr * right, col0 - dc * right, grid)
    return {
        "width_m": round(left_m + right_m, 1),
        "left_m": left_m,
        "right_m": right_m,
        "left_ll": (round(left_lon, 6), round(left_lat, 6)),
        "right_ll": (round(right_lon, 6), round(right_lat, 6)),
        "qc": "ok",
    }


def _class(delta: float | None) -> str:
    if delta is None:
        return "unavailable"
    if delta > TOLERANCE_M:
        return "candidate_retreat"
    if delta < -TOLERANCE_M:
        return "candidate_accretion"
    return "stable"


def _class_label(name: str) -> str:
    return {
        "candidate_retreat": "Candidate bank retreat",
        "candidate_accretion": "Candidate accretion",
        "stable": "Stable",
        "unavailable": "Unavailable",
    }.get(name, name)


def _nearest(lon: float, lat: float) -> tuple[dict | None, float | None]:
    best: dict | None = None
    best_m = 1e18
    for section in reference_sections():
        _az12, _az21, dist = _GEOD.inv(lon, lat, section["lon"], section["lat"])
        if dist < best_m:
            best_m = dist
            best = section
    if best is None or best_m > SEARCH_M:
        return None, None if best is None else best_m
    return best, best_m


def _pixel_class(row: int, col: int, earlier: np.ndarray, earlier_obs: np.ndarray, later: np.ndarray, later_obs: np.ndarray) -> str:
    if not (0 <= row < later.shape[0] and 0 <= col < later.shape[1]):
        return "outside"
    if not (bool(earlier_obs[row, col]) and bool(later_obs[row, col])):
        return "nodata"
    was = bool(earlier[row, col])
    now = bool(later[row, col])
    if now and not was:
        return "corridor_expansion"
    if was and not now:
        return "corridor_contraction"
    if now and was:
        return "persistent_water"
    return "land"


def _zone(mask: np.ndarray, row: int, col: int, grid: dict, change_class: str, earlier_label: str, later_label: str) -> dict:
    from scipy import ndimage as ndi

    labels, _count = ndi.label(mask)
    label = int(labels[row, col])
    rows, cols = np.nonzero(labels == label)
    area = round(int(rows.size) * grid["pixel_km2"], 2)
    crow, ccol = float(rows.mean()), float(cols.mean())
    lon, lat = _lonlat(crow, ccol, grid)
    return {
        "change_class": change_class,
        "area_km2": area,
        "area_display": fmt_area(area),
        "centroid_lat": round(lat, 5),
        "centroid_lon": round(lon, 5),
        "earlier_label": earlier_label,
        "later_label": later_label,
    }


def identify(lon: float, lat: float, later_id: str, earlier_id: str | None) -> dict:
    catalog = load_catalog()
    if not catalog:
        raise FileNotFoundError("Water-mask catalog has not been built.")
    by_id = {item["id"]: item for item in catalog["masks"]}
    if later_id not in by_id:
        raise KeyError(later_id)
    if earlier_id is None:
        ordered = catalog["masks"]
        index = next(i for i, item in enumerate(ordered) if item["id"] == later_id)
        if index == 0:
            earlier_id = later_id
        else:
            earlier_id = ordered[index - 1]["id"]
    if earlier_id not in by_id:
        raise KeyError(earlier_id)
    grid = catalog["grid"]
    inside = _inside(lon, lat, grid)
    earlier_name = by_id[earlier_id]["label"]
    later_name = by_id[later_id]["label"]
    section, distance_m = _nearest(lon, lat)
    pixel_name = "outside"
    zone = None
    measured = None
    if inside and earlier_id != later_id:
        river_a, _obs_a, river_b, _obs_b, erosion, deposition = _load_pair(earlier_id, later_id)
        row_f, col_f = _pixel_rc(lon, lat, grid)
        row, col = int(round(row_f)), int(round(col_f))
        if 0 <= row < erosion.shape[0] and 0 <= col < erosion.shape[1]:
            if bool(erosion[row, col]):
                pixel_name = "corridor_expansion"
                zone = _zone(erosion, row, col, grid, "Corridor expansion", earlier_name, later_name)
            elif bool(deposition[row, col]):
                pixel_name = "corridor_contraction"
                zone = _zone(deposition, row, col, grid, "Corridor contraction", earlier_name, later_name)
            elif bool(river_a[row, col]) and bool(river_b[row, col]):
                pixel_name = "persistent_water"
            elif not bool(river_a[row, col]) and not bool(river_b[row, col]):
                pixel_name = "land"
            else:
                pixel_name = "land"
        if section is not None:
            before = _measure(river_a, section, grid)
            after = _measure(river_b, section, grid)
            left_delta = None if before["left_m"] is None or after["left_m"] is None else round(after["left_m"] - before["left_m"], 1)
            right_delta = None if before["right_m"] is None or after["right_m"] is None else round(after["right_m"] - before["right_m"], 1)
            left_name = _class(left_delta)
            right_name = _class(right_delta)
            measured = {
                "section_id": section["section_id"],
                "reach_id": section["reach_id"],
                "chainage_m": section["chainage_m"],
                "chainage_display": f"{section['chainage_m'] / 1000:.1f} km from Sadiya",
                "distance_m": round(distance_m or 0, 0),
                "width_earlier_m": before["width_m"],
                "width_later_m": after["width_m"],
                "left_delta_m": left_delta,
                "right_delta_m": right_delta,
                "left_class": left_name,
                "right_class": right_name,
                "left_label": _class_label(left_name),
                "right_label": _class_label(right_name),
                "qc": "ok" if before["qc"] == "ok" and after["qc"] == "ok" else "missing_intersection",
                "lon": section["lon"],
                "lat": section["lat"],
            }
    pixel_labels = {
        "corridor_expansion": "Corridor expansion",
        "corridor_contraction": "Corridor contraction",
        "persistent_water": "River in both masks",
        "land": "Land in both masks",
        "nodata": "No observation at this pixel",
        "outside": "Outside the water-mask footprint",
    }
    if section is None:
        message = "No nearby measurement section."
    elif measured and measured["qc"] != "ok":
        message = "Section found. Width is unavailable because the mask does not cross both banks."
    else:
        message = "Section measured on the stored masks."
    if not inside:
        message = "This point is outside the water-mask footprint."
    return {
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "inside_footprint": inside,
        "message": message,
        "pixel_class": pixel_name,
        "pixel_label": pixel_labels.get(pixel_name, pixel_name),
        "earlier_label": earlier_name,
        "later_label": later_name,
        "section": measured,
        "zone": zone,
    }


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def build_profile(later_id: str, earlier_id: str) -> dict:
    catalog = load_catalog()
    if not catalog:
        raise FileNotFoundError("Water-mask catalog has not been built.")
    by_id = {item["id"]: item for item in catalog["masks"]}
    if later_id not in by_id or earlier_id not in by_id:
        raise KeyError("Unknown mask")
    cache = PROFILE_DIR / f"{later_id}__{earlier_id}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    grid = catalog["grid"]
    river_a, _obs_a, river_b, _obs_b, _erosion, _deposition = _load_pair(earlier_id, later_id)
    sections = []
    for section in reference_sections():
        before = _measure(river_a, section, grid)
        after = _measure(river_b, section, grid)
        left_delta = None if before["left_m"] is None or after["left_m"] is None else round(after["left_m"] - before["left_m"], 1)
        right_delta = None if before["right_m"] is None or after["right_m"] is None else round(after["right_m"] - before["right_m"], 1)
        left_ll = after["left_ll"] or before["left_ll"]
        right_ll = after["right_ll"] or before["right_ll"]
        sections.append(
            {
                "section_id": section["section_id"],
                "reach_id": section["reach_id"],
                "chainage_m": section["chainage_m"],
                "lon": section["lon"],
                "lat": section["lat"],
                "width_earlier_m": before["width_m"],
                "width_later_m": after["width_m"],
                "left_delta_m": left_delta,
                "right_delta_m": right_delta,
                "qc": "ok" if before["qc"] == "ok" and after["qc"] == "ok" else "missing_intersection",
                "left_lon": None if left_ll is None else left_ll[0],
                "left_lat": None if left_ll is None else left_ll[1],
                "right_lon": None if right_ll is None else right_ll[0],
                "right_lat": None if right_ll is None else right_ll[1],
            }
        )
    grouped: dict[str, list[dict]] = {}
    for row in sections:
        grouped.setdefault(row["reach_id"], []).append(row)
    reaches = []
    for reach_id, rows in grouped.items():
        valid = [row for row in rows if row["qc"] == "ok"]
        retreats = [value for row in valid for value in (row["left_delta_m"], row["right_delta_m"]) if value is not None and value > 0]
        mid = rows[len(rows) // 2]
        reaches.append(
            {
                "reach_id": reach_id,
                "chainage_start_m": rows[0]["chainage_m"],
                "chainage_end_m": rows[-1]["chainage_m"],
                "n_sections": len(rows),
                "n_valid": len(valid),
                "mean_width_earlier_m": _avg([row["width_earlier_m"] for row in valid if row["width_earlier_m"] is not None]),
                "mean_width_later_m": _avg([row["width_later_m"] for row in valid if row["width_later_m"] is not None]),
                "mean_left_delta_m": _avg([row["left_delta_m"] for row in valid if row["left_delta_m"] is not None]),
                "mean_right_delta_m": _avg([row["right_delta_m"] for row in valid if row["right_delta_m"] is not None]),
                "max_retreat_m": None if not retreats else round(max(retreats), 1),
                "lon": mid["lon"],
                "lat": mid["lat"],
            }
        )
    valid_rows = [row for row in sections if row["qc"] == "ok"]
    retreats = [value for row in valid_rows for value in (row["left_delta_m"], row["right_delta_m"]) if value is not None and value > TOLERANCE_M]
    profile = {
        "earlier_id": earlier_id,
        "later_id": later_id,
        "earlier_label": by_id[earlier_id]["label"],
        "later_label": by_id[later_id]["label"],
        "section_step_m": SECTION_M,
        "reach_step_m": REACH_M,
        "tolerance_m": TOLERANCE_M,
        "n_sections": len(sections),
        "n_valid": len(valid_rows),
        "mean_width_earlier_m": _avg([row["width_earlier_m"] for row in valid_rows if row["width_earlier_m"] is not None]),
        "mean_width_later_m": _avg([row["width_later_m"] for row in valid_rows if row["width_later_m"] is not None]),
        "max_retreat_m": None if not retreats else round(max(retreats), 1),
        "sections": sections,
        "reaches": reaches,
    }
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(profile))
    return profile


def profile_csv(later_id: str, earlier_id: str) -> str:
    profile = build_profile(later_id, earlier_id)
    header = "section_id,reach_id,chainage_m,lon,lat,width_earlier_m,width_later_m,left_delta_m,right_delta_m,qc"
    lines = [header]
    for row in profile["sections"]:
        lines.append(
            ",".join(
                str(row[key] if row[key] is not None else "")
                for key in (
                    "section_id",
                    "reach_id",
                    "chainage_m",
                    "lon",
                    "lat",
                    "width_earlier_m",
                    "width_later_m",
                    "left_delta_m",
                    "right_delta_m",
                    "qc",
                )
            )
        )
    return "\n".join(lines) + "\n"


def mask_path(mask_id: str) -> Path:
    catalog = load_catalog()
    if not catalog:
        raise FileNotFoundError("Water-mask catalog has not been built.")
    match = next((item for item in catalog["masks"] if item["id"] == mask_id), None)
    if match is None:
        raise KeyError(mask_id)
    folder = Path(CATALOG_PATH).parents[1] / "drive-download-20261109T093459Z-1-001"
    path = folder / match["filename"]
    if not path.is_file():
        raise FileNotFoundError(match["filename"])
    return path


def _ranked_patches(mask: np.ndarray, grid: dict) -> tuple[list[dict], int]:
    from scipy import ndimage as ndi

    labels, count = ndi.label(mask)
    if count == 0:
        return [], 0
    counts = np.bincount(labels.ravel())
    order = np.argsort(counts[1:])[::-1] + 1
    slices = ndi.find_objects(labels)
    pixel_km2 = float(grid["pixel_km2"])
    rows: list[dict] = []
    for rank, label in enumerate(order[:PATCH_LIMIT], start=1):
        window = slices[int(label) - 1]
        if window is None:
            continue
        selected = labels[window] == label
        local_rows, local_cols = np.nonzero(selected)
        nearest = int(np.argmin((local_rows - local_rows.mean()) ** 2 + (local_cols - local_cols.mean()) ** 2))
        crow = float(local_rows[nearest] + window[0].start)
        ccol = float(local_cols[nearest] + window[1].start)
        lon, lat = _lonlat(crow + 0.5, ccol + 0.5, grid)
        area = round(int(counts[int(label)]) * pixel_km2, 2)
        rows.append(
            {
                "rank": rank,
                "area_km2": area,
                "area_display": fmt_area(area),
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
            }
        )
    return rows, int(count)


def change_points(later_id: str, earlier_id: str) -> dict:
    catalog = load_catalog()
    if not catalog:
        raise FileNotFoundError("Water-mask catalog has not been built.")
    by_id = {item["id"]: item for item in catalog["masks"]}
    if later_id not in by_id or earlier_id not in by_id:
        raise KeyError("Unknown mask")
    PATCH_DIR.mkdir(parents=True, exist_ok=True)
    cache = PATCH_DIR / f"{later_id}__{earlier_id}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    _earlier, _earlier_obs, _later, _later_obs, erosion, deposition = _load_pair(earlier_id, later_id)
    grid = catalog["grid"]
    erosion_rows, erosion_count = _ranked_patches(erosion, grid)
    deposition_rows, deposition_count = _ranked_patches(deposition, grid)
    payload = {
        "later_id": later_id,
        "earlier_id": earlier_id,
        "later_label": by_id[later_id]["label"],
        "earlier_label": by_id[earlier_id]["label"],
        "shown": PATCH_LIMIT,
        "erosion_count": erosion_count,
        "deposition_count": deposition_count,
        "erosion": erosion_rows,
        "deposition": deposition_rows,
    }
    cache.write_text(json.dumps(payload))
    return payload


def comparison_ready(later_id: str, earlier_id: str) -> dict:
    """Ensure the pair exists, then return its change record. Used by the map compare action."""
    if not CATALOG_PATH.exists():
        raise FileNotFoundError("Water-mask catalog has not been built.")
    return get_change(later_id, earlier_id)
