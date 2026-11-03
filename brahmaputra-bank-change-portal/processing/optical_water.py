"""Sentinel-2 / Landsat water extraction. Never used for Sentinel-1."""

from __future__ import annotations

# MNDWI = (Green - SWIR1) / (Green + SWIR1)
# Sentinel-2: B3 (10 m), B11 (20 m) → operational 20 m grid.
# Landsat: keep 30 m native grid.

DEFAULT_MNDWI_THRESHOLD = 0.1


def mndwi(green, swir1):
    return (green - swir1) / (green + swir1 + 1e-6)


def optical_water_mask(green, swir1, valid_mask, threshold: float = DEFAULT_MNDWI_THRESHOLD):
    water = (mndwi(green, swir1) > threshold) & valid_mask
    return water, {"method": "MNDWI", "threshold": threshold, "sensor_family": "optical"}
