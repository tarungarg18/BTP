"""Build and read the water-mask catalog used by the portal API.

Run: python -m processing.catalog
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from pyproj import Geod
from shapely.geometry import box, mapping

from .aoi import endpoints_lonlat
from .gee_init import gee_status
from .guide import CACHE as GUIDE_CACHE
from .guide import load_guide_lonlat
from .watermask import (
    DISPLAY_STRIDE,
    MIN_PATCH_HA,
    OPENING_RADIUS_M,
    RECOVERY_DISTANCE_M,
    change_masks,
    extract_river,
    load_mask_cache,
    parse_mask_filename,
    read_water,
    save_mask_cache,
    write_mask_png,
    EROSION_RGBA,
    DEPOSITION_RGBA,
    RIVER_RGBA,
)

ROOT = Path(__file__).resolve().parents[1]
MASK_DIR = ROOT / "drive-download-20261109T093459Z-1-001"
CATALOG_PATH = ROOT / "data" / "mask_catalog.json"
EXTRA_PATH = ROOT / "data" / "change_extra.json"
CACHE_DIR = ROOT / "data" / "mask_cache"
OVERLAY_DIR = ROOT / "data" / "overlays"
_LOCK = threading.Lock()
_GEOD = Geod(ellps="WGS84")


def mask_directory() -> Path:
    return MASK_DIR


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _area(count: int, pixel_km2: float) -> float:
    return round(count * pixel_km2, 2)


def fmt_area(km2: float | None) -> str | None:
    if km2 is None:
        return None
    magnitude = abs(km2)
    if magnitude >= 100:
        return f"{km2:.0f} km²"
    if magnitude >= 10:
        return f"{km2:.1f} km²"
    return f"{km2:.2f} km²"


def fmt_km(km: float | None) -> str | None:
    if km is None:
        return None
    if abs(km) >= 100:
        return f"{km:.0f} km"
    return f"{km:.1f} km"


def fmt_signed_area(km2: float | None) -> str | None:
    if km2 is None:
        return None
    text = fmt_area(abs(km2)) or ""
    if km2 > 0:
        return f"+{text}"
    if km2 < 0:
        return f"−{text}"
    return text


def discover_masks() -> list[dict]:
    if not MASK_DIR.exists():
        return []
    found = []
    for path in sorted(MASK_DIR.glob("*.tif")):
        parsed = parse_mask_filename(path.name)
        if parsed is None:
            continue
        parsed["path"] = str(path)
        parsed["filename"] = path.name
        found.append(parsed)
    found.sort(key=lambda item: item["sort"])
    return found


def _length_km(geometry) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    if geometry.geom_type == "MultiLineString":
        return sum(_length_km(part) for part in geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return sum(_length_km(part) for part in geometry.geoms)
    if geometry.geom_type != "LineString":
        return 0.0
    return _GEOD.geometry_length(geometry) / 1000.0


def _guide_feature() -> dict:
    line = load_guide_lonlat()
    return {
        "type": "Feature",
        "properties": {
            "role": "centreline_guide",
            "source": "Natural Earth 10m Brahmaputra, clipped Sadiya to Dhubri",
        },
        "geometry": mapping(line),
    }


def _overlap_km(footprint: dict | None) -> float | None:
    if not footprint:
        return None
    line = load_guide_lonlat()
    window = box(footprint["west"], footprint["south"], footprint["east"], footprint["north"])
    piece = line.intersection(window)
    if piece.is_empty:
        return 0.0
    return round(_length_km(piece), 1)


def _stem_km() -> float:
    return round(_length_km(load_guide_lonlat()), 1)


def _min_pixels(pixel_km2: float) -> int:
    pixel_m2 = pixel_km2 * 1_000_000.0
    return max(1, int(round((MIN_PATCH_HA * 10_000.0) / pixel_m2)))


def _overlay_name(mask_id: str, kind: str) -> str:
    return f"{mask_id}-{kind}.png"


def _change_name(later_id: str, earlier_id: str, kind: str) -> str:
    return f"{later_id}__{earlier_id}-{kind}.png"


def _public_overlay(name: str) -> str:
    return f"/api/overlays/{name}"


def build() -> Path:
    masks = discover_masks()
    if not masks:
        raise FileNotFoundError(f"No Brahmaputra_WaterMask GeoTIFFs in {MASK_DIR}")

    sample_water, _observed, grid = read_water(Path(masks[0]["path"]))
    del sample_water
    pixel_km2 = grid["pixel_km2"]
    pixel_m = (grid["pixel_width_m"] + grid["pixel_height_m"]) / 2.0
    min_pixels = _min_pixels(pixel_km2)
    print(
        f"grid {grid['width']}x{grid['height']} pixel {grid['pixel_width_m']:.1f}x{grid['pixel_height_m']:.1f} m",
        flush=True,
    )

    records = []
    previous = None
    changes = []
    for index, item in enumerate(masks, start=1):
        path = Path(item["path"])
        cache = CACHE_DIR / f"{item['id']}.npz"
        river_png = OVERLAY_DIR / _overlay_name(item["id"], "river")
        print(f"[{index}/{len(masks)}] {item['label']}", flush=True)
        if cache.exists() and river_png.exists():
            river, observed, observed_full = load_mask_cache(cache)
            print("  cache", flush=True)
        else:
            water, observed, _meta = read_water(path)
            observed_full = bool(observed.all())
            river = extract_river(water, pixel_m)
            del water
            save_mask_cache(cache, river, observed, observed_full)
            write_mask_png(river, RIVER_RGBA, river_png)
        water_km2 = _area(int(river.sum()), pixel_km2)
        observed_fraction = round(float(observed.mean()), 4)
        status = "processed" if int(river.sum()) >= 1000 else "failed_qc"
        record = {
            "id": item["id"],
            "year": item["year"],
            "season": item["season"],
            "season_label": item["season_label"],
            "copy_index": item["copy_index"],
            "label": item["label"],
            "short_label": item["short_label"],
            "filename": item["filename"],
            "water_km2": water_km2,
            "water_display": fmt_area(water_km2),
            "observed_fraction": observed_fraction,
            "river_pixels": int(river.sum()),
            "status": status,
            "validation_status": "not_field_validated",
            "source_id": "landsat",
            "river_png": _public_overlay(river_png.name),
            "bounds": grid["bounds"],
        }
        records.append(record)
        if previous is not None:
            changes.append(
                _pair_change(
                    previous[0],
                    previous[1],
                    previous[2],
                    record,
                    river,
                    observed,
                    pixel_km2,
                    min_pixels,
                    grid["bounds"],
                )
            )
        previous = (record, river, observed)
        del river, observed

    catalog = {
        "built_at": _now(),
        "mask_count": len(records),
        "grid": {
            "width": grid["width"],
            "height": grid["height"],
            "pixel_width_m": grid["pixel_width_m"],
            "pixel_height_m": grid["pixel_height_m"],
            "pixel_km2": pixel_km2,
            "bounds": grid["bounds"],
            "display_stride": DISPLAY_STRIDE,
        },
        "method": {
            "opening_radius_m": OPENING_RADIUS_M,
            "recovery_distance_m": RECOVERY_DISTANCE_M,
            "min_patch_ha": MIN_PATCH_HA,
            "min_patch_pixels": min_pixels,
            "water_value": 1,
            "nodata_value": 255,
            "reference": "Brahmaputra_River_Extraction.ipynb",
        },
        "masks": records,
        "changes": changes,
    }
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(json.dumps(catalog))
    print(f"wrote {CATALOG_PATH}", flush=True)
    return CATALOG_PATH


def _pair_change(
    earlier: dict,
    earlier_river,
    earlier_observed,
    later: dict,
    later_river,
    later_observed,
    pixel_km2: float,
    min_pixels: int,
    bounds: dict,
) -> dict:
    erosion, deposition, persistent = change_masks(
        earlier_river,
        later_river,
        earlier_observed,
        later_observed,
        min_pixels,
    )
    erosion_png = OVERLAY_DIR / _change_name(later["id"], earlier["id"], "erosion")
    deposition_png = OVERLAY_DIR / _change_name(later["id"], earlier["id"], "deposition")
    write_mask_png(erosion, EROSION_RGBA, erosion_png)
    write_mask_png(deposition, DEPOSITION_RGBA, deposition_png)
    erosion_km2 = _area(int(erosion.sum()), pixel_km2)
    deposition_km2 = _area(int(deposition.sum()), pixel_km2)
    persistent_km2 = _area(int(persistent.sum()), pixel_km2)
    net = round(later["water_km2"] - earlier["water_km2"], 2)
    print(
        f"  vs {earlier['short_label']}: erosion {erosion_km2} km2, deposition {deposition_km2} km2",
        flush=True,
    )
    return _change_record(
        earlier,
        later,
        erosion_km2,
        deposition_km2,
        persistent_km2,
        net,
        bounds,
        _public_overlay(erosion_png.name),
        _public_overlay(deposition_png.name),
    )


def _change_record(
    earlier: dict,
    later: dict,
    erosion_km2: float,
    deposition_km2: float,
    persistent_km2: float,
    net: float,
    bounds: dict,
    erosion_png: str,
    deposition_png: str,
) -> dict:
    return {
        "available": True,
        "earlier_id": earlier["id"],
        "later_id": later["id"],
        "earlier_label": earlier["label"],
        "later_label": later["label"],
        "earlier_short": earlier["short_label"],
        "later_short": later["short_label"],
        "erosion_km2": erosion_km2,
        "deposition_km2": deposition_km2,
        "persistent_km2": persistent_km2,
        "erosion_display": fmt_area(erosion_km2),
        "deposition_display": fmt_area(deposition_km2),
        "persistent_display": fmt_area(persistent_km2),
        "net_water_change_km2": net,
        "net_water_change_display": fmt_signed_area(net),
        "earlier_water_km2": earlier["water_km2"],
        "later_water_km2": later["water_km2"],
        "unit": "km²",
        "validation_status": "candidate_not_field_validated",
        "disclaimer": (
            "Candidate change only. New river water is corridor expansion and lost river "
            "water is corridor contraction. A higher or lower stage can look the same. Patches "
            f"smaller than {MIN_PATCH_HA:.0f} ha are omitted. Not a field survey."
        ),
        "erosion_png": erosion_png,
        "deposition_png": deposition_png,
        "bounds": bounds,
        "note": f"{later['label']} compared with {earlier['label']}.",
        "rows": [
            {
                "id": "erosion",
                "label": "Corridor expansion",
                "display": fmt_area(erosion_km2),
                "tone": "erosion",
                "detail": "Land on the earlier mask that is river on the later mask.",
            },
            {
                "id": "deposition",
                "label": "Corridor contraction",
                "display": fmt_area(deposition_km2),
                "tone": "deposition",
                "detail": "River on the earlier mask that is land on the later mask.",
            },
            {
                "id": "persistent",
                "label": "Persistent water",
                "display": fmt_area(persistent_km2),
                "tone": "stable",
                "detail": "River pixels present in both masks.",
            },
        ],
    }


def load_catalog() -> dict | None:
    if not CATALOG_PATH.exists():
        return None
    return json.loads(CATALOG_PATH.read_text())


def _season_name(label: str | None) -> str:
    text = label or ""
    for name in ("Pre-monsoon", "Post-monsoon", "Annual"):
        if name in text:
            return name
    return ""


def present_change(record: dict) -> dict:
    shown = dict(record)
    rows = []
    for row in shown.get("rows") or []:
        item = dict(row)
        if item.get("id") == "erosion":
            item["label"] = "Corridor expansion"
        elif item.get("id") == "deposition":
            item["label"] = "Corridor contraction"
        rows.append(item)
    shown["rows"] = rows
    disclaimer = str(shown.get("disclaimer") or "")
    disclaimer = disclaimer.replace(
        "New river water is mapped as erosion and lost river water as deposition.",
        "New river water is corridor expansion and lost river water is corridor contraction.",
    )
    shown["disclaimer"] = disclaimer
    earlier = _season_name(shown.get("earlier_label"))
    later = _season_name(shown.get("later_label"))
    if earlier and earlier != later:
        note = (
            " These two masks are different seasons, so a large share of the area can be "
            "water level rather than a bank that moved."
        )
        disclaimer = str(shown.get("disclaimer") or "")
        if note.strip() not in disclaimer:
            shown["disclaimer"] = disclaimer + note
    return shown


def list_masks() -> list[dict]:
    catalog = load_catalog()
    if not catalog:
        return []
    return catalog["masks"]


def list_step_changes() -> list[dict]:
    catalog = load_catalog()
    if not catalog:
        return []
    return [present_change(item) for item in catalog["changes"]]


def _empty_change(note: str) -> dict:
    return {
        "available": False,
        "earlier_id": None,
        "later_id": None,
        "earlier_label": None,
        "later_label": None,
        "earlier_short": None,
        "later_short": None,
        "erosion_km2": None,
        "deposition_km2": None,
        "persistent_km2": None,
        "erosion_display": None,
        "deposition_display": None,
        "persistent_display": None,
        "net_water_change_km2": None,
        "net_water_change_display": None,
        "earlier_water_km2": None,
        "later_water_km2": None,
        "unit": "km²",
        "validation_status": "unavailable",
        "disclaimer": (
            "No mask pair is available to difference. Erosion and deposition are not shown."
        ),
        "erosion_png": None,
        "deposition_png": None,
        "bounds": None,
        "note": note,
        "rows": [],
    }


def _find_pair(later_id: str, earlier_id: str) -> dict | None:
    catalog = load_catalog() or {}
    for item in catalog.get("changes", []):
        if item["later_id"] == later_id and item["earlier_id"] == earlier_id:
            return item
    if EXTRA_PATH.exists():
        extra = json.loads(EXTRA_PATH.read_text())
        for item in extra:
            if item["later_id"] == later_id and item["earlier_id"] == earlier_id:
                return item
    return None


def get_change(later_id: str, earlier_id: str | None) -> dict:
    catalog = load_catalog()
    if not catalog:
        raise FileNotFoundError("Water-mask catalog has not been built.")
    by_id = {item["id"]: item for item in catalog["masks"]}
    if later_id not in by_id:
        raise KeyError(f"Unknown mask {later_id}")
    ordered = catalog["masks"]
    if earlier_id is None:
        index = next(i for i, item in enumerate(ordered) if item["id"] == later_id)
        if index == 0:
            return _empty_change(f"{by_id[later_id]['label']} is the earliest mask. There is no previous mask.")
        earlier_id = ordered[index - 1]["id"]
    if earlier_id not in by_id:
        raise KeyError(f"Unknown mask {earlier_id}")
    if earlier_id == later_id:
        raise ValueError("Choose two different masks.")
    cached = _find_pair(later_id, earlier_id)
    if cached:
        return present_change(cached)
    return present_change(_compute_pair(catalog, by_id[earlier_id], by_id[later_id]))


def _compute_pair(catalog: dict, earlier: dict, later: dict) -> dict:
    earlier_river, earlier_observed, _full_a = load_mask_cache(CACHE_DIR / f"{earlier['id']}.npz")
    later_river, later_observed, _full_b = load_mask_cache(CACHE_DIR / f"{later['id']}.npz")
    pixel_km2 = catalog["grid"]["pixel_km2"]
    min_pixels = catalog["method"]["min_patch_pixels"]
    record = _pair_change(
        earlier,
        earlier_river,
        earlier_observed,
        later,
        later_river,
        later_observed,
        pixel_km2,
        min_pixels,
        catalog["grid"]["bounds"],
    )
    with _LOCK:
        extra = json.loads(EXTRA_PATH.read_text()) if EXTRA_PATH.exists() else []
        extra = [item for item in extra if not (item["later_id"] == later["id"] and item["earlier_id"] == earlier["id"])]
        extra.append(record)
        EXTRA_PATH.write_text(json.dumps(extra))
    return record


def _source_rows(catalog: dict | None, gee: dict) -> list[dict]:
    mask_count = 0 if catalog is None else catalog["mask_count"]
    latest = None if not catalog or not catalog["masks"] else catalog["masks"][-1]["label"]
    sentinel_detail = (
        "No scene is ingested. New Sentinel acquisitions are not connected, so this source is not a live feed."
        if not gee.get("available")
        else "Earth Engine is logged in, but this catalog has no Sentinel scene yet. This is not a live feed."
    )
    landsat_detail = (
        f"{mask_count} binary water-mask GeoTIFFs loaded. Pixel value 1 is water and 255 is nodata. "
        "Season is taken from the file name (pre-monsoon, post-monsoon, or annual), not from an acquisition clock."
        if mask_count
        else "No water-mask catalog is loaded. Sentinel is also empty, so there is nothing new to acquire from here."
    )
    return [
        {
            "id": "sentinel-1",
            "name": "Sentinel-1",
            "kind": "SAR (VV)",
            "status": "no_acquisition",
            "status_label": "No acquisition",
            "scene_count": 0,
            "latest_label": None,
            "detail": sentinel_detail,
            "validation_status": "not_available",
        },
        {
            "id": "sentinel-2",
            "name": "Sentinel-2",
            "kind": "Optical (MNDWI)",
            "status": "no_acquisition",
            "status_label": "No acquisition",
            "scene_count": 0,
            "latest_label": None,
            "detail": sentinel_detail,
            "validation_status": "not_available",
        },
        {
            "id": "landsat",
            "name": "Landsat",
            "kind": "Optical water mask",
            "status": "processed" if mask_count else "no_acquisition",
            "status_label": "Masks processed" if mask_count else "No catalog",
            "scene_count": mask_count,
            "latest_label": latest,
            "detail": landsat_detail,
            "validation_status": "not_field_validated" if mask_count else "not_available",
        },
    ]


def _cadence(catalog: dict | None) -> tuple[str, str]:
    if not catalog or not catalog["masks"]:
        return "No interval", "No dated mask is loaded, so a revisit interval is not reported."
    years = [item["year"] for item in catalog["masks"]]
    seasons = sorted({item["season_label"] for item in catalog["masks"]})
    return (
        "Seasonal",
        f"{catalog['mask_count']} masks, {min(years)}–{max(years)}. Labels: {', '.join(seasons)}. Not a 13-day live revisit.",
    )


def portal_summary() -> dict:
    gee = gee_status()
    catalog = load_catalog()
    files_on_disk = len(discover_masks())
    stem_km = _stem_km()
    footprint = None if catalog is None else catalog["grid"]["bounds"]
    overlap = _overlap_km(footprint)
    sources = _source_rows(catalog, gee)
    loaded = sum(1 for source in sources if source["scene_count"] > 0)
    cadence_value, cadence_detail = _cadence(catalog)
    latest = None if not catalog or not catalog["masks"] else catalog["masks"][-1]
    recent = present_change(catalog["changes"][-1]) if catalog and catalog.get("changes") else _empty_change(
        "Build the water-mask catalog to compare the latest mask with the previous one."
        if files_on_disk
        else "No water-mask GeoTIFF was found."
    )
    if catalog and files_on_disk:
        badge = "Historical catalog · no new acquisition"
        live = False
    elif files_on_disk:
        badge = "Masks on disk · catalog not built"
        live = False
    else:
        badge = "No acquisition available"
        live = False

    source_detail = (
        f"{loaded} of {len(sources)} sources have data. "
        + " · ".join(f"{source['name']}: {source['status_label']}" for source in sources)
    )
    return {
        "portal": {
            "title": "Brahmaputra Bank Change Portal",
            "subtitle": "River mask monitoring for the Assam main stem",
            "status_badge": badge,
            "live": live,
        },
        "hero": {
            "eyebrow": "Assam · Sadiya to Dhubri",
            "title": "Track the river.",
            "accent": "Understand every change.",
            "lede": (
                "Corridor geometry and bankline movement for the Assam Brahmaputra, "
                "measured from the stored water masks. Sentinel-1 and Sentinel-2 are listed "
                "separately and have no ingested scene."
            ),
        },
        "features": [
            {
                "icon": "satellite",
                "title": "Multi-sensor observations",
                "detail": f"Sentinel-1 SAR · Sentinel-2 optical · Landsat · {loaded} loaded",
            },
            {
                "icon": "layers",
                "title": "Corridor geometry",
                "detail": "Extracted river, centreline, 300 m sections",
            },
            {
                "icon": "split",
                "title": "Bank-change analysis",
                "detail": "Corridor expansion and contraction for any date pair",
            },
            {
                "icon": "clock",
                "title": "Observation timeline",
                "detail": cadence_detail,
            },
        ],
        "highlights": [
            {
                "id": "sources",
                "display": str(len(sources)),
                "label": "Satellite sources",
                "detail": source_detail,
            },
            {
                "id": "interval",
                "display": cadence_value,
                "label": "Mask cadence",
                "detail": cadence_detail,
            },
            {
                "id": "length",
                "display": fmt_km(stem_km) or "—",
                "label": "Main stem",
                "detail": "Geodesic length of the Natural Earth Brahmaputra centreline from Sadiya to Dhubri.",
            },
            {
                "id": "reach",
                "display": "300 m",
                "label": "Section interval",
                "detail": (
                    f"Fixed sections along the centreline. Masks cover {fmt_km(overlap)} of that line."
                    if overlap is not None
                    else "Fixed sections along the centreline."
                ),
            },
            {
                "id": "freshness",
                "display": "Historical" if catalog else "No feed",
                "label": "Acquisition status",
                "detail": (
                    "No new scene is available. Measurements are from the stored masks, not a live service."
                    if catalog
                    else "The portal has no processed acquisition to show yet."
                ),
            },
        ],
        "study_area": {
            "coverage": "Assam main-stem Brahmaputra",
            "extent": "Sadiya – Dhubri",
            "length_km": stem_km,
            "length_display": fmt_km(stem_km),
            "crs": "Centreline and masks in WGS 84. Areas use a local geodesic pixel size.",
            "mask_coverage": (
                "Water masks cover only their GeoTIFF footprint, not the whole stem to Sadiya."
                if footprint
                else "Water-mask footprint is not loaded."
            ),
            "mask_length_km": overlap,
            "mask_length_display": fmt_km(overlap) if overlap is not None else None,
            "endpoints": endpoints_lonlat(),
            "centerline": _guide_feature() if GUIDE_CACHE.exists() else _guide_feature(),
            "footprint": footprint,
        },
        "sources": sources,
        "latest_observation": _latest_observation(latest),
        "recent_change": recent,
        "method_steps": [
            {
                "title": "Read the mask",
                "short": "Value 1 is water",
                "detail": "GeoTIFF value 1 is water. Value 255 is nodata and is left out of both the river and the comparison.",
            },
            {
                "title": "Extract the river",
                "short": "Opening and braids",
                "detail": f"Morphological opening at {OPENING_RADIUS_M:.0f} m, then the largest component, then braids within {RECOVERY_DISTANCE_M:.0f} m.",
            },
            {
                "title": "Keep the season",
                "short": "Year and pre/post",
                "detail": "Each file is one year and a season: pre-monsoon, post-monsoon, or an annual mask. There is no day-of-year in the file name.",
            },
            {
                "title": "Compare dates",
                "short": "Later minus earlier",
                "detail": "Inside the shared observed area, new river is corridor expansion and lost river is corridor contraction. Bank-normal shift is measured on 300 m sections, outward positive.",
            },
            {
                "title": "Drop speckle",
                "short": f"Under {MIN_PATCH_HA:.0f} ha removed",
                "detail": f"Change patches smaller than {MIN_PATCH_HA:.0f} ha are removed. River area itself is not filtered that way.",
            },
            {
                "title": "Show the map",
                "short": "Mask on imagery",
                "detail": "The blue fill is the extracted mask. The centreline is only a guide from Sadiya to Dhubri, not a surveyed bank.",
            },
        ],
        "method": None
        if catalog is None
        else catalog["method"],
        "disclaimer": (
            "Candidate satellite change only. Water level and season can imitate bank retreat or accretion. "
            "Corridor expansion and contraction are area differences, not surveyed bank movement. "
            "Not field-validated and not a warning product."
        ),
        "year_min": None if not catalog or not catalog["masks"] else catalog["masks"][0]["year"],
        "year_max": None if not catalog or not catalog["masks"] else catalog["masks"][-1]["year"],
        "mask_count": 0 if catalog is None else catalog["mask_count"],
        "files_on_disk": files_on_disk,
        "catalog_built_at": None if catalog is None else catalog["built_at"],
        "gee": {"available": bool(gee.get("available")), "reason": gee.get("reason", "")},
    }


def _latest_observation(latest: dict | None) -> dict:
    if latest is None:
        return {
            "available": False,
            "mask_id": None,
            "date_label": None,
            "sensor": None,
            "status_label": "No acquisition",
            "validation_status": "No processed mask",
            "water_display": None,
            "river_png": None,
            "bounds": None,
            "note": "There is no processed water mask to show as the latest observation.",
        }
    return {
        "available": True,
        "mask_id": latest["id"],
        "date_label": latest["label"],
        "sensor": "Landsat water mask",
        "status_label": "Processed" if latest["status"] == "processed" else "Failed QC",
        "validation_status": "Not field-validated",
        "water_display": latest["water_display"],
        "river_png": latest["river_png"],
        "bounds": latest["bounds"],
        "note": "The date is the file’s year and season, not a calendar acquisition day.",
    }


def main() -> None:
    build()


if __name__ == "__main__":
    main()
