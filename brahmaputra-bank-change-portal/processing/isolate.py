"""Turn a water-mask raster into river water, outer banks, and a centreline.

The search guide is only a corridor filter. Displayed geometry comes from water pixels.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import rasterio
from rasterio.features import rasterize, shapes
from shapely.geometry import LineString, MultiLineString, Point, Polygon, mapping, shape
from shapely.ops import linemerge, nearest_points, substring, unary_union
from skimage.morphology import closing, disk, remove_small_objects

from .crs import CrsBundle, to_lonlat
from .geometry import _fc, _feature, _line_to_lonlat, cross_sections, densify

SEARCH_BUFFER_M = 11_000.0
MIN_WATER_PIXELS = 40
CLOSE_PX = 2
SIMPLIFY_M = 40.0


def _to_lonlat_any(geom, bundle: CrsBundle):
    return to_lonlat(geom, bundle)


def _poly_fc(geom, bundle: CrsBundle, props: dict) -> dict:
    geom = geom.simplify(SIMPLIFY_M, preserve_topology=True)
    if geom.is_empty:
        return _fc([])
    gj = mapping(_to_lonlat_any(geom, bundle))
    return _fc([{"type": "Feature", "geometry": gj, "properties": props}])


def _line_fc(geom, bundle: CrsBundle, props: dict) -> dict:
    if geom.is_empty:
        return _fc([])
    if geom.geom_type == "MultiLineString":
        geom = max(geom.geoms, key=lambda g: g.length)
    geom = geom.simplify(SIMPLIFY_M, preserve_topology=True)
    return _fc([_feature(_line_to_lonlat(geom, bundle), props)])


def mask_to_polygons(mask: np.ndarray, transform) -> Any:
    feats = []
    for geom, value in shapes(mask.astype(np.uint8), mask=mask.astype(bool), transform=transform):
        if int(value) != 1:
            continue
        poly = shape(geom)
        if poly.area > 0:
            feats.append(poly)
    if not feats:
        return Polygon()
    return unary_union(feats)


def isolate_water(mask: np.ndarray, transform, guide_m: LineString) -> tuple[Any, np.ndarray]:
    """Keep water inside the search corridor; drop ponds that do not touch the belt."""
    h, w = mask.shape
    corridor = rasterize(
        [(guide_m.buffer(SEARCH_BUFFER_M), 1)],
        out_shape=(h, w),
        transform=transform,
        fill=0,
        dtype="uint8",
    ).astype(bool)
    water = (mask > 0) & corridor
    if CLOSE_PX:
        water = closing(water, footprint=disk(CLOSE_PX))
    water = remove_small_objects(water, min_size=MIN_WATER_PIXELS)
    return mask_to_polygons(water.astype(np.uint8), transform), water


def river_envelope(river_only, guide_m: LineString | None = None):
    if river_only.is_empty:
        return Polygon()
    closed = river_only.buffer(90).buffer(-90)
    if closed.is_empty:
        closed = river_only
    parts = closed.geoms if closed.geom_type == "MultiPolygon" else [closed]
    belt = guide_m.buffer(8000) if guide_m is not None else None
    filled = []
    for part in parts:
        if part.is_empty or part.area == 0:
            continue
        poly = Polygon(part.exterior)
        if belt is not None and not poly.intersects(belt):
            continue
        if poly.area < 4e5:
            continue
        filled.append(poly)
    if not filled:
        return Polygon()
    env = unary_union(filled).buffer(300).buffer(-300)
    return env


def _line_from_xy(samples: list[dict[str, Any]], lon_key: str, lat_key: str) -> LineString:
    coords = [(row[lon_key], row[lat_key]) for row in samples if lon_key in row and lat_key in row]
    if len(coords) < 2:
        return LineString()
    return LineString(coords)


def _pixel_xy(row: int, col: int, transform) -> tuple[float, float]:
    x, y = rasterio.transform.xy(transform, row, col, offset="center")
    return float(x), float(y)


def _xy_pixel(x: float, y: float, transform) -> tuple[int, int]:
    col, row = ~transform * (x, y)
    return int(round(row)), int(round(col))


def principal_centerline(envelope: Polygon, guide_m: LineString) -> LineString:
    """Midpoint of the water belt every 400 m along the search path."""
    coords = list(guide_m.coords)
    pts: list[tuple[float, float]] = []
    length = guide_m.length
    d = 0.0
    step = 400.0
    while d <= length + 1e-6:
        pt = guide_m.interpolate(min(d, length))
        i = min(int(d / max(length / max(len(coords) - 1, 1), 1.0)), len(coords) - 2)
        x0, y0 = coords[i]
        x1, y1 = coords[min(i + 1, len(coords) - 1)]
        tx, ty = x1 - x0, y1 - y0
        norm = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / norm, tx / norm
        ray = LineString(
            [
                (pt.x - nx * 20000.0, pt.y - ny * 20000.0),
                (pt.x + nx * 20000.0, pt.y + ny * 20000.0),
            ]
        )
        hit = ray.intersection(envelope)
        points: list[Point] = []
        if hit.is_empty:
            pass
        elif hit.geom_type == "Point":
            points = [hit]
        elif hit.geom_type == "MultiPoint":
            points = list(hit.geoms)
        elif hit.geom_type == "LineString":
            points = [Point(hit.coords[0]), Point(hit.coords[-1])]
        elif hit.geom_type == "MultiLineString":
            for part in hit.geoms:
                points.extend([Point(part.coords[0]), Point(part.coords[-1])])
        elif hit.geom_type == "GeometryCollection":
            for geom in hit.geoms:
                if geom.geom_type == "Point":
                    points.append(geom)
                elif geom.geom_type == "LineString" and geom.length > 0:
                    points.extend([Point(geom.coords[0]), Point(geom.coords[-1])])
        if len(points) >= 2:
            def side(p: Point) -> float:
                return (p.x - pt.x) * nx + (p.y - pt.y) * ny

            left = [p for p in points if side(p) > 0]
            right = [p for p in points if side(p) <= 0]
            if left and right:
                lp = max(left, key=lambda p: p.distance(pt))
                rp = max(right, key=lambda p: p.distance(pt))
                pts.append(((lp.x + rp.x) / 2.0, (lp.y + rp.y) / 2.0))
            elif pt.within(envelope):
                pts.append((pt.x, pt.y))
        elif pt.within(envelope):
            pts.append((pt.x, pt.y))
        d += step
    if len(pts) < 5:
        return densify(guide_m, 400)
    return densify(LineString(pts).simplify(80), 400)


def _as_line(geom, fallback: LineString) -> LineString:
    if isinstance(geom, LineString) and geom.length > 1:
        return geom
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString) and merged.length > 1:
            return merged
        if hasattr(merged, "geoms") and merged.geoms:
            return max((g for g in merged.geoms if isinstance(g, LineString)), key=lambda g: g.length, default=fallback)
    return fallback


def split_banks(envelope: Polygon, centerline_m: LineString) -> tuple[LineString, LineString]:
    ring = LineString(envelope.exterior.coords)
    fallback = ring
    up = Point(centerline_m.coords[0])
    down = Point(centerline_m.coords[-1])
    up_pt, _ = nearest_points(ring, up)
    down_pt, _ = nearest_points(ring, down)
    up_d = ring.project(up_pt)
    down_d = ring.project(down_pt)
    if up_d > down_d:
        up_d, down_d = down_d, up_d
    if abs(down_d - up_d) < 50:
        half = ring.length / 2.0
        arc_a = _as_line(substring(ring, 0.0, half, normalized=False), fallback)
        arc_b = _as_line(substring(ring, half, ring.length, normalized=False), fallback)
    else:
        arc_a = _as_line(substring(ring, up_d, down_d, normalized=False), fallback)
        arc_b = _as_line(
            unary_union(
                [
                    substring(ring, down_d, ring.length, normalized=False),
                    substring(ring, 0.0, up_d, normalized=False),
                ]
            ),
            fallback,
        )

    mid = centerline_m.interpolate(centerline_m.length * 0.5)
    dx = centerline_m.coords[-1][0] - centerline_m.coords[0][0]
    dy = centerline_m.coords[-1][1] - centerline_m.coords[0][1]
    left_vec = (-dy, dx)

    def side_score(line: LineString) -> float:
        if not isinstance(line, LineString) or line.length == 0:
            return -1e99
        p = line.interpolate(line.length / 2)
        return (p.x - mid.x) * left_vec[0] + (p.y - mid.y) * left_vec[1]

    left, right = (arc_a, arc_b) if side_score(arc_a) >= side_score(arc_b) else (arc_b, arc_a)
    return left, right


def geometry_from_mask(
    tif_path,
    guide_m: LineString,
    bundle: CrsBundle,
    epoch_date: str,
    frozen_centerline_m: LineString | None = None,
) -> dict[str, Any]:
    with rasterio.open(tif_path) as src:
        mask = src.read(1)
        transform = src.transform

    river_only, _ = isolate_water(mask, transform, guide_m)
    if river_only.is_empty:
        raise RuntimeError(f"No river water isolated for {epoch_date}")
    envelope = river_envelope(river_only, guide_m)
    if envelope.is_empty:
        envelope = river_only if river_only.geom_type == "Polygon" else max(river_only.geoms, key=lambda g: g.area)

    water_for_axis = unary_union(river_only)
    center = frozen_centerline_m or principal_centerline(water_for_axis, guide_m)
    env_for_split = envelope if getattr(envelope, "geom_type", "") == "Polygon" else (
        max(envelope.geoms, key=lambda g: g.area) if getattr(envelope, "geoms", None) else water_for_axis
    )
    if env_for_split.geom_type != "Polygon":
        env_for_split = Polygon(env_for_split.convex_hull.exterior)
    left, right = split_banks(env_for_split, center)
    sections, samples = cross_sections(center, water_for_axis, left, right, epoch_date, width_scale=1.0)
    sample_left = _line_from_xy(samples, "left_lon", "left_lat")
    sample_right = _line_from_xy(samples, "right_lon", "right_lat")
    if len(sample_left.coords) > 20:
        left_fc = _fc([{"type": "Feature", "geometry": mapping(sample_left.simplify(0.0004)), "properties": {"side": "left", "looking": "downstream"}}])
    else:
        left_fc = _line_fc(left, bundle, {"side": "left", "looking": "downstream"})
    if len(sample_right.coords) > 20:
        right_fc = _fc([{"type": "Feature", "geometry": mapping(sample_right.simplify(0.0004)), "properties": {"side": "right", "looking": "downstream"}}])
    else:
        right_fc = _line_fc(right, bundle, {"side": "right", "looking": "downstream"})

    return {
        "date": epoch_date,
        "river_only": _poly_fc(river_only, bundle, {"role": "river_water", "date": epoch_date}),
        "river_envelope": _poly_fc(envelope, bundle, {"role": "outer_water_boundary", "date": epoch_date}),
        "corridor_centerline": _line_fc(center, bundle, {"role": "channel_centre"}),
        "left_bank": left_fc,
        "right_bank": right_fc,
        "cross_sections": _fc(sections[::3]),  # display every 900 m
        "width_samples": samples,
        "envelope_m": envelope,
        "left_m": left,
        "right_m": right,
        "centerline_m": center,
        "river_only_m": river_only,
    }
