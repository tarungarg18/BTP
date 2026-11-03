"""Corridor isolation, envelope, centerline, endpoint-split banks, 300 m widths."""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import LineString, MultiLineString, Point, Polygon, mapping
from shapely.ops import linemerge, nearest_points, substring, unary_union

from .aoi import mainstem_line
from .crs import CrsBundle, load_crs, to_lonlat, to_metres

SECTION_STEP_M = 300.0
REACH_STEP_M = 5_000.0
ABNORMAL_WIDTH_M = 25_000.0


def _feature(geometry, properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "geometry": mapping(geometry), "properties": properties}


def _fc(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _line_to_lonlat(line: LineString, bundle: CrsBundle) -> LineString:
    return LineString([(round(x, 6), round(y, 6)) for x, y in to_lonlat(line, bundle).coords])


def _poly_to_lonlat(poly: Polygon, bundle: CrsBundle) -> Polygon:
    geom = to_lonlat(poly, bundle)
    if not isinstance(geom, Polygon):
        geom = max(geom.geoms, key=lambda g: g.area)
    return geom


def variable_half_width(chainage_m: float, length_m: float) -> float:
    t = chainage_m / max(length_m, 1.0)
    # Brahmaputra corridor is narrower at Guwahati-like mid-west, wider in braided east.
    return 1800 + 2200 * math.sin(math.pi * t) ** 2 + 400 * math.sin(6 * math.pi * t)


def build_envelope(centerline_m: LineString) -> Polygon:
    samples = []
    length = centerline_m.length
    step = 500.0
    d = 0.0
    while d <= length:
        pt = centerline_m.interpolate(d)
        samples.append(pt.buffer(variable_half_width(d, length)))
        d += step
    samples.append(centerline_m.interpolate(length).buffer(variable_half_width(length, length)))
    envelope = unary_union(samples).buffer(80).buffer(-80)
    if envelope.geom_type == "MultiPolygon":
        envelope = max(envelope.geoms, key=lambda g: g.area)
    return envelope


def split_banks(envelope: Polygon, centerline_m: LineString) -> tuple[LineString, LineString]:
    """Split the closed exterior at upstream/downstream nearest points."""
    ring = LineString(envelope.exterior.coords)
    up = Point(centerline_m.coords[0])
    down = Point(centerline_m.coords[-1])
    up_pt, _ = nearest_points(ring, up)
    down_pt, _ = nearest_points(ring, down)
    up_d = ring.project(up_pt)
    down_d = ring.project(down_pt)
    if up_d > down_d:
        up_d, down_d = down_d, up_d
        up, down = down, up

    arc_a = substring(ring, up_d, down_d, normalized=False)
    arc_b = unary_union(
        [
            substring(ring, down_d, ring.length, normalized=False),
            substring(ring, 0.0, up_d, normalized=False),
        ]
    )
    if isinstance(arc_b, MultiLineString):
        merged = linemerge(arc_b)
        arc_b = merged if isinstance(merged, LineString) else max(merged.geoms, key=lambda g: g.length)

    mid = centerline_m.interpolate(centerline_m.length * 0.5)
    dx = centerline_m.coords[-1][0] - centerline_m.coords[0][0]
    dy = centerline_m.coords[-1][1] - centerline_m.coords[0][1]
    # Left of downstream direction is (+ -dy, +dx).
    left_vec = (-dy, dx)

    def side_score(line: LineString) -> float:
        p = line.interpolate(line.length / 2)
        vx, vy = p.x - mid.x, p.y - mid.y
        return vx * left_vec[0] + vy * left_vec[1]

    left, right = (arc_a, arc_b) if side_score(arc_a) >= side_score(arc_b) else (arc_b, arc_a)
    return left, right


def densify(line: LineString, step_m: float) -> LineString:
    pts = []
    d = 0.0
    while d < line.length:
        pts.append(line.interpolate(d))
        d += step_m
    pts.append(line.interpolate(line.length))
    return LineString(pts)


def cross_sections(
    centerline_m: LineString,
    envelope: Polygon,
    left: LineString,
    right: LineString,
    epoch_date: str,
    width_scale: float = 1.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sections: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    length = centerline_m.length
    d = 0.0
    index = 0
    coords = list(centerline_m.coords)
    while d <= length + 1e-6:
        pt = centerline_m.interpolate(min(d, length))
        # Local tangent from nearby vertices.
        i = min(int(d / max(length / (len(coords) - 1), 1)), len(coords) - 2)
        x0, y0 = coords[i]
        x1, y1 = coords[min(i + 1, len(coords) - 1)]
        tx, ty = x1 - x0, y1 - y0
        norm = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / norm, tx / norm
        ray = LineString(
            [
                (pt.x - nx * ABNORMAL_WIDTH_M, pt.y - ny * ABNORMAL_WIDTH_M),
                (pt.x + nx * ABNORMAL_WIDTH_M, pt.y + ny * ABNORMAL_WIDTH_M),
            ]
        )
        hit = ray.intersection(envelope.exterior)
        qc = "ok"
        left_pt = None
        right_pt = None
        points = []
        if hit.is_empty:
            qc = "missing_intersection"
        else:
            if hit.geom_type == "Point":
                points = [hit]
            elif hit.geom_type == "MultiPoint":
                points = list(hit.geoms)
            elif hit.geom_type == "GeometryCollection":
                points = [g for g in hit.geoms if g.geom_type == "Point"]
            else:
                points = []
            if len(points) < 2:
                qc = "missing_intersection"
            elif len(points) > 4:
                qc = "multiple_intersections"
            if len(points) >= 2:
                def side(p):
                    return (p.x - pt.x) * nx + (p.y - pt.y) * ny

                left_candidates = [p for p in points if side(p) > 0]
                right_candidates = [p for p in points if side(p) <= 0]
                if not left_candidates or not right_candidates:
                    qc = "missing_intersection"
                else:
                    left_pt = max(left_candidates, key=lambda p: p.distance(pt))
                    right_pt = max(right_candidates, key=lambda p: p.distance(pt))

        width = None
        left_off = None
        right_off = None
        if left_pt is not None and right_pt is not None:
            width = left_pt.distance(right_pt) * width_scale
            left_off = left_pt.distance(pt) * width_scale
            right_off = right_pt.distance(pt) * width_scale
            if width > ABNORMAL_WIDTH_M:
                qc = "abnormal_width"
        elif qc == "ok":
            qc = "invalid"

        reach_id = f"R{int(d // REACH_STEP_M) + 1:03d}"
        lonlat = to_lonlat(pt, load_crs()) if False else None
        bundle = getattr(cross_sections, "_bundle", None)
        if bundle is None:
            bundle = load_crs()
            cross_sections._bundle = bundle  # type: ignore[attr-defined]
        ll = to_lonlat(pt, bundle)
        props = {
            "section_id": f"XS{index:05d}",
            "chainage_m": round(d, 1),
            "reach_id": reach_id,
            "width_m": None if width is None else round(width, 1),
            "left_offset_m": None if left_off is None else round(left_off, 1),
            "right_offset_m": None if right_off is None else round(right_off, 1),
            "lon": round(ll.x, 6),
            "lat": round(ll.y, 6),
            "epoch_date": epoch_date,
            "qc_flag": qc,
        }
        samples.append(props)
        geom = ray if left_pt is None else LineString(
            [
                (left_pt.x, left_pt.y) if left_pt else (pt.x, pt.y),
                (right_pt.x, right_pt.y) if right_pt else (pt.x, pt.y),
            ]
        )
        geom_ll = _line_to_lonlat(geom if geom.length > 0 else ray, bundle)
        sections.append(_feature(geom_ll, props))
        index += 1
        d += SECTION_STEP_M
    return sections, samples


def build_reference(bundle: CrsBundle | None = None) -> dict[str, Any]:
    bundle = bundle or load_crs()
    raw = densify(to_metres(mainstem_line(), bundle), 400)
    envelope = build_envelope(raw)
    left, right = split_banks(envelope, raw)
    sections, samples = cross_sections(raw, envelope, left, right, epoch_date="reference")
    reaches = []
    length = raw.length
    start = 0.0
    rid = 1
    while start < length:
        end = min(start + REACH_STEP_M, length)
        reaches.append(
            {
                "reach_id": f"R{rid:03d}",
                "chainage_start_m": round(start, 1),
                "chainage_end_m": round(end, 1),
            }
        )
        rid += 1
        start = end
    return {
        "crs_wkt": bundle.projected.to_wkt(),
        "length_m": round(length, 1),
        "pixel_m": 20.0,
        "section_step_m": SECTION_STEP_M,
        "centerline": _fc([_feature(_line_to_lonlat(raw, bundle), {"role": "reference_centerline"})]),
        "envelope": _fc([_feature(_poly_to_lonlat(envelope, bundle), {"role": "river_envelope"})]),
        "left_bank": _fc([_feature(_line_to_lonlat(left, bundle), {"side": "left", "looking": "downstream"})]),
        "right_bank": _fc([_feature(_line_to_lonlat(right, bundle), {"side": "right", "looking": "downstream"})]),
        "cross_sections": _fc(sections),
        "width_samples": samples,
        "reaches": reaches,
        "centerline_m": raw,
        "envelope_m": envelope,
        "left_m": left,
        "right_m": right,
    }


def epoch_geometry(reference: dict[str, Any], epoch_date: str, bank_shift_m: float) -> dict[str, Any]:
    bundle = load_crs()
    center = reference["centerline_m"]
    # Shift envelope outward on the left (south when flowing west) for a candidate retreat demo.
    envelope = reference["envelope_m"].buffer(bank_shift_m)
    left, right = split_banks(envelope, center)
    scale = 1.0 + (bank_shift_m / 4000.0)
    sections, samples = cross_sections(center, envelope, left, right, epoch_date, width_scale=scale)
    river_only = envelope.buffer(-350)
    if river_only.is_empty:
        river_only = envelope
    return {
        "date": epoch_date,
        "river_only": _fc([_feature(_poly_to_lonlat(river_only, bundle), {"role": "river_only"})]),
        "river_envelope": _fc([_feature(_poly_to_lonlat(envelope, bundle), {"role": "river_envelope"})]),
        "corridor_centerline": reference["centerline"],
        "left_bank": _fc([_feature(_line_to_lonlat(left, bundle), {"side": "left"})]),
        "right_bank": _fc([_feature(_line_to_lonlat(right, bundle), {"side": "right"})]),
        "cross_sections": _fc(sections),
        "width_samples": samples,
        "envelope_m": envelope,
        "left_m": left,
        "right_m": right,
    }
