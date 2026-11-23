import pytest

from processing.crs import ANALYSIS_CRS
from processing.date_options import ALGORITHM_VERSION, CLASSIFICATION, MASKING, build_compare_request


def test_mode_a_window_15():
    req = build_compare_request(mode="dates", earlier="2020-04-08", later="2020-04-22", window_days=15)
    assert req.earlier.start.isoformat() == "2020-03-25"
    assert req.earlier.end.isoformat() == "2020-04-08"
    assert req.later.start.isoformat() == "2020-04-08"
    assert req.later.end.isoformat() == "2020-04-22"


def test_mode_b_periods():
    req = build_compare_request(
        mode="periods",
        earlier_start="2020-02-01",
        earlier_end="2020-03-15",
        later_start="2021-02-01",
        later_end="2021-03-15",
        sensor="optical",
    )
    assert req.mode == "periods"
    assert req.earlier.label.startswith("2020-02-01")


def test_mode_b_adjacent_periods_ok():
    req = build_compare_request(
        mode="periods",
        earlier_start="2020-02-01",
        earlier_end="2020-03-15",
        later_start="2020-03-16",
        later_end="2020-04-30",
        sensor="optical",
    )
    assert req.later.start.isoformat() == "2020-03-16"
    assert req.earlier.end.isoformat() == "2020-03-15"


def test_mode_b_rejects_overlapping_periods():
    with pytest.raises(ValueError, match="must not overlap"):
        build_compare_request(
            mode="periods",
            earlier_start="2020-02-01",
            earlier_end="2020-03-15",
            later_start="2020-03-01",
            later_end="2020-04-30",
            sensor="optical",
        )


def test_optical_archive_floor():
    try:
        build_compare_request(mode="dates", earlier="2015-04-08", later="2020-04-08", sensor="optical")
        assert False, "expected archive rejection"
    except ValueError as exc:
        assert "2017-03-28" in str(exc)


def test_mode_a_reports_overlapping_windows():
    req = build_compare_request(mode="dates", earlier="2026-04-08", later="2026-04-22", window_days=15)
    assert req.overlap_days == 1
    assert req.as_dict()["overlap_note"]


def test_mode_a_no_overlap_when_windows_are_apart():
    req = build_compare_request(mode="dates", earlier="2020-04-15", later="2021-04-15", window_days=15)
    assert req.overlap_days == 0
    assert req.as_dict()["overlap_note"] is None


def test_cache_key_deterministic_and_complete():
    req = build_compare_request(mode="dates", earlier="2020-04-08", later="2020-04-22", sensor="microwave", window_days=30)
    key = req.cache_key(close_m=300, scale_m=100, crs=ANALYSIS_CRS)
    assert ALGORITHM_VERSION == "envv4"
    assert ALGORITHM_VERSION in key
    assert "sensor=microwave" in key
    assert "win=30" in key
    assert "close_m=300" in key
    assert f"class={CLASSIFICATION['microwave']}" in key
    assert f"mask={MASKING['microwave']}" in key
    assert "if False" not in key
    assert f"crs={ANALYSIS_CRS}" in key
    assert key == req.cache_key(close_m=300, scale_m=100, crs=ANALYSIS_CRS)
