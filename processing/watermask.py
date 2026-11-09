"""Extract the Brahmaputra from a binary water-mask GeoTIFF.

Same rule as Brahmaputra_River_Extraction.ipynb:
water pixels are value 1 (255 is nodata, not water), narrow links are opened
away, the largest component is kept, and nearby braids are recovered.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from scipy import ndimage as ndi
from skimage.morphology import disk, remove_small_objects

OPENING_RADIUS_M = 90
RECOVERY_DISTANCE_M = 750
MIN_PATCH_HA = 1.0
DISPLAY_STRIDE = 2
WATER_VALUE = 1
NODATA_VALUE = 255

NAME_RE = re.compile(
    r"^Brahmaputra_WaterMask_(\d{4})(?:_(PRE|POST))?(\(\d+\))?\.tif$",
    re.IGNORECASE,
)

SEASON_RANK = {"pre": 0, "annual": 1, "post": 2}
SEASON_LABEL = {"pre": "Pre-monsoon", "post": "Post-monsoon", "annual": "Annual"}
SEASON_SHORT = {"pre": "pre", "post": "post", "annual": "ann"}

RIVER_RGBA = (2, 132, 199, 220)
EARLIER_RGBA = (14, 116, 144, 150)
EROSION_RGBA = (225, 29, 72, 230)
DEPOSITION_RGBA = (217, 119, 6, 235)


def parse_mask_filename(name: str) -> dict | None:
    match = NAME_RE.fullmatch(name)
    if not match:
        return None
    year = int(match.group(1))
    season = (match.group(2) or "annual").lower()
    duplicate = match.group(3)
    copy_index = int(duplicate[1:-1]) if duplicate else 0
    mask_id = f"{year}-{season}" if copy_index == 0 else f"{year}-{season}-{copy_index}"
    label = f"{year} {SEASON_LABEL[season]}"
    short = f"{year} {SEASON_SHORT[season]}"
    if copy_index:
        label = f"{label} ({copy_index})"
        short = f"{short} ({copy_index})"
    return {
        "id": mask_id,
        "year": year,
        "season": season,
        "season_label": SEASON_LABEL[season],
        "copy_index": copy_index,
        "label": label,
        "short_label": short,
        "sort": (year, SEASON_RANK[season], copy_index),
    }


def pixel_metres(dataset) -> tuple[float, float]:
    if dataset.crs is None or not dataset.crs.is_geographic:
        raise ValueError("Water masks must be north-up geographic GeoTIFFs.")
    latitude = (dataset.bounds.top + dataset.bounds.bottom) / 2.0
    width_m = abs(dataset.transform.a) * 111_320 * np.cos(np.deg2rad(latitude))
    height_m = abs(dataset.transform.e) * 110_574
    return float(width_m), float(height_m)


def _radius_px(distance_m: float, pixel_m: float) -> int:
    return max(1, int(round(distance_m / pixel_m)))


def read_water(path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """Return water==1, observed (not nodata), and raster metadata."""
    with rasterio.open(path) as source:
        band = source.read(1)
        width_m, height_m = pixel_metres(source)
        bounds = source.bounds
        meta = {
            "width": source.width,
            "height": source.height,
            "pixel_width_m": round(width_m, 3),
            "pixel_height_m": round(height_m, 3),
            "pixel_km2": (width_m * height_m) / 1_000_000.0,
            "bounds": {
                "west": bounds.left,
                "south": bounds.bottom,
                "east": bounds.right,
                "north": bounds.top,
            },
        }
    water = band == WATER_VALUE
    observed = band != NODATA_VALUE
    return water, observed, meta


def extract_river(water: np.ndarray, pixel_m: float) -> np.ndarray:
    opening_px = _radius_px(OPENING_RADIUS_M, pixel_m)
    recovery_px = _radius_px(RECOVERY_DISTANCE_M, pixel_m)
    opened = ndi.binary_opening(water, structure=disk(opening_px))
    labels, _count = ndi.label(opened)
    del opened
    if labels.max() == 0:
        return np.zeros(water.shape, dtype=bool)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    main = labels == int(sizes.argmax())
    del labels
    distance = ndi.distance_transform_edt(~main)
    del main
    return (distance <= recovery_px) & water


def downsample_or(mask: np.ndarray, stride: int = DISPLAY_STRIDE) -> np.ndarray:
    height, width = mask.shape
    height -= height % stride
    width -= width % stride
    view = mask[:height, :width]
    return view.reshape(height // stride, stride, width // stride, stride).max(axis=(1, 3))


def write_mask_png(mask: np.ndarray, color: tuple[int, int, int, int], path: Path) -> None:
    small = downsample_or(mask)
    image = np.zeros((*small.shape, 4), dtype=np.uint8)
    image[small] = color
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image, mode="RGBA").save(path, format="PNG", compress_level=3)


def pack_mask(mask: np.ndarray) -> np.ndarray:
    return np.packbits(np.ascontiguousarray(mask).ravel())


def unpack_mask(packed: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    count = shape[0] * shape[1]
    flat = np.unpackbits(np.asarray(packed))[:count]
    return flat.reshape(shape).astype(bool)


def save_mask_cache(
    path: Path,
    river: np.ndarray,
    observed: np.ndarray,
    observed_full: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        river=pack_mask(river),
        observed=np.zeros(0, dtype=np.uint8) if observed_full else pack_mask(observed),
        shape=np.array(river.shape, dtype=np.int32),
        observed_full=np.array([1 if observed_full else 0], dtype=np.uint8),
    )


def load_mask_cache(path: Path) -> tuple[np.ndarray, np.ndarray, bool]:
    with np.load(path) as data:
        shape = (int(data["shape"][0]), int(data["shape"][1]))
        river = unpack_mask(data["river"], shape)
        observed_full = bool(int(data["observed_full"][0]))
        if observed_full:
            observed = np.ones(shape, dtype=bool)
        else:
            observed = unpack_mask(data["observed"], shape)
    return river, observed, observed_full


def change_masks(
    earlier: np.ndarray,
    later: np.ndarray,
    earlier_observed: np.ndarray,
    later_observed: np.ndarray,
    min_pixels: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    valid = earlier_observed & later_observed
    erosion = later & ~earlier & valid
    deposition = earlier & ~later & valid
    persistent = earlier & later & valid
    if erosion.any():
        erosion = remove_small_objects(erosion, min_size=min_pixels)
    if deposition.any():
        deposition = remove_small_objects(deposition, min_size=min_pixels)
    return erosion, deposition, persistent
