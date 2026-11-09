"""Fuse optical and SAR water only when observation times are close."""

from __future__ import annotations

from datetime import datetime, timedelta

MAX_FUSION_GAP = timedelta(days=2)


def can_fuse(optical_time: datetime, sar_time: datetime) -> bool:
    return abs(optical_time - sar_time) <= MAX_FUSION_GAP


def fuse(optical, sar, optical_valid, sar_valid):
    """Return fused mask and a disagreement flag array (boolean numpy-like)."""
    both = optical_valid & sar_valid
    fused = (optical & optical_valid) | (sar & sar_valid & ~optical_valid)
    disagree = both & (optical != sar)
    confidence = both & (optical == sar)
    return fused, disagree, confidence
