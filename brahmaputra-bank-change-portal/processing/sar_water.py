"""Sentinel-1 GRD water extraction from VV/VH backscatter. Not MNDWI."""

from __future__ import annotations

# Typical IW GRD VV water is darker than land. Threshold is scene-tested.
DEFAULT_VV_DB_THRESHOLD = -16.0


def sar_water_mask(vv_db, valid_mask, threshold: float = DEFAULT_VV_DB_THRESHOLD):
    water = (vv_db < threshold) & valid_mask
    return water, {
        "method": "VV_backscatter_threshold",
        "threshold_db": threshold,
        "sensor_family": "sar",
    }
