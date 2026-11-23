"""Calculate three clear-season pairs and save presentation maps.

Optical, 15-day windows. Both Sentinel-2 and Sentinel-1 cover these windows.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from processing.date_options import build_compare_request
from processing.live_extract import _pair_from_request, _rc_of

OUT = ROOT / "reports" / "present"
PAIRS = [
    ("01_january_2024_2025", "2024-01-20", "2025-01-20", "January 2024 and January 2025"),
    ("02_november_2023_2024", "2023-11-15", "2024-11-15", "November 2023 and November 2024"),
    ("03_winter_2023_2024", "2023-03-01", "2024-02-15", "March 2023 and February 2024"),
]


def _draw(pair: dict, path: Path) -> None:
    stride = 6
    erosion = pair["erosion"][::stride, ::stride]
    deposition = pair["deposition"][::stride, ::stride]
    water = pair["later_water"][::stride, ::stride]
    rgb = np.full((*erosion.shape, 3), 236, dtype=np.uint8)
    rgb[water] = (125, 176, 196)
    rgb[deposition] = (214, 138, 38)
    rgb[erosion] = (214, 48, 58)
    image = Image.fromarray(rgb, mode="RGB")
    draw = ImageDraw.Draw(image)
    grid = pair["grid"]
    colors = {
        "start_left": (14, 116, 144),
        "start_right": (14, 116, 144),
        "end_left": (180, 83, 9),
        "end_right": (180, 83, 9),
    }
    for feature in pair.get("banks") or []:
        role = feature.get("properties", {}).get("role", "")
        if role not in colors or feature["geometry"]["type"] != "LineString":
            continue
        points = []
        for lon, lat in feature["geometry"]["coordinates"]:
            row, col = _rc_of(float(lon), float(lat), grid)
            points.append((col / stride, row / stride))
        if len(points) >= 2:
            draw.line(points, fill=colors[role], width=2)
    image.save(path, format="PNG")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = []
    for key, earlier, later, title in PAIRS:
        print(f"PAIR {title}", flush=True)
        request = build_compare_request(
            mode="dates",
            sensor="optical",
            window_days=15,
            earlier=earlier,
            later=later,
            acknowledge_partial=True,
        )
        pair = _pair_from_request(request, staged=False, fetch_both_sensors=False)
        stats = pair["stats"]
        image = OUT / f"{key}.png"
        _draw(pair, image)
        banks = pair.get("bankline_qc") or {}
        row = {
            "title": title,
            "earlier": request.earlier.label,
            "later": request.later.label,
            "sensor": "Sentinel-2 optical",
            "window_days": 15,
            "erosion_km2": stats.get("erosion_km2"),
            "deposition_km2": stats.get("deposition_km2"),
            "net_km2": stats.get("net_km2"),
            "valid_fraction": stats.get("valid_fraction"),
            "image": str(image),
            "bank_km": {
                name: (side or {}).get("length_km") for name, side in banks.items()
            },
        }
        summary.append(row)
        print(json.dumps(row), flush=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("WROTE", OUT / "summary.json", flush=True)


if __name__ == "__main__":
    main()
