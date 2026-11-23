"""Synthetic mathematical tests for outer-envelope bankline comparison."""

from __future__ import annotations

import math

import numpy as np
from rasterio.transform import from_origin, xy
from shapely.geometry import LineString, Polygon

from processing.bankline_compare import (
    BanklineQCError,
    SIDE_CONFIDENCE,
    bankline_qc_report,
    build_outer_river_envelope,
    calculate_area_statistics,
    calculate_corridor_difference,
    extract_outer_ring,
    find_endpoints,
    sample_bank_transects,
    split_left_right_banks,
    transect_coverage_summary,
)
from processing.crs import load_crs, to_metres


def _grid(width=200, height=80, pixel_m=100.0):
    transform = from_origin(0, height * pixel_m, pixel_m, pixel_m)
    return transform, width, height


def _horizontal_river(width, height, row0, row1, col0, col1, island=False):
    water = np.zeros((height, width), dtype=bool)
    water[row0:row1, col0:col1] = True
    if island:
        water[(row0 + row1) // 2 - 2 : (row0 + row1) // 2 + 2, (col0 + col1) // 2 - 5 : (col0 + col1) // 2 + 5] = False
    return water


def _corridor(width, height):
    return np.ones((height, width), dtype=bool)


def _guide_for_box(transform, width, height, row_mid):
    bundle = load_crs()
    x_east, y = xy(transform, row_mid, width - 5, offset="center")
    x_west, _ = xy(transform, row_mid, 5, offset="center")
    lon_e, lat_e = bundle.to_lonlat.transform(x_east, y)
    lon_w, lat_w = bundle.to_lonlat.transform(x_west, y)
    return LineString([(lon_e, lat_e), (lon_w, lat_w)])


def test_identical_envelopes_zero_change():
    transform, w, h = _grid()
    river = _horizontal_river(w, h, 30, 50, 10, 190)
    corridor = _corridor(w, h)
    env = build_outer_river_envelope(river, corridor, pixel_m=100.0, close_m=200.0, guide_mask=river)
    valid = np.ones_like(env)
    erosion, deposition, persistent, common, ero_raw, dep_raw = calculate_corridor_difference(
        env, env, valid, valid, corridor, min_patch_m2=1.0, pixel_m=100.0
    )
    assert not erosion.any() and not ero_raw.any()
    assert not deposition.any() and not dep_raw.any()
    assert persistent.sum() == env.sum()
    stats = calculate_area_statistics(env, env, ero_raw, dep_raw, persistent, common, transform)
    assert stats["erosion_km2"] == 0
    assert stats["deposition_km2"] == 0
    assert abs(stats["net_km2"]) < 1e-6


def test_left_expansion_is_erosion():
    transform, w, h = _grid()
    corridor = _corridor(w, h)
    earlier = _horizontal_river(w, h, 35, 50, 10, 190)
    later = _horizontal_river(w, h, 30, 50, 10, 190)
    valid = np.ones((h, w), dtype=bool)
    erosion, deposition, persistent, common, _, _ = calculate_corridor_difference(
        earlier, later, valid, valid, corridor, min_patch_m2=1.0, pixel_m=100.0
    )
    assert erosion.any()
    assert not deposition.any()
    assert erosion[30:35, 20:180].mean() > 0.5


def test_right_expansion_is_erosion():
    transform, w, h = _grid()
    corridor = _corridor(w, h)
    earlier = _horizontal_river(w, h, 30, 45, 10, 190)
    later = _horizontal_river(w, h, 30, 50, 10, 190)
    valid = np.ones((h, w), dtype=bool)
    erosion, deposition, *_ = calculate_corridor_difference(
        earlier, later, valid, valid, corridor, min_patch_m2=1.0, pixel_m=100.0
    )
    assert erosion.any()
    assert erosion[45:50, 20:180].mean() > 0.5


def test_left_contraction_is_deposition():
    transform, w, h = _grid()
    corridor = _corridor(w, h)
    earlier = _horizontal_river(w, h, 30, 50, 10, 190)
    later = _horizontal_river(w, h, 35, 50, 10, 190)
    valid = np.ones((h, w), dtype=bool)
    erosion, deposition, *_ = calculate_corridor_difference(
        earlier, later, valid, valid, corridor, min_patch_m2=1.0, pixel_m=100.0
    )
    assert deposition.any()
    assert not erosion.any()


def test_right_contraction_is_deposition():
    transform, w, h = _grid()
    corridor = _corridor(w, h)
    earlier = _horizontal_river(w, h, 30, 50, 10, 190)
    later = _horizontal_river(w, h, 30, 45, 10, 190)
    valid = np.ones((h, w), dtype=bool)
    erosion, deposition, *_ = calculate_corridor_difference(
        earlier, later, valid, valid, corridor, min_patch_m2=1.0, pixel_m=100.0
    )
    assert deposition.any()
    assert not erosion.any()


def test_date_reversal_swaps_classes():
    transform, w, h = _grid()
    corridor = _corridor(w, h)
    earlier = _horizontal_river(w, h, 35, 50, 10, 190)
    later = _horizontal_river(w, h, 30, 50, 10, 190)
    valid = np.ones((h, w), dtype=bool)
    e1, d1, *_ = calculate_corridor_difference(earlier, later, valid, valid, corridor, min_patch_m2=1.0, pixel_m=100.0)
    e2, d2, *_ = calculate_corridor_difference(later, earlier, valid, valid, corridor, min_patch_m2=1.0, pixel_m=100.0)
    assert np.array_equal(e1, d2)
    assert np.array_equal(d1, e2)
    assert e1.sum() + d1.sum() == e2.sum() + d2.sum()


def test_braided_islands_stay_inside_envelope():
    transform, w, h = _grid()
    corridor = _corridor(w, h)
    water = _horizontal_river(w, h, 30, 50, 10, 190, island=True)
    guide = water.copy()
    guide[:] = False
    guide[40, 10:190] = True
    env = build_outer_river_envelope(water, corridor, pixel_m=100.0, close_m=400.0, guide_mask=guide)
    assert env[40, 100]
    poly = extract_outer_ring(env, transform)
    assert len(poly.interiors) == 0


def test_isolated_lake_excluded():
    transform, w, h = _grid()
    corridor = _corridor(w, h)
    water = _horizontal_river(w, h, 30, 50, 10, 190)
    water[5:12, 20:30] = True
    guide = np.zeros((h, w), dtype=bool)
    guide[40, 10:190] = True
    env = build_outer_river_envelope(water, corridor, pixel_m=100.0, close_m=200.0, guide_mask=guide)
    assert not env[5:12, 20:30].any()


def test_missing_observation_not_change():
    transform, w, h = _grid()
    corridor = _corridor(w, h)
    earlier = _horizontal_river(w, h, 30, 50, 10, 190)
    later = _horizontal_river(w, h, 30, 55, 10, 190)
    valid_e = np.ones((h, w), dtype=bool)
    valid_l = np.ones((h, w), dtype=bool)
    valid_l[50:55, :] = False
    erosion, deposition, _, common, *_ = calculate_corridor_difference(
        earlier, later, valid_e, valid_l, corridor, min_patch_m2=1.0, pixel_m=100.0
    )
    assert not erosion[50:55, 20:180].any()
    assert not common[50:55, 20:180].any()


def test_area_accounting():
    transform, w, h = _grid()
    corridor = _corridor(w, h)
    earlier = _horizontal_river(w, h, 35, 50, 10, 190)
    later = _horizontal_river(w, h, 30, 52, 10, 190)
    valid = np.ones((h, w), dtype=bool)
    erosion, deposition, persistent, common, ero_raw, dep_raw = calculate_corridor_difference(
        earlier, later, valid, valid, corridor, min_patch_m2=1.0, pixel_m=100.0
    )
    stats = calculate_area_statistics(earlier, later, ero_raw, dep_raw, persistent, common, transform)
    assert abs(stats["net_km2"] - (stats["erosion_km2"] - stats["deposition_km2"])) < 0.5
    assert abs(stats["pixel_m2"] - 10_000.0) < 1e-6


def test_curved_corridor_banklines():
    transform, w, h = _grid(width=220, height=120, pixel_m=100.0)
    water = np.zeros((h, w), dtype=bool)
    for col in range(15, 205):
        centre = int(40 + 18 * math.sin((col - 15) / 30.0))
        water[centre - 8 : centre + 8, col] = True
    corridor = _corridor(w, h)
    guide_mask = np.zeros((h, w), dtype=bool)
    for col in range(15, 205):
        centre = int(40 + 18 * math.sin((col - 15) / 30.0))
        guide_mask[centre, col] = True
    env = build_outer_river_envelope(water, corridor, pixel_m=100.0, close_m=250.0, guide_mask=guide_mask)
    bundle = load_crs()
    poly_m = extract_outer_ring(env, transform)
    coords = []
    for col in range(204, 14, -3):
        centre = int(40 + 18 * math.sin((col - 15) / 30.0))
        x, y = xy(transform, centre, col, offset="center")
        lon, lat = bundle.to_lonlat.transform(x, y)
        coords.append((lon, lat))
    guide = LineString(coords)
    guide_m = to_metres(guide, bundle)
    ends = find_endpoints(poly_m, guide_m, search_inward_m=5_000.0, step_m=250.0)
    left, right = split_left_right_banks(poly_m, ends, guide_m)
    assert left.length > 5_000
    assert right.length > 5_000
    widths = []
    for s in np.linspace(0.1, 0.9, 8):
        widths.append(left.interpolate(s, normalized=True).distance(right.interpolate(s, normalized=True)))
    assert max(widths) - min(widths) > 50


def test_long_parallel_water_body_not_selected_over_guide_river():
    """Unrelated long E–W water must lose to the guide-touching main stem."""
    transform, w, h = _grid(width=220, height=100, pixel_m=100.0)
    corridor = _corridor(w, h)
    water = _horizontal_river(w, h, 35, 55, 30, 140)
    water[8:14, 10:210] = True
    guide = np.zeros((h, w), dtype=bool)
    guide[45, 30:140] = True
    env = build_outer_river_envelope(water, corridor, pixel_m=100.0, close_m=150.0, guide_mask=guide)
    assert env[8:14, :].sum() == 0, "parallel E–W lake must not dominate the envelope"
    assert env[35:55, 50:120].mean() > 0.5


def test_ambiguous_transect_multi_intersection_not_extremes():
    """More than two ring hits on a cross-section → ambiguous, no offset extremes."""
    bundle = load_crs()
    poly_m = Polygon(
        [
            (-20_000, -2_000),
            (20_000, -2_000),
            (20_000, -500),
            (-500, -500),
            (-500, 500),
            (20_000, 500),
            (20_000, 2_000),
            (-20_000, 2_000),
            (-20_000, 500),
            (500, 500),
            (500, -500),
            (-20_000, -500),
        ]
    )
    guide_west = bundle.to_lonlat.transform(-18_000, 0)
    guide_east = bundle.to_lonlat.transform(18_000, 0)
    guide = LineString([guide_east, guide_west])
    guide_m = to_metres(guide, bundle)
    rows = sample_bank_transects(poly_m, poly_m, guide_m, step_m=5_000.0, reach_m=30_000.0)
    mid = min(rows, key=lambda r: abs(r["chainage_m"] - guide_m.length / 2))
    assert mid["ambiguous"] is True
    assert mid["qc_status"] == "ambiguous"
    assert mid["left_old_offset_m"] is None and mid["right_old_offset_m"] is None
    summary = transect_coverage_summary(rows)
    assert summary["ambiguous"] >= 1


def test_endpoints_produce_two_banks():
    transform, w, h = _grid()
    water = _horizontal_river(w, h, 30, 50, 10, 190)
    corridor = _corridor(w, h)
    guide_mask = np.zeros((h, w), dtype=bool)
    guide_mask[40, 10:190] = True
    env = build_outer_river_envelope(water, corridor, pixel_m=100.0, close_m=200.0, guide_mask=guide_mask)
    poly_m = extract_outer_ring(env, transform)
    bundle = load_crs()
    guide = _guide_for_box(transform, w, h, 40)
    guide_m = to_metres(guide, bundle)
    ends = find_endpoints(poly_m, guide_m, search_inward_m=3_000.0, step_m=200.0)
    assert set(ends) == {"UL", "UR", "DL", "DR"}
    left, right = split_left_right_banks(poly_m, ends, guide_m)
    assert left.is_simple and right.is_simple


def test_bankline_qc_report_keys_and_side_confidence():
    transform, w, h = _grid()
    water = _horizontal_river(w, h, 30, 50, 10, 190)
    corridor = _corridor(w, h)
    guide_mask = np.zeros((h, w), dtype=bool)
    guide_mask[40, 10:190] = True
    env = build_outer_river_envelope(water, corridor, pixel_m=100.0, close_m=200.0, guide_mask=guide_mask)
    poly_m = extract_outer_ring(env, transform)
    guide = _guide_for_box(transform, w, h, 40)
    guide_m = to_metres(guide, load_crs())
    ends = find_endpoints(poly_m, guide_m, search_inward_m=3_000.0, step_m=200.0)
    left, right = split_left_right_banks(poly_m, ends, guide_m)
    qc = bankline_qc_report(left, right, guide_m, poly_m)
    expected_keys = {
        "length_km",
        "is_simple",
        "max_coordinate_gap_m",
        "pct_on_expected_side",
        "median_distance_to_exterior_m",
    }
    for side in ("left", "right"):
        assert expected_keys <= set(qc[side].keys())
        assert qc[side]["is_simple"] is True
        assert qc[side]["pct_on_expected_side"] >= 100.0 * SIDE_CONFIDENCE
        assert qc[side]["length_km"] > 0
        assert qc[side]["median_distance_to_exterior_m"] < 500.0