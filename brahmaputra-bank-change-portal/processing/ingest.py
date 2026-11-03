"""Build the portal store from real satellite water — not a drawn corridor."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import mapping

from .aoi import DOWNSTREAM_NAME, UPSTREAM_NAME, endpoints_lonlat
from .change import compare_epochs
from .crs import distortion_report, load_crs, to_metres
from .gee_init import gee_available, gee_status
from .geometry import densify
from .guide import load_guide_lonlat
from .isolate import SEARCH_BUFFER_M, geometry_from_mask

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "store.json"
RASTER_DIR = ROOT / "data" / "rasters"
PIXEL_M = 30.0

WINDOWS = [
    {
        "id": "epoch-2024-01-06",
        "date": "2024-01-06",
        "start": "2024-01-05",
        "end": "2024-01-12",
        "sensor": "sentinel-2",
    },
    {
        "id": "epoch-2024-01-21",
        "date": "2024-01-21",
        "start": "2024-01-20",
        "end": "2024-01-28",
        "sensor": "sentinel-2",
    },
]


def _strip(obj: dict) -> dict:
    skip = {"centerline_m", "envelope_m", "left_m", "right_m", "river_only_m"}
    return {k: v for k, v in obj.items() if k not in skip}


def _fetch_mask(bounds_m, bundle, window: dict, tif: Path) -> dict:
    sensor = window["sensor"]
    start, end = window["start"], window["end"]
    if gee_available():
        from .gee_water import fetch_water_mask_gee

        print(f"GEE {sensor} {start}→{end}", flush=True)
        if sensor == "sentinel-1":
            return fetch_water_mask_gee(bounds_m, bundle, start, end, "sentinel-1", PIXEL_M, tif)
        return fetch_water_mask_gee(bounds_m, bundle, start, end, "sentinel-2", PIXEL_M, tif)

    from .stac_water import mosaic_s1_water, mosaic_s2_water

    print(f"STAC {sensor} {start}→{end} (GEE not logged in: {gee_status()['reason']})", flush=True)
    if sensor == "sentinel-1":
        return mosaic_s1_water(bounds_m, bundle, start, end, PIXEL_M, tif)
    return mosaic_s2_water(bounds_m, bundle, start, end, PIXEL_M, tif)


def run() -> Path:
    bundle = load_crs()
    guide_ll = load_guide_lonlat()
    guide_m = densify(to_metres(guide_ll, bundle), 400)
    bounds = guide_m.buffer(SEARCH_BUFFER_M).bounds
    RASTER_DIR.mkdir(parents=True, exist_ok=True)

    layers = []
    metas = []
    frozen = None
    for window in WINDOWS:
        tif = RASTER_DIR / f"{window['id']}_water.tif"
        if tif.exists() and tif.stat().st_size > 1000:
            print(f"reuse {tif}", flush=True)
            meta = {"backend": "cached_raster", "sensor": window["sensor"], "window": [window["start"], window["end"]]}
        else:
            meta = _fetch_mask(bounds, bundle, window, tif)
        geom = geometry_from_mask(tif, guide_m, bundle, window["date"], frozen_centerline_m=frozen)
        if frozen is None:
            frozen = geom["centerline_m"]
        layers.append(geom)
        metas.append(meta)
        print(
            f"{window['id']} water features={len(geom['river_only']['features'])} "
            f"width samples={len(geom['width_samples'])} source={meta.get('backend')}",
            flush=True,
        )

    epoch_a, epoch_b = layers
    center = frozen
    length = center.length
    reaches = []
    start = 0.0
    rid = 1
    while start < length:
        end = min(start + 5000.0, length)
        reaches.append(
            {
                "reach_id": f"R{rid:03d}",
                "chainage_start_m": round(start, 1),
                "chainage_end_m": round(end, 1),
            }
        )
        rid += 1
        start = end

    comparison = compare_epochs(epoch_a, epoch_b, reaches, tolerance_m=30.0)
    comparison.pop("bank_changes", None)  # too many points; map uses polygons + inspect table

    gee = gee_status()
    source_note = (
        f"Google Earth Engine project {gee['project']}"
        if gee["available"]
        else (
            "Copernicus Sentinel-2 L2A (same satellite collection as GEE "
            "COPERNICUS/S2_SR_HARMONIZED). Earth Engine is not logged in on this machine "
            f"({gee['reason']}); set GEE_PROJECT after `earthengine authenticate` to switch."
        )
    )

    store = {
        "study_area": {
            "name": "Assam main-stem Brahmaputra",
            "upstream": UPSTREAM_NAME,
            "downstream": DOWNSTREAM_NAME,
            "iwai_waterway": "National Waterway 2 (Sadiya–Bangladesh border)",
            "endpoints": endpoints_lonlat(),
            "crs_name": "Assam_Brahmaputra_Albers",
            "crs_wkt": bundle.projected.to_wkt(),
            "operational_pixel_m": PIXEL_M,
            "landsat_pixel_m": 30,
            "corridor_length_m": round(length, 1),
            "distortion_m_per_km": distortion_report(bundle),
            "source": source_note,
            "how_calculated": [
                "Sentinel-2 water = MNDWI = (Green − SWIR1) / (Green + SWIR1); water if MNDWI > 0.1.",
                "Sentinel-1 water = radar VV darker than −16 dB. Never MNDWI on radar.",
                "Keep only water inside an 11 km search belt along the Brahmaputra from Sadiya to Dhubri. Ponds off the belt are dropped.",
                "Blue fill is that satellite water. Outer edge of the water is the left/right bank (looking downstream).",
                "Yellow line is the middle of the water body, Sadiya → Dhubri — not the 17-point sketch used only to find the river.",
                "Width is the bank-to-bank distance every 300 m on a frozen centreline from the first date.",
                "Red/green change is where the outer water boundary moved > 30 m. Water level can look like erosion.",
            ],
            "disclaimer": (
                "Satellite water, not a surveyed bank. Candidate change only. "
                "Not the entire Brahmaputra basin."
            ),
            "gee": gee,
        },
        "reference": {
            "centerline": epoch_a["corridor_centerline"],
            "cross_sections": epoch_a["cross_sections"],
            "reaches": reaches,
            "section_step_m": 300,
            "search_guide": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"role": "search_guide_only", "note": "Not the river. Used only to clip satellite water."},
                        "geometry": mapping(load_guide_lonlat()),
                    }
                ],
            },
        },
        "acquisitions": [
            {
                "id": f"acq-{m.get('sensor')}-{w['date']}",
                "sensor": m.get("sensor"),
                "date": w["date"],
                "status": "processed",
                "source": m.get("collection") or m.get("backend"),
                "scene_count": m.get("scene_count"),
                "method": m.get("method"),
            }
            for w, m in zip(WINDOWS, metas)
        ],
        "jobs": [
            {
                "id": "job-water-ingest",
                "kind": "satellite_water_mask",
                "status": "processed",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "backend": metas[0].get("backend"),
            }
        ],
        "epochs": [
            {
                "id": w["id"],
                "date": w["date"],
                "sensors": [m.get("sensor") or w["sensor"]],
                "status": "processed",
                "validation_status": "Unvalidated satellite water",
                "source": m.get("collection") or m.get("backend"),
                "method": m.get("method"),
                "scene_count": m.get("scene_count"),
                "layers": _strip(layer),
            }
            for w, m, layer in zip(WINDOWS, metas, layers)
        ],
        "comparisons": [
            {
                "id": f"cmp-{epoch_a['date']}__{epoch_b['date']}",
                "epoch_a_id": WINDOWS[0]["id"],
                "epoch_b_id": WINDOWS[1]["id"],
                **comparison,
            }
        ],
    }
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(store))
    print(f"Wrote {STORE} ({STORE.stat().st_size / 1e6:.1f} MB)", flush=True)
    return STORE


if __name__ == "__main__":
    run()
