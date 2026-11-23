"""Checks for the HOD-readiness corrections that do not need Earth Engine."""

from __future__ import annotations

import inspect

import numpy as np
from rasterio.transform import rowcol
from shapely.geometry import LineString

from processing.bankline_compare import _cross_bank_hits, _pixel_m, compare_corridors
from processing.crs import load_crs
from processing.date_options import MIN_VALID_FRACTION, build_compare_request
from processing.live_extract import ROI, _base_grid, _roi_boundary_lonlat


def test_roi_boundary_lies_inside_albers_grid():
    transform, width, height, _grid = _base_grid()
    lons, lats = _roi_boundary_lonlat(0.05)
    assert lons[0] == ROI[0]
    bundle = load_crs()
    xs, ys = bundle.to_metre.transform(lons, lats)
    for x, y in zip(xs, ys):
        row, col = rowcol(transform, float(x), float(y))
        assert 0 <= col < width
        assert 0 <= row < height


def test_ambiguous_endpoint_cross_section_is_rejected():
    ring = LineString([(40, 8), (60, 8), (60, 4), (40, 4), (40, -4), (60, -4), (60, -8), (40, -8)])
    guide = LineString([(0, 0), (100, 0)])
    assert _cross_bank_hits(ring, guide, 50, 30) is None


def test_single_pair_endpoint_cross_section_is_kept():
    ring = LineString([(40, 300), (60, 300), (60, -300), (40, -300), (40, 300)])
    guide = LineString([(0, 0), (100, 0)])
    hit = _cross_bank_hits(ring, guide, 50, 500)
    assert hit is not None


def test_metric_pixel_size_is_the_affine_step():
    from rasterio.transform import from_origin

    transform = from_origin(0, 1000, 100, 100)
    assert _pixel_m(transform) == 100


def test_coverage_warning_uses_the_shared_threshold():
    source = inspect.getsource(compare_corridors)
    assert "MIN_VALID_FRACTION" in source
    assert ">= 0.6" not in source
    assert MIN_VALID_FRACTION == 0.70


def test_identify_uses_the_requested_sensor_and_mode(monkeypatch):
    seen = {}

    def fake_pair(req, staged=False, fetch_both_sensors=False):
        seen["sensor"] = req.sensor
        seen["mode"] = req.mode
        seen["later"] = req.later.label
        grid = {
            "height": 2,
            "width": 2,
            "bounds": {"west": 89.5, "south": 25.5, "east": 96.0, "north": 28.5},
            "transform": [100, 0, 0, 0, -100, 0],
            "crs": "Assam_Brahmaputra_Albers",
        }
        blank = np.zeros((2, 2), dtype=bool)
        return {
            "grid": grid,
            "erosion": blank,
            "deposition": blank,
            "earlier_body": blank,
            "later_body": blank,
            "valid": blank,
            "earlier": {"meta": {"label": req.earlier.label}},
            "later": {"meta": {"label": req.later.label}},
        }

    monkeypatch.setattr("processing.live_extract._pair_from_request", fake_pair)
    from processing.live_extract import period_identify

    req = build_compare_request(
        mode="periods",
        sensor="microwave",
        earlier_start="2019-11-01",
        earlier_end="2019-11-15",
        later_start="2024-11-01",
        later_end="2024-11-15",
    )
    result = period_identify(91.7, 26.1, request=req)
    assert seen["sensor"] == "microwave"
    assert seen["mode"] == "periods"
    assert "2024-11-01" in seen["later"]
    assert result["pixel_class"] in {"nodata", "outside"}
