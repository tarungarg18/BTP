"""Coarse Earth Engine coverage along the Brahmaputra guide.

Prints the fraction of a 5 km guide buffer that has a usable observation.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from processing.gee_init import require_ee
from processing.guide import load_guide_lonlat
from processing.live_extract import NDWI_THRESHOLD, VV_DB, _mask_clouds

ENDS = [
    "2024-01-20",
    "2025-01-20",
    "2024-02-15",
    "2025-02-15",
    "2023-11-15",
    "2024-11-15",
    "2023-03-01",
    "2024-03-01",
    "2022-12-10",
    "2023-12-10",
]


def window(day: date):
    start = day - timedelta(days=14)
    return start, day + timedelta(days=1)


def main() -> None:
    ee = require_ee()
    line = load_guide_lonlat().simplify(0.03, preserve_topology=True)
    belt = ee.Geometry.LineString([[x, y] for x, y in line.coords]).buffer(5000)
    out = {}
    for text in ENDS:
        day = date.fromisoformat(text)
        start, end = window(day)
        region = belt
        optical = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(region)
            .filterDate(start.isoformat(), end.isoformat())
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 90))
            .select(["B3", "B11", "SCL"])
        )
        sar = (
            ee.ImageCollection("COPERNICUS/S1_GRD")
            .filterBounds(region)
            .filterDate(start.isoformat(), end.isoformat())
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .select(["VV"])
        )

        def optical_valid(image):
            return _mask_clouds(image).select("B3").mask().unmask(0).toFloat()

        def sar_valid(image):
            return image.select("VV").mask().unmask(0).toFloat()

        opt = optical.map(optical_valid).max().rename("v")
        rad = sar.map(sar_valid).max().rename("v")
        reducer = ee.Reducer.mean()
        out[f"optical_{text}"] = opt.reduceRegion(reducer, region, 2000, maxPixels=1e8).get("v")
        out[f"sar_{text}"] = rad.reduceRegion(reducer, region, 2000, maxPixels=1e8).get("v")
        out[f"optical_n_{text}"] = optical.size()
        out[f"sar_n_{text}"] = sar.size()
    values = ee.Dictionary(out).getInfo()
    rows = []
    for text in ENDS:
        rows.append({
            "end": text,
            "optical": None if values[f"optical_{text}"] is None else round(float(values[f"optical_{text}"]), 3),
            "optical_scenes": int(values[f"optical_n_{text}"]),
            "sar": None if values[f"sar_{text}"] is None else round(float(values[f"sar_{text}"]), 3),
            "sar_scenes": int(values[f"sar_n_{text}"]),
        })
    print(json.dumps(rows, indent=2), flush=True)


if __name__ == "__main__":
    main()
