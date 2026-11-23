"""Real-data QC audit for the envelope / bankline pipeline.

Writes reports/qc/ artifacts. Does not invent banklines or alter displayed
areas to force agreement — it measures and documents.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import array_bounds
from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "qc"


def _write_mask_tif(path: Path, mask: np.ndarray, transform, nodata: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=mask.shape[0],
        width=mask.shape[1],
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
        compress="lzw",
    ) as ds:
        ds.write(np.asarray(mask, dtype=np.uint8), 1)


def _write_rgb(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(path)


def _bank_report(feat: dict, guide_m, bundle) -> dict:
    from shapely.geometry import LineString, Point

    from processing.bankline_compare import _signed_side
    from processing.crs import to_metres

    geom = shape(feat["geometry"])
    line_m = to_metres(geom, bundle)
    coords = list(geom.coords)
    gaps = []
    for i in range(1, len(coords)):
        gaps.append(math.hypot(coords[i][0] - coords[i - 1][0], coords[i][1] - coords[i - 1][1]) * 111_000)
    # side fraction in projected space
    line_m = LineString(list(line_m.coords)) if not isinstance(line_m, LineString) else line_m
    pos = 0
    n = 0
    for i in range(0, len(line_m.coords), max(1, len(line_m.coords) // 40)):
        n += 1
        if _signed_side(line_m.coords[i], guide_m) > 0:
            pos += 1
    role = feat["properties"]["role"]
    want_left = "left" in role
    side_pct = 100.0 * pos / max(n, 1) if want_left else 100.0 * (1 - pos / max(n, 1))
    return {
        "role": role,
        "geom_type": geom.geom_type,
        "valid": bool(geom.is_valid),
        "simple": bool(geom.is_simple),
        "length_km": round(float(line_m.length) / 1000.0, 2),
        "vertices": len(coords),
        "first": [round(coords[0][0], 5), round(coords[0][1], 5)],
        "last": [round(coords[-1][0], 5), round(coords[-1][1], 5)],
        "max_vertex_gap_m_approx": round(max(gaps) if gaps else 0.0, 1),
        "pct_on_expected_side": round(side_pct, 1),
    }


def _observation_rgb(corridor, earlier_obs, later_obs) -> np.ndarray:
    h, w = corridor.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    common = corridor & earlier_obs & later_obs
    earlier_only = corridor & earlier_obs & ~later_obs
    later_only = corridor & later_obs & ~earlier_obs
    nodata = corridor & ~earlier_obs & ~later_obs
    rgb[nodata] = (40, 40, 40)
    rgb[earlier_only] = (56, 189, 248)
    rgb[later_only] = (245, 158, 11)
    rgb[common] = (34, 197, 94)
    return rgb


def _transect_rgb(rows, transform, shape_hw) -> np.ndarray:
    h, w = shape_hw
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[:] = (20, 20, 20)
    colors = {
        "both_ok": (34, 197, 94),
        "ok": (34, 197, 94),
        "earlier_only": (56, 189, 248),
        "later_only": (245, 158, 11),
        "neither": (120, 40, 40),
        "missing_intersection": (120, 40, 40),
    }
    a, e = float(transform.a), float(abs(transform.e))
    c, f = float(transform.c), float(transform.f)
    for row in rows:
        col = int((row["longitude"] - c) / a)
        r = int((f - row["latitude"]) / e)
        if 0 <= r < h and 0 <= col < w:
            color = colors.get(row["qc_status"], (80, 80, 80))
            rgb[max(0, r - 2) : r + 3, max(0, col - 2) : col + 3] = color
    return rgb


def _bankline_diagnostic_png(pair, transform, path: Path) -> None:
    from PIL import ImageDraw

    h, w = pair["earlier_body"].shape
    # Downsample for a readable PNG.
    stride = 4
    canvas = np.zeros((h // stride, w // stride, 3), dtype=np.uint8)
    canvas[::] = (15, 20, 28)
    for name, color in (("earlier_body", (40, 70, 90)), ("later_body", (60, 50, 30))):
        mask = pair[name][::stride, ::stride]
        canvas[mask] = color
    img = Image.fromarray(canvas, mode="RGB")
    draw = ImageDraw.Draw(img)
    a, e = float(transform.a), float(abs(transform.e))
    c, f = float(transform.c), float(transform.f)

    def to_px(lon, lat):
        return ((lon - c) / a / stride, (f - lat) / e / stride)

    for feat in pair["banks"]:
        role = feat["properties"]["role"]
        geom = feat["geometry"]
        if geom["type"] == "LineString":
            color = (56, 189, 248) if role.startswith("start") else (245, 158, 11)
            pts = [to_px(lon, lat) for lon, lat in geom["coordinates"][:: max(1, len(geom["coordinates"]) // 800)]]
            if len(pts) >= 2:
                draw.line(pts, fill=color, width=1)
        elif geom["type"] == "Point":
            x, y = to_px(geom["coordinates"][0], geom["coordinates"][1])
            r = 3
            draw.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255), fill=(255, 80, 80))
    img.save(path)


def run(later="2026-04-22", earlier="2026-04-08") -> dict:
    from processing.bankline_compare import (
        DEFAULT_CLOSE_M,
        _guide_frame,
        write_transect_csv,
    )
    from processing.crs import load_crs
    from processing.guide import load_guide_lonlat
    from processing.live_extract import _PAIR_CACHE, _base_grid, _pair

    OUT.mkdir(parents=True, exist_ok=True)
    _PAIR_CACHE.clear()
    pair = _pair(later, earlier, sensor="optical")
    transform, width, height, grid = _base_grid()
    stats = pair["stats"]
    obs = pair["observation"]
    tqc = pair["transect_qc"]

    # 1–2 GeoTIFFs
    _write_mask_tif(OUT / "earlier_water.tif", pair["earlier_water"], transform)
    _write_mask_tif(OUT / "later_water.tif", pair["later_water"], transform)
    _write_mask_tif(OUT / "earlier_envelope.tif", pair["earlier_body"], transform)
    _write_mask_tif(OUT / "later_envelope.tif", pair["later_body"], transform)
    _write_mask_tif(OUT / "common_valid.tif", pair["valid"], transform)
    _write_mask_tif(OUT / "erosion.tif", pair["erosion_raw"] if pair.get("erosion_raw") is not None else pair["erosion"], transform)
    _write_mask_tif(OUT / "deposition.tif", pair["deposition_raw"] if pair.get("deposition_raw") is not None else pair["deposition"], transform)

    # Vectors
    (OUT / "earlier_envelope.geojson").write_text(json.dumps(pair["envelopes"]["earlier"]), encoding="utf-8")
    (OUT / "later_envelope.geojson").write_text(json.dumps(pair["envelopes"]["later"]), encoding="utf-8")
    banks = {"type": "FeatureCollection", "features": [f for f in pair["banks"] if f["geometry"]["type"] == "LineString"]}
    endpoints = {"type": "FeatureCollection", "features": [f for f in pair["banks"] if f["geometry"]["type"] == "Point"]}
    (OUT / "banklines.geojson").write_text(json.dumps(banks), encoding="utf-8")
    (OUT / "endpoints.geojson").write_text(json.dumps(endpoints), encoding="utf-8")

    write_transect_csv(pair["transects"], OUT / "transects_qc.csv")

    corridor = pair["belt"]
    earlier_obs = pair["earlier_observed"] & corridor
    later_obs = pair["later_observed"] & corridor
    _write_rgb(OUT / "observation_diagnostic.png", _observation_rgb(corridor, earlier_obs, later_obs)[::4, ::4])
    _write_rgb(OUT / "transect_diagnostic.png", _transect_rgb(pair["transects"], transform, pair["earlier_body"].shape)[::4, ::4])
    _bankline_diagnostic_png(pair, transform, OUT / "banklines_diagnostic.png")

    bundle, guide_m = _guide_frame(load_guide_lonlat())
    bank_qc = [_bank_report(f, guide_m, bundle) for f in banks["features"]]

    # Closing sensitivity on a window around Guwahati
    from processing.bankline_compare import build_outer_river_envelope, guide_search_mask
    from processing.live_extract import extract_window, resolve_windows

    ew, lw = resolve_windows(later, earlier)
    later_win = extract_window(*lw, "optical")
    gmask = guide_search_mask(height, width, transform, 8_000.0)
    pixel_m = abs(float(transform.a)) * 111_320.0 * math.cos(math.radians(27.0))
    sensitivity = {}
    for close_m in (100, 200, 300, 500):
        env = build_outer_river_envelope(
            later_win["water"], corridor, pixel_m=pixel_m, close_m=float(close_m), guide_mask=gmask
        )
        sensitivity[str(close_m)] = {
            "pixels": int(env.sum()),
            "cols": int(env.any(0).sum()),
            "components": int(__import__("scipy.ndimage", fromlist=["label"]).label(env)[1]),
        }
        _write_mask_tif(OUT / f"sensitivity_close_{close_m}m.tif", env, transform)

    west, south, east, north = array_bounds(height, width, transform)
    report = {
        "pair": {"earlier": earlier, "later": later, "sensor": pair["sensor"]},
        "grid": {
            "shape": [height, width],
            "crs": "EPSG:4326",
            "transform": [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f],
            "bounds": {"west": west, "south": south, "east": east, "north": north},
            "pixel_m2_albers": stats.get("pixel_m2"),
            "pixel_km2_albers": stats.get("pixel_km2"),
            "same_grid_both_dates": True,
            "close_m": DEFAULT_CLOSE_M,
        },
        "area_accounting": {
            "source": stats.get("area_source"),
            "earlier_full_pixels": stats.get("earlier_full_pixels"),
            "later_full_pixels": stats.get("later_full_pixels"),
            "earlier_full_km2": stats.get("earlier_full_km2"),
            "later_full_km2": stats.get("later_full_km2"),
            "earlier_common_valid_pixels": stats.get("earlier_valid_pixels"),
            "later_common_valid_pixels": stats.get("later_valid_pixels"),
            "earlier_common_valid_km2": stats.get("earlier_km2"),
            "later_common_valid_km2": stats.get("later_km2"),
            "albers_polygon_earlier_valid_km2": stats.get("albers_earlier_valid_km2"),
            "albers_polygon_later_valid_km2": stats.get("albers_later_valid_km2"),
            "erosion_km2": stats.get("erosion_km2"),
            "deposition_km2": stats.get("deposition_km2"),
            "net_later_minus_earlier_km2": stats.get("net_km2"),
            "net_erosion_minus_deposition_km2": round(
                float(stats["erosion_km2"]) - float(stats["deposition_km2"]), 3
            ),
            "accounting_identity_ok": abs(
                float(stats["net_km2"]) - (float(stats["erosion_km2"]) - float(stats["deposition_km2"]))
            )
            < 1e-6,
            "note": (
                "Full-envelope pixel counts are NOT comparable to common-valid areas. "
                "Reported erosion/deposition/earlier/later corridor areas use envelope & common_valid only."
            ),
        },
        "observation": obs,
        "transect_qc": tqc,
        "banklines": bank_qc,
        "endpoints": [
            {
                "role": f["properties"]["role"],
                "coordinates": f["geometry"]["coordinates"],
            }
            for f in endpoints["features"]
        ],
        "closing_sensitivity": sensitivity,
        "unresolved": [
            obs.get("coverage_warning") or "Common valid coverage is adequate.",
            (
                f"Only {tqc['both_ok']}/{tqc['total_transects']} transects have both-date "
                f"intersections ({tqc['pct_of_guide']}% of full guide). Within the mutual "
                f"envelope span, coverage is {tqc.get('pct_of_mutual_span')}%."
            ),
            (
                "Optical-only envelopes for cloudy 15-day windows remain incomplete along "
                "parts of Sadiya–Dhubri; microwave is not silently fused into water."
            ),
        ],
    }
    (OUT / "qc_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    md = [
        "# Brahmaputra bankline QC report",
        "",
        f"Pair: earlier **{earlier}**, later **{later}**, sensor **optical**.",
        f"Closing radius: **{DEFAULT_CLOSE_M} m** (single configurable parameter).",
        "",
        "## 1. Grid and area accounting",
        "",
        f"- Shared grid shape `{height}×{width}`, CRS EPSG:4326, Assam-Albers pixel area "
        f"**{stats.get('pixel_m2')} m²** ({stats.get('pixel_km2')} km²).",
        f"- Full envelope pixels: earlier **{stats.get('earlier_full_pixels')}**, later **{stats.get('later_full_pixels')}**.",
        f"- Full envelope area (same pixel area): earlier **{stats.get('earlier_full_km2')} km²**, "
        f"later **{stats.get('later_full_km2')} km²**.",
        f"- Common-valid envelope pixels: earlier **{stats.get('earlier_valid_pixels')}**, "
        f"later **{stats.get('later_valid_pixels')}**.",
        f"- Common-valid areas (reported): earlier **{stats.get('earlier_km2')} km²**, "
        f"later **{stats.get('later_km2')} km²**.",
        f"- Independent Albers polygonization: earlier **{stats.get('albers_earlier_valid_km2')} km²**, "
        f"later **{stats.get('albers_later_valid_km2')} km²**.",
        f"- Erosion **{stats.get('erosion_km2')}**, deposition **{stats.get('deposition_km2')}**, "
        f"net **{stats.get('net_km2')}**.",
        f"- Identity later−earlier = erosion−deposition: "
        f"**{report['area_accounting']['accounting_identity_ok']}**.",
        "",
        "**Root cause of the apparent pixel/area inconsistency:** the component pixel counts "
        "were full envelopes, while the reported km² values were common-valid only. "
        "Both are now reported explicitly.",
        "",
        "## 2. Valid observation coverage",
        "",
        f"- Corridor pixels: **{obs['corridor_pixels']}**",
        f"- Earlier observed: **{obs['earlier_observed_fraction']*100:.1f}%**",
        f"- Later observed: **{obs['later_observed_fraction']*100:.1f}%**",
        f"- Common valid: **{obs['common_valid_fraction_of_corridor']*100:.1f}%**",
        f"- NoData in both: **{obs['nodata_both_fraction']*100:.1f}%**",
        "",
        obs.get("coverage_warning") or "Coverage warning: none.",
        "",
        "See `observation_diagnostic.png` (green=common, cyan=earlier-only, amber=later-only, grey=nodata).",
        "",
        "## 3. Transects",
        "",
        f"- both_ok **{tqc['both_ok']}** / {tqc['total_transects']} ({tqc['pct_of_guide']}% of full guide)",
        f"- earlier_only **{tqc['earlier_only']}**, later_only **{tqc['later_only']}**, neither **{tqc['neither']}**",
        f"- left_ok **{tqc['left_bank_ok']}**, right_ok **{tqc['right_bank_ok']}**",
        f"- first both_ok chainage **{tqc['first_both_ok_chainage_m']} m**, last **{tqc['last_both_ok_chainage_m']} m**",
        f"- max consecutive missing **{tqc['max_consecutive_missing_m']} m**",
        f"- within mutual envelope span: **{tqc.get('pct_of_mutual_span')}%** both_ok",
        "",
        tqc.get("note", ""),
        "",
        "CSV: `transects_qc.csv`. Map: `transect_diagnostic.png`.",
        "",
        "## 4. Closing sensitivity (later date)",
        "",
    ]
    for close_m, row in sensitivity.items():
        md.append(f"- {close_m} m → {row['pixels']} px, {row['cols']} cols, {row['components']} components")
    md.extend(
        [
            "",
            f"Active setting: **{DEFAULT_CLOSE_M} m** (was previously confused with a 750 m leftover).",
            "",
            "## 5. Banklines",
            "",
        ]
    )
    for row in bank_qc:
        md.append(
            f"- **{row['role']}**: {row['length_km']} km, {row['vertices']} vertices, "
            f"simple={row['simple']}, side={row['pct_on_expected_side']}%, "
            f"ends {row['first']} → {row['last']}"
        )
    md.extend(
        [
            "",
            "Endpoints in `endpoints.geojson`. Overview `banklines_diagnostic.png`.",
            "",
            "## Unresolved / limitations",
            "",
        ]
    )
    for item in report["unresolved"]:
        md.append(f"- {item}")
    (OUT / "qc_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "net_ok": report["area_accounting"]["accounting_identity_ok"], "valid_pct": obs["common_valid_fraction_of_corridor"], "transect_both_ok": tqc["both_ok"]}, indent=2))
    return report


if __name__ == "__main__":
    run()
