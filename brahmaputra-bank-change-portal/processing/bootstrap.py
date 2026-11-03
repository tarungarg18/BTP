"""Seed the local store with a locked Assam corridor and two dated epochs."""

from __future__ import annotations

import json
from pathlib import Path

from .aoi import DOWNSTREAM_NAME, UPSTREAM_NAME, endpoints_lonlat
from .change import compare_epochs
from .crs import distortion_report, load_crs
from .geometry import build_reference, epoch_geometry

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "store.json"


def run() -> Path:
    bundle = load_crs()
    distortion = distortion_report(bundle)
    reference = build_reference(bundle)
    epoch_a = epoch_geometry(reference, "2024-01-12", bank_shift_m=0.0)
    epoch_b = epoch_geometry(reference, "2024-01-27", bank_shift_m=85.0)
    comparison = compare_epochs(epoch_a, epoch_b, reference["reaches"], tolerance_m=30.0)

    def strip_shapely(obj: dict) -> dict:
        skip = {"centerline_m", "envelope_m", "left_m", "right_m"}
        return {k: v for k, v in obj.items() if k not in skip}

    store = {
        "study_area": {
            "name": "Assam main-stem Brahmaputra",
            "upstream": UPSTREAM_NAME,
            "downstream": DOWNSTREAM_NAME,
            "iwai_waterway": "National Waterway 2 (Sadiya–Bangladesh border)",
            "endpoints": endpoints_lonlat(),
            "crs_name": "Assam_Brahmaputra_Albers",
            "crs_wkt": bundle.projected.to_wkt(),
            "operational_pixel_m": 20,
            "landsat_pixel_m": 30,
            "corridor_length_m": reference["length_m"],
            "distortion_m_per_km": distortion,
            "disclaimer": (
                "Selected Assam main stem, not the entire Brahmaputra basin. "
                "Bootstrap corridor pending GEE water-mask ingest."
            ),
        },
        "reference": {
            "centerline": reference["centerline"],
            "cross_sections": reference["cross_sections"],
            "reaches": reference["reaches"],
            "section_step_m": 300,
        },
        "acquisitions": [
            {
                "id": "acq-s2-2024-01-12",
                "sensor": "sentinel-2",
                "date": "2024-01-12",
                "status": "processed",
                "source": "bootstrap_pending_gee",
            },
            {
                "id": "acq-s1-2024-01-27",
                "sensor": "sentinel-1",
                "date": "2024-01-27",
                "status": "processed",
                "source": "bootstrap_pending_gee",
            },
            {
                "id": "acq-s2-2024-02-10",
                "sensor": "sentinel-2",
                "date": "2024-02-10",
                "status": "discovered",
                "source": "catalogue_placeholder",
            },
        ],
        "jobs": [
            {
                "id": "job-001",
                "kind": "bootstrap_geometry",
                "status": "processed",
                "started_at": "2024-01-12T04:00:00Z",
                "finished_at": "2024-01-12T04:12:00Z",
            }
        ],
        "epochs": [
            {
                "id": "epoch-2024-01-12",
                "date": "2024-01-12",
                "sensors": ["sentinel-2"],
                "status": "processed",
                "validation_status": "Unvalidated",
                "source": "bootstrap_pending_gee",
                "layers": strip_shapely(epoch_a),
            },
            {
                "id": "epoch-2024-01-27",
                "date": "2024-01-27",
                "sensors": ["sentinel-1"],
                "status": "processed",
                "validation_status": "Unvalidated",
                "source": "bootstrap_pending_gee",
                "layers": strip_shapely(epoch_b),
            },
        ],
        "comparisons": [
            {
                "id": "cmp-2024-01-12__2024-01-27",
                "epoch_a_id": "epoch-2024-01-12",
                "epoch_b_id": "epoch-2024-01-27",
                **comparison,
            }
        ],
    }
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(store, indent=2))
    return STORE


if __name__ == "__main__":
    path = run()
    print(f"Wrote {path}")
