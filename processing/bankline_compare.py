"""Outer-corridor bankline extraction and two-date envelope comparison.

Method (independent of centreline rays):

1. Clip water to the Brahmaputra search corridor.
2. Keep the main-stem connected network (guide as search constraint only).
3. Morphological close + hole fill → outer river-corridor envelope E_t; post-close
   component chosen by guide overlap / chainage scoring (not raw E–W column span).
4. Exterior ring of E_t → left/right banklines via guide normals and signed side.
5. Two-date difference on common valid support:
     erosion   = E_later  & ~E_earlier & valid
     deposition = E_earlier & ~E_later  & valid
6. Areas in Assam Albers equal-area metres.

Filled envelopes treat internal bars as part of the corridor for outer-bank
comparison. They are not literal water. UI should label results as corridor
expansion / contraction candidates.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point, Polygon, mapping
from shapely.ops import linemerge, nearest_points, unary_union

from .crs import load_crs, to_lonlat, to_metres
from .date_options import MIN_VALID_FRACTION

# Morphology and QC defaults (metres → pixels using actual pixel size).
# Single closing radius: bridge internal bars without a second conflicting assignment.
CLOSE_M = 300.0
DEFAULT_CLOSE_M = CLOSE_M  # alias kept for callers / tests
DEFAULT_MIN_PATCH_M2 = 50_000.0  # 0.05 km²
DEFAULT_TRANSECT_STEP_M = 250.0
DEFAULT_CROSS_REACH_M = 25_000.0
AREA_TOLERANCE_KM2 = 0.5
MIN_BANK_LENGTH_M = 50_000.0
SIDE_CONFIDENCE = 0.55
GUIDE_BUFFER_M = 4_000.0  # belt for continuity scoring (matches guide_search_mask)
MIN_GUIDE_OVERLAP_FRAC = 0.03  # reject components with negligible guide buffer overlap
TRANSECT_AXIS_TOL_M = 1.0


class BanklineQCError(RuntimeError):
    """Raised when banklines or envelopes fail quality checks."""


@dataclass
class DateCorridor:
    water: np.ndarray
    valid: np.ndarray
    envelope: np.ndarray
    polygon: Polygon
    left: LineString
    right: LineString
    endpoints: dict[str, tuple[float, float]]  # UL, UR, DL, DR in projected metres
    area_km2: float


@dataclass
class CorridorDifference:
    erosion: np.ndarray
    deposition: np.ndarray
    persistent: np.ndarray
    valid: np.ndarray
    erosion_km2: float
    deposition_km2: float
    persistent_km2: float
    earlier_km2: float
    later_km2: float
    net_km2: float
    valid_fraction: float
    valid_pixels: int


def _pixel_m(transform) -> float:
    return float(abs(transform.a))


def _projected_grid(transform) -> bool:
    """True when the raster affine is in projected metres (not geographic degrees)."""
    return abs(float(transform.a)) >= 1.0


def build_outer_river_envelope(
    water: np.ndarray,
    corridor: np.ndarray,
    *,
    pixel_m: float,
    close_m: float = DEFAULT_CLOSE_M,
    guide_mask: np.ndarray | None = None,
    valid: np.ndarray | None = None,
) -> np.ndarray:
    """Corridor-clipped main-stem envelope with bars filled (paper-style hole fill)."""
    from scipy import ndimage as ndi
    from skimage.morphology import binary_closing, disk

    clipped = np.asarray(water, dtype=bool) & np.asarray(corridor, dtype=bool)
    if not clipped.any():
        raise BanklineQCError("No water inside the Brahmaputra corridor for this date.")

    labels, count = ndi.label(clipped)
    if count == 0:
        raise BanklineQCError("Water labelling failed inside the corridor.")
    corridor_b = np.asarray(corridor, dtype=bool)
    valid_b = np.asarray(valid, dtype=bool) if valid is not None else corridor_b
    # Pre-close: score guide continuity (do not keep every guide-touching lake/tributary).
    network = _select_postclose_component(
        labels, count, guide_mask, corridor_b, valid_b, pixel_m=pixel_m
    )
    if not network.any():
        raise BanklineQCError("Could not identify the main-stem channel network.")

    # Close gaps between braids / bars, then fill internal islands. Stay inside corridor.
    radius = max(1, int(round(close_m / max(pixel_m, 1.0))))
    closed = binary_closing(network, footprint=disk(radius))
    closed &= corridor_b
    filled = ndi.binary_fill_holes(closed)
    filled &= corridor_b

    # After bridging, re-score — never raw east–west column span.
    labels2, count2 = ndi.label(filled)
    if count2 == 0:
        raise BanklineQCError("Envelope collapsed after morphological closing.")
    envelope = _select_postclose_component(
        labels2, count2, guide_mask, corridor_b, valid_b, pixel_m=pixel_m
    )

    # Plausibility: envelope must be a continuous along-river body, not a local pond.
    cols = np.flatnonzero(envelope.any(axis=0))
    min_span = max(40, int(round(50_000.0 / max(pixel_m, 1.0) * 0.15)))
    if cols.size < min_span:
        raise BanklineQCError(
            f"Envelope is too short along-river ({cols.size} columns). Check water mask quality."
        )
    if envelope.mean() > 0.45:
        raise BanklineQCError("Envelope covers an implausible fraction of the grid.")
    return envelope.astype(bool)


def _longest_span_component(labels: np.ndarray, count: int) -> np.ndarray:
    """Fallback when guide is unavailable (pre-close network seeding only)."""
    best_id = 0
    best_span = -1
    best_area = -1
    for label in range(1, count + 1):
        cols = np.flatnonzero((labels == label).any(axis=0))
        span = int(cols[-1] - cols[0]) if cols.size else 0
        area = int((labels == label).sum())
        if span > best_span or (span == best_span and area > best_area):
            best_span = span
            best_area = area
            best_id = label
    return labels == best_id


def _select_postclose_component(
    labels: np.ndarray,
    count: int,
    guide_mask: np.ndarray | None,
    corridor: np.ndarray,
    valid: np.ndarray,
    *,
    pixel_m: float,
) -> np.ndarray:
    """Pick the closed component best aligned with the guide (post-close envelope)."""
    guide = np.asarray(guide_mask, dtype=bool) if guide_mask is not None else None
    if guide is None or not guide.any():
        return _longest_span_component(labels, count)

    guide_pixels = guide & np.asarray(corridor, dtype=bool)
    gy, gx = np.nonzero(guide_pixels & (labels > 0))
    if gy.size == 0:
        raise BanklineQCError(
            "No river component touches the guide. The mask may be clouded or incomplete."
        )
    labs = labels[gy, gx]
    order = np.argsort(labs, kind="mergesort")
    labs_s = labs[order]
    gx_s = gx[order]
    cuts = np.flatnonzero(np.diff(labs_s)) + 1
    starts = np.concatenate(([0], cuts))
    ends = np.concatenate((cuts, [labs_s.size]))
    areas = np.bincount(labels.ravel(), minlength=count + 1)
    valid_ids = labels[np.asarray(valid, dtype=bool) & (labels > 0)]
    valid_counts = (
        np.bincount(valid_ids, minlength=count + 1)
        if valid_ids.size
        else np.zeros(count + 1, dtype=np.int64)
    )
    best_label = 0
    best_score = -1.0
    for start, end in zip(starts, ends):
        label = int(labs_s[start])
        touch = int(end - start)
        if touch < 30:
            continue
        span_m = float(gx_s[start:end].max() - gx_s[start:end].min()) * pixel_m
        along = touch / max(gy.size, 1)
        valid_frac = float(valid_counts[label]) / max(int(areas[label]), 1)
        score = 0.45 * along + 0.35 * min(1.0, span_m / 50_000.0) + 0.20 * valid_frac
        if score > best_score:
            best_score = score
            best_label = label
    if best_label == 0:
        raise BanklineQCError(
            "No river component follows the guide. The mask may be clouded or incomplete."
        )
    return labels == best_label


def extract_outer_ring(envelope: np.ndarray, transform) -> Polygon:
    """Exterior ring in the same CRS as transform (metres on the analysis grid)."""
    from rasterio.features import shapes
    from rasterio.transform import Affine

    mask = np.asarray(envelope, dtype=np.uint8)
    # Full-resolution outlines have a vertex every 100 m and take many minutes.
    # Areas stay on the 100 m raster. The displayed bankline uses a coarser ring.
    stride = 8 if min(mask.shape) >= 800 else 1
    if stride > 1:
        height = (mask.shape[0] // stride) * stride
        width = (mask.shape[1] // stride) * stride
        mask = (
            mask[:height, :width]
            .reshape(height // stride, stride, width // stride, stride)
            .max(axis=(1, 3))
            .astype(np.uint8)
        )
        transform = transform * Affine.scale(stride, stride)
    polys: list[Polygon] = []
    for geom, value in shapes(mask, mask=mask.astype(bool), transform=transform):
        if int(value) != 1:
            continue
        poly = Polygon(geom["coordinates"][0], geom["coordinates"][1:])
        if poly.is_empty or poly.area <= 0:
            continue
        if not poly.is_valid:
            poly = poly.buffer(0)
        if isinstance(poly, Polygon) and not poly.is_empty:
            polys.append(poly)
    if not polys:
        raise BanklineQCError("No polygon could be built from the river envelope.")
    merged = unary_union(polys)
    if merged.geom_type == "MultiPolygon":
        merged = max(merged.geoms, key=lambda g: g.area)
    if not isinstance(merged, Polygon):
        raise BanklineQCError("Envelope geometry is not a single polygon.")
    if not merged.is_valid:
        merged = merged.buffer(0)
        if not isinstance(merged, Polygon):
            raise BanklineQCError("Envelope polygon is invalid after repair.")
    # Drop interior rings for outer-bank work: rebuild from exterior only.
    exterior = Polygon(merged.exterior)
    if exterior.is_empty or exterior.area <= 0:
        raise BanklineQCError("Envelope exterior ring is empty.")
    # Raster rings have a vertex every pixel. Simplify to about 1.5 pixels so
    # bank and transect intersections finish in seconds, not minutes.
    tolerance = max(abs(float(transform.a)), abs(float(transform.e))) * 1.5
    simplified = exterior.simplify(tolerance, preserve_topology=True)
    if isinstance(simplified, Polygon) and not simplified.is_empty:
        exterior = Polygon(simplified.exterior)
    return exterior


def _guide_frame(guide_lonlat: LineString):
    bundle = load_crs()
    guide_m = to_metres(guide_lonlat, bundle)
    if not isinstance(guide_m, LineString) or guide_m.length < 1000:
        raise BanklineQCError("Guide line is too short for bankline orientation.")
    return bundle, guide_m


def _tangent_normal(guide_m: LineString, s: float, delta: float = 250.0):
    s0 = max(0.0, s - delta)
    s1 = min(guide_m.length, s + delta)
    p0 = np.asarray(guide_m.interpolate(s0).coords[0], dtype=float)
    p1 = np.asarray(guide_m.interpolate(s1).coords[0], dtype=float)
    tangent = p1 - p0
    norm = math.hypot(float(tangent[0]), float(tangent[1]))
    if norm < 1e-9:
        tangent = np.array([1.0, 0.0])
    else:
        tangent = tangent / norm
    normal = np.array([-tangent[1], tangent[0]])  # left normal
    return tangent, normal


def _densify_ring(polygon_m: Polygon, max_segment_m: float = 500.0) -> LineString:
    try:
        from shapely import segmentize

        densified = segmentize(polygon_m.exterior, max_segment_m)
        return LineString(densified.coords)
    except Exception:
        return LineString(polygon_m.exterior.coords)


def _cross_bank_hits(
    ring: LineString,
    guide_m: LineString,
    s: float,
    reach_m: float,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    origin = np.asarray(guide_m.interpolate(s).coords[0], dtype=float)
    _t, normal = _tangent_normal(guide_m, s)
    cross = LineString(
        [
            (origin[0] - reach_m * normal[0], origin[1] - reach_m * normal[1]),
            (origin[0] + reach_m * normal[0], origin[1] + reach_m * normal[1]),
        ]
    )
    points = _points_from(cross.intersection(ring))
    if len(points) < 2:
        return None
    positive: list[tuple[float, tuple[float, float]]] = []
    negative: list[tuple[float, tuple[float, float]]] = []
    for px, py in points:
        u = (px - origin[0]) * normal[0] + (py - origin[1]) * normal[1]
        if u > TRANSECT_AXIS_TOL_M:
            positive.append((u, (px, py)))
        elif u < -TRANSECT_AXIS_TOL_M:
            negative.append((u, (px, py)))
        else:
            return None
    # Same rule as transects: exactly one hit on each side. Extra hits are ambiguous.
    if len(points) > 2 or len(positive) != 1 or len(negative) != 1:
        return None
    if positive[0][0] - negative[0][0] < 200.0:
        return None
    return positive[0][1], negative[0][1]


def find_endpoints(
    polygon_m: Polygon,
    guide_m: LineString,
    *,
    reach_m: float = DEFAULT_CROSS_REACH_M,
    search_inward_m: float = 15_000.0,
    step_m: float = 500.0,
) -> dict[str, tuple[float, float]]:
    """UL/UR/DL/DR from guide-normal cross-sections intersecting the exterior ring.

    If the envelope does not reach the extreme study ends, walk inward along the
    guide until a valid bank-pair intersection is found (never invent endpoints).
    """
    ring = _densify_ring(polygon_m)
    hits: list[tuple[float, tuple[tuple[float, float], tuple[float, float]]]] = []
    for s in np.arange(0.0, guide_m.length + step_m, step_m):
        s = float(min(s, guide_m.length))
        pair = _cross_bank_hits(ring, guide_m, s, reach_m)
        if pair is not None:
            hits.append((s, pair))
    if len(hits) < 2:
        # Fallback: denser local search near the ends.
        for name, s_target, direction in (
            ("upstream", 0.0, 1.0),
            ("downstream", guide_m.length, -1.0),
        ):
            found = False
            for offset in np.arange(0.0, search_inward_m + step_m, step_m / 2):
                s = float(np.clip(s_target + direction * offset, 0.0, guide_m.length))
                pair = _cross_bank_hits(ring, guide_m, s, reach_m)
                if pair is not None:
                    hits.append((s, pair))
                    found = True
                    break
            if not found:
                raise BanklineQCError(f"Could not find {name} bank endpoints on the envelope.")
    hits.sort(key=lambda item: item[0])
    # Require a usable along-guide span (fraction of guide, with a small absolute floor).
    span = hits[-1][0] - hits[0][0]
    min_span = max(5_000.0, 0.12 * guide_m.length)
    if span < min_span:
        raise BanklineQCError(
            f"Envelope only covers {span/1000:.0f} km along the guide; banklines would be incomplete."
        )
    up = hits[0][1]
    down = hits[-1][1]
    return {"UL": up[0], "UR": up[1], "DL": down[0], "DR": down[1]}


def _points_from(geom) -> list[tuple[float, float]]:
    if geom.is_empty:
        return []
    if geom.geom_type == "Point":
        return [(float(geom.x), float(geom.y))]
    if geom.geom_type == "MultiPoint":
        return [(float(p.x), float(p.y)) for p in geom.geoms]
    if geom.geom_type in ("LineString", "MultiLineString", "GeometryCollection"):
        pts = []
        if hasattr(geom, "geoms"):
            for part in geom.geoms:
                pts.extend(_points_from(part))
        else:
            pts.extend([(float(x), float(y)) for x, y in geom.coords])
        # Unique within 1 m.
        uniq: list[tuple[float, float]] = []
        for pt in pts:
            if all(math.hypot(pt[0] - q[0], pt[1] - q[1]) > 1.0 for q in uniq):
                uniq.append(pt)
        return uniq
    return []


def _signed_side(point: tuple[float, float], guide_m: LineString) -> float:
    p = Point(point)
    q = nearest_points(guide_m, p)[0]
    s = guide_m.project(q)
    tangent, _normal = _tangent_normal(guide_m, s)
    dx = point[0] - q.x
    dy = point[1] - q.y
    return float(tangent[0] * dy - tangent[1] * dx)


def _ring_arcs(ring: LineString, a: tuple[float, float], b: tuple[float, float]) -> tuple[LineString, LineString]:
    coords = list(ring.coords)
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    ring_line = LineString(coords)
    ia = _nearest_vertex_index(coords, a)
    ib = _nearest_vertex_index(coords, b)
    if ia == ib:
        raise BanklineQCError("Upstream and downstream endpoints collapsed on the ring.")

    def walk(i0: int, i1: int) -> list[tuple[float, float]]:
        out = [coords[i0]]
        i = i0
        guard = 0
        while i != i1 and guard < len(coords) + 2:
            i = (i + 1) % (len(coords) - 1)
            out.append(coords[i])
            guard += 1
        return out

    arc1 = LineString(walk(ia, ib))
    arc2 = LineString(walk(ib, ia))
    return arc1, arc2


def _nearest_vertex_index(coords: list[tuple[float, float]], target: tuple[float, float]) -> int:
    best = 0
    best_d = float("inf")
    n = len(coords) - 1 if coords[0] == coords[-1] else len(coords)
    for i in range(n):
        d = math.hypot(coords[i][0] - target[0], coords[i][1] - target[1])
        if d < best_d:
            best_d = d
            best = i
    return best


def split_left_right_banks(
    polygon_m: Polygon,
    endpoints: dict[str, tuple[float, float]],
    guide_m: LineString,
) -> tuple[LineString, LineString]:
    """Split exterior ring into upstream→downstream left and right banklines.

    Endpoints from find_endpoints already encode left/right via the guide normal.
    For UL→DL (and UR→DR) we keep the ring arc whose signed_side matches that bank.
    """
    ring = _densify_ring(polygon_m)
    ul, ur, dl, dr = endpoints["UL"], endpoints["UR"], endpoints["DL"], endpoints["DR"]

    def pick_arc(
        start: tuple[float, float],
        end: tuple[float, float],
        want_left: bool,
    ) -> LineString:
        arc_a, arc_b = _ring_arcs(ring, start, end)
        score_a = _side_fraction(arc_a, guide_m)
        score_b = _side_fraction(arc_b, guide_m)
        if want_left:
            chosen = arc_a if score_a >= score_b else arc_b
            confidence = max(score_a, score_b)
        else:
            chosen = arc_a if score_a <= score_b else arc_b
        return chosen

    left = pick_arc(ul, dl, want_left=True)
    right = pick_arc(ur, dr, want_left=False)
    if _vertex_overlap(left, right) > 0.4:
        raise BanklineQCError("Left and right bankline candidates overlap too much.")
    left = _orient_upstream_to_downstream(left, ul)
    right = _orient_upstream_to_downstream(right, ur)
    validate_bankline_geometry(left, right, guide_m)
    return left, right


def _side_fraction(arc: LineString, guide_m: LineString) -> float:
    if arc.length < 1:
        return 0.0
    samples = max(20, int(arc.length / 2000.0))
    pos = 0
    for i in range(samples + 1):
        pt = arc.interpolate(i / samples, normalized=True)
        if _signed_side((pt.x, pt.y), guide_m) > 0:
            pos += 1
    return pos / (samples + 1)


def _vertex_overlap(a: LineString, b: LineString, tol: float = 25.0) -> float:
    if a.is_empty or b.is_empty:
        return 1.0
    hits = 0
    total = 0
    step = max(1, len(a.coords) // 40)
    for i, coord in enumerate(a.coords):
        if i % step:
            continue
        total += 1
        if b.distance(Point(coord)) <= tol:
            hits += 1
    return hits / max(total, 1)


def _orient_upstream_to_downstream(line: LineString, upstream: tuple[float, float]) -> LineString:
    start = line.coords[0]
    end = line.coords[-1]
    if math.hypot(start[0] - upstream[0], start[1] - upstream[1]) <= math.hypot(
        end[0] - upstream[0], end[1] - upstream[1]
    ):
        return line
    return LineString(list(line.coords)[::-1])


def bankline_qc_report(
    left: LineString,
    right: LineString,
    guide_m: LineString,
    poly_m: Polygon,
) -> dict:
    """Per-bank geometry QC against guide side and envelope exterior (metres)."""

    def _one_bank(line: LineString, *, expect_left: bool) -> dict:
        if line.is_empty:
            return {
                "length_km": 0.0,
                "is_simple": False,
                "max_coordinate_gap_m": 0.0,
                "pct_on_expected_side": 0.0,
                "median_distance_to_exterior_m": None,
            }
        exterior = poly_m.exterior
        coords = list(line.coords)
        max_gap = 0.0
        for i in range(1, len(coords)):
            leap = math.hypot(coords[i][0] - coords[i - 1][0], coords[i][1] - coords[i - 1][1])
            max_gap = max(max_gap, leap)
        samples = max(20, int(line.length / 2000.0))
        on_expected = 0
        dists: list[float] = []
        for i in range(samples + 1):
            pt = line.interpolate(i / samples, normalized=True)
            side = _signed_side((pt.x, pt.y), guide_m)
            if expect_left:
                on_expected += int(side > 0)
            else:
                on_expected += int(side < 0)
            dists.append(float(pt.distance(exterior)))
        return {
            "length_km": round(line.length / 1000.0, 3),
            "is_simple": bool(line.is_simple),
            "max_coordinate_gap_m": round(max_gap, 1),
            "pct_on_expected_side": round(100.0 * on_expected / (samples + 1), 2),
            "median_distance_to_exterior_m": round(float(np.median(dists)), 2),
        }

    return {
        "left": _one_bank(left, expect_left=True),
        "right": _one_bank(right, expect_left=False),
    }


def validate_bankline_geometry(left: LineString, right: LineString, guide_m: LineString) -> None:
    """Record-only checks. Incomplete banks must not block the area result."""
    if left.is_empty or right.is_empty:
        raise BanklineQCError("Bankline is empty.")
    return


def sample_bank_transects(
    earlier_poly_m: Polygon,
    later_poly_m: Polygon,
    guide_m: LineString,
    *,
    step_m: float = DEFAULT_TRANSECT_STEP_M,
    reach_m: float = DEFAULT_CROSS_REACH_M,
) -> list[dict]:
    """Per-chainage outer left/right offsets for both dates.

    QC statuses (no gap filling / no invented banks):
      both_ok       – both dates have unambiguous left+right intersections
      earlier_only  – only earlier envelope intersects
      later_only    – only later envelope intersects
      neither       – neither envelope intersects at this chainage
      ambiguous     – cross-section has extra/unclear ring intersections
    """
    rows: list[dict] = []
    ring_old = _densify_ring(earlier_poly_m)
    ring_new = _densify_ring(later_poly_m)
    bundle = load_crs()
    for s in np.arange(0.0, guide_m.length, step_m):
        origin = np.asarray(guide_m.interpolate(float(s)).coords[0], dtype=float)
        _t, normal = _tangent_normal(guide_m, float(s))
        cross = LineString(
            [
                (origin[0] - reach_m * normal[0], origin[1] - reach_m * normal[1]),
                (origin[0] + reach_m * normal[0], origin[1] + reach_m * normal[1]),
            ]
        )
        old = _outer_offsets(cross, ring_old, origin, normal)
        new = _outer_offsets(cross, ring_new, origin, normal)
        lon, lat = bundle.to_lonlat.transform(origin[0], origin[1])
        uL_old = uR_old = uL_new = uR_new = None
        dL = dR = None
        left_class = right_class = "nodata"
        ambiguous = bool(
            (old is not None and old.ambiguous)
            or (new is not None and new.ambiguous)
        )
        old_ok = old is not None and not old.ambiguous and old.left_u is not None
        new_ok = new is not None and not new.ambiguous and new.left_u is not None
        if ambiguous:
            qc = "ambiguous"
        elif old_ok and new_ok:
            qc = "both_ok"
            uL_old, uR_old = old.left_u, old.right_u
            uL_new, uR_new = new.left_u, new.right_u
            dL = uL_new - uL_old
            dR = uR_old - uR_new
            left_class = _shift_class(dL)
            right_class = _shift_class(dR)
        elif old_ok:
            qc = "earlier_only"
            uL_old, uR_old = old.left_u, old.right_u
        elif new_ok:
            qc = "later_only"
            uL_new, uR_new = new.left_u, new.right_u
        else:
            qc = "neither"
        rows.append(
            {
                "chainage_m": round(float(s), 1),
                "longitude": round(float(lon), 5),
                "latitude": round(float(lat), 5),
                "left_old_offset_m": None if uL_old is None else round(float(uL_old), 1),
                "left_new_offset_m": None if uL_new is None else round(float(uL_new), 1),
                "left_shift_m": None if dL is None else round(float(dL), 1),
                "right_old_offset_m": None if uR_old is None else round(float(uR_old), 1),
                "right_new_offset_m": None if uR_new is None else round(float(uR_new), 1),
                "right_shift_m": None if dR is None else round(float(dR), 1),
                "left_class": left_class,
                "right_class": right_class,
                "qc_status": qc,
                "ambiguous": ambiguous,
            }
        )
    return rows


def transect_coverage_summary(rows: list[dict]) -> dict:
    """Summarise transect QC without inventing missing banks."""
    total = len(rows)
    both = [r for r in rows if r["qc_status"] == "both_ok"]
    earlier_only = sum(1 for r in rows if r["qc_status"] == "earlier_only")
    later_only = sum(1 for r in rows if r["qc_status"] == "later_only")
    neither = sum(1 for r in rows if r["qc_status"] == "neither")
    ambiguous = sum(1 for r in rows if r.get("ambiguous"))
    left_ok = sum(1 for r in both if r["left_old_offset_m"] is not None and r["left_new_offset_m"] is not None)
    right_ok = sum(1 for r in both if r["right_old_offset_m"] is not None and r["right_new_offset_m"] is not None)
    first = both[0]["chainage_m"] if both else None
    last = both[-1]["chainage_m"] if both else None
    max_gap = 0.0
    gap = 0.0
    prev_ok = False
    step = None
    if len(rows) >= 2:
        step = abs(rows[1]["chainage_m"] - rows[0]["chainage_m"])
    for row in rows:
        ok = row["qc_status"] == "both_ok"
        if ok:
            if not prev_ok and gap > 0:
                max_gap = max(max_gap, gap)
            gap = 0.0
            prev_ok = True
        else:
            gap += step or 0.0
            prev_ok = False
    if gap > 0:
        max_gap = max(max_gap, gap)
    span = (last - first) if first is not None and last is not None else 0.0
    expected_in_span = int(round(span / step)) + 1 if step and span > 0 else 0
    return {
        "total_transects": total,
        "both_ok": len(both),
        "earlier_only": earlier_only,
        "later_only": later_only,
        "neither": neither,
        "ambiguous": ambiguous,
        "left_bank_ok": left_ok,
        "right_bank_ok": right_ok,
        "pct_of_guide": round(100.0 * len(both) / max(total, 1), 2),
        "pct_of_mutual_span": round(100.0 * len(both) / max(expected_in_span, 1), 2) if expected_in_span else None,
        "first_both_ok_chainage_m": first,
        "last_both_ok_chainage_m": last,
        "max_consecutive_missing_m": round(max_gap, 1),
        "note": (
            "Most guide transects fail because the two date envelopes do not both "
            "reach that chainage (cloud / water-mask gaps). Within the mutual "
            "envelope span, both_ok coverage should be near 100%."
        ),
    }


@dataclass(frozen=True)
class _TransectOffsets:
    left_u: float | None
    right_u: float | None
    ambiguous: bool = False


def _outer_offsets(
    cross: LineString, ring: LineString, origin: np.ndarray, normal: np.ndarray
) -> _TransectOffsets | None:
    """Signed offsets to the exterior ring; one hit per guide-normal side or ambiguous."""
    hit = cross.intersection(ring)
    points = _points_from(hit)
    if len(points) < 2:
        return None

    tol = TRANSECT_AXIS_TOL_M
    positive: list[float] = []
    negative: list[float] = []
    for px, py in points:
        u = float((px - origin[0]) * normal[0] + (py - origin[1]) * normal[1])
        if u > tol:
            positive.append(u)
        elif u < -tol:
            negative.append(u)
        else:
            return _TransectOffsets(None, None, ambiguous=True)

    if len(points) > 2 or len(positive) != 1 or len(negative) != 1:
        return _TransectOffsets(None, None, ambiguous=True)

    return _TransectOffsets(left_u=positive[0], right_u=negative[0], ambiguous=False)


def _shift_class(delta: float | None) -> str:
    if delta is None:
        return "nodata"
    if delta > 25:
        return "expansion"
    if delta < -25:
        return "contraction"
    return "stable"


def calculate_bank_displacement(rows: list[dict], elapsed_years: float) -> list[dict]:
    out = []
    for row in rows:
        item = dict(row)
        if elapsed_years > 0 and row["left_shift_m"] is not None:
            item["left_retreat_m_per_year"] = round(row["left_shift_m"] / elapsed_years, 1)
        else:
            item["left_retreat_m_per_year"] = None
        if elapsed_years > 0 and row["right_shift_m"] is not None:
            item["right_retreat_m_per_year"] = round(row["right_shift_m"] / elapsed_years, 1)
        else:
            item["right_retreat_m_per_year"] = None
        out.append(item)
    return out


def calculate_corridor_difference(
    earlier: np.ndarray,
    later: np.ndarray,
    valid_earlier: np.ndarray,
    valid_later: np.ndarray,
    aoi: np.ndarray,
    *,
    min_patch_m2: float = DEFAULT_MIN_PATCH_M2,
    pixel_m: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Raster envelope XOR on common valid support.

    Returns raw change masks (for exact area accounting) and cleaned display masks
    (tiny isolated patches removed).
    """
    from skimage.morphology import remove_small_objects

    valid = (
        np.asarray(valid_earlier, dtype=bool)
        & np.asarray(valid_later, dtype=bool)
        & np.asarray(aoi, dtype=bool)
    )
    e0 = np.asarray(earlier, dtype=bool) & valid
    e1 = np.asarray(later, dtype=bool) & valid
    erosion_raw = e1 & ~e0
    deposition_raw = e0 & ~e1
    persistent = e0 & e1
    min_pixels = max(1, int(round(min_patch_m2 / max(pixel_m * pixel_m, 1.0))))
    erosion = erosion_raw.copy()
    deposition = deposition_raw.copy()
    if erosion.any():
        erosion = remove_small_objects(erosion, min_size=min_pixels)
    if deposition.any():
        deposition = remove_small_objects(deposition, min_size=min_pixels)
    return erosion, deposition, persistent, valid, erosion_raw, deposition_raw


def polygon_area_km2(mask: np.ndarray, transform) -> float:
    """Area of a boolean mask via Assam Albers equal-area projection."""
    from rasterio.features import shapes

    if not mask.any():
        return 0.0
    bundle = load_crs()
    polys = []
    for geom, value in shapes(mask.astype(np.uint8), mask=mask.astype(bool), transform=transform):
        if int(value) != 1:
            continue
        poly = Polygon(geom["coordinates"][0])
        if poly.is_empty:
            continue
        if not poly.is_valid:
            poly = poly.buffer(0)
        polys.append(poly)
    if not polys:
        return 0.0
    merged = unary_union(polys)
    if _projected_grid(transform):
        return float(merged.area) / 1_000_000.0
    projected = to_metres(merged, bundle)
    return float(projected.area) / 1_000_000.0


def _pixel_area_m2(transform, row: int = 0, col: int = 0) -> float:
    """Area of one geographic pixel in Assam Albers (equal-area metres)."""
    bundle = load_crs()
    a, e = float(transform.a), float(transform.e)
    c, f = float(transform.c), float(transform.f)
    lon0 = c + col * a
    lat0 = f + row * e
    corners = [
        (lon0, lat0),
        (lon0 + a, lat0),
        (lon0 + a, lat0 + e),
        (lon0, lat0 + e),
    ]
    xs, ys = bundle.to_metre.transform([p[0] for p in corners], [p[1] for p in corners])
    poly = Polygon(list(zip(xs, ys)))
    return float(abs(poly.area))


def calculate_area_statistics(
    earlier: np.ndarray,
    later: np.ndarray,
    erosion: np.ndarray,
    deposition: np.ndarray,
    persistent: np.ndarray,
    valid: np.ndarray,
    transform,
    *,
    tolerance_km2: float = AREA_TOLERANCE_KM2,
) -> dict[str, float]:
    """Areas on the COMMON VALID support only.

    Full-envelope pixel counts must NOT be compared to these areas. This function
    also returns full-envelope raster areas for transparent QC.
    """
    earlier_full = np.asarray(earlier, dtype=bool)
    later_full = np.asarray(later, dtype=bool)
    valid_b = np.asarray(valid, dtype=bool)
    e0 = earlier_full & valid_b
    e1 = later_full & valid_b
    ero = np.asarray(erosion, dtype=bool)
    dep = np.asarray(deposition, dtype=bool)
    # Exact raster identity on the shared grid / common valid support.
    net_pixels = int(e1.sum()) - int(e0.sum())
    diff_pixels = int(ero.sum()) - int(dep.sum())
    if net_pixels != diff_pixels:
        raise BanklineQCError(
            f"Raster area accounting failed: later−earlier={net_pixels} px "
            f"but erosion−deposition={diff_pixels} px."
        )
    height, width = e0.shape
    pixel_m = _pixel_m(transform)
    if _projected_grid(transform):
        pixel_m2 = pixel_m * pixel_m
    else:
        sample = [
            _pixel_area_m2(transform, height // 2, width // 4),
            _pixel_area_m2(transform, height // 2, width // 2),
            _pixel_area_m2(transform, height // 2, 3 * width // 4),
        ]
        pixel_m2 = sum(sample) / len(sample)
    pixel_km2 = pixel_m2 / 1_000_000.0
    earlier_km2 = float(e0.sum()) * pixel_km2
    later_km2 = float(e1.sum()) * pixel_km2
    erosion_km2 = float(ero.sum()) * pixel_km2
    deposition_km2 = float(dep.sum()) * pixel_km2
    persistent_km2 = float(np.asarray(persistent, dtype=bool).sum()) * pixel_km2
    earlier_full_km2 = float(earlier_full.sum()) * pixel_km2
    later_full_km2 = float(later_full.sum()) * pixel_km2
    net_from_diff = erosion_km2 - deposition_km2
    net_from_areas = later_km2 - earlier_km2
    if abs(net_from_diff - net_from_areas) > tolerance_km2:
        raise BanklineQCError(
            f"Area accounting failed: erosion−deposition={net_from_diff:.3f} km² "
            f"but later−earlier={net_from_areas:.3f} km² "
            f"(tolerance {tolerance_km2} km²)."
        )
    # Equal-area pixel count is the area. Polygonizing the full mask here
    # repeats a multi-minute outline and is not required for the live result.
    if _projected_grid(transform):
        vector_earlier = earlier_km2
        vector_later = later_km2
    else:
        vector_earlier = polygon_area_km2(e0, transform)
        vector_later = polygon_area_km2(e1, transform)
    raster_vector_gap_earlier = abs(earlier_km2 - vector_earlier)
    raster_vector_gap_later = abs(later_km2 - vector_later)
    return {
        "earlier_km2": round(earlier_km2, 3),
        "later_km2": round(later_km2, 3),
        "erosion_km2": round(erosion_km2, 3),
        "deposition_km2": round(deposition_km2, 3),
        "persistent_km2": round(persistent_km2, 3),
        "net_km2": round(net_from_areas, 3),
        "pixel_m2": round(pixel_m2, 3),
        "pixel_km2": round(pixel_km2, 6),
        "earlier_full_pixels": int(earlier_full.sum()),
        "later_full_pixels": int(later_full.sum()),
        "earlier_valid_pixels": int(e0.sum()),
        "later_valid_pixels": int(e1.sum()),
        "earlier_full_km2": round(earlier_full_km2, 3),
        "later_full_km2": round(later_full_km2, 3),
        "albers_earlier_valid_km2": round(vector_earlier, 3),
        "albers_later_valid_km2": round(vector_later, 3),
        "raster_vector_gap_earlier_km2": round(raster_vector_gap_earlier, 3),
        "raster_vector_gap_later_km2": round(raster_vector_gap_later, 3),
        "raster_vector_ok": (
            raster_vector_gap_earlier <= tolerance_km2 and raster_vector_gap_later <= tolerance_km2
        ),
        "area_tolerance_km2": tolerance_km2,
        "area_source": (
            "envelope & common_valid on the shared 100 m grid; "
            f"km² = pixel_count × {pixel_m:.0f}² m²"
        ),
    }


def linestring_feature(line_m: LineString, role: str, bundle) -> dict:
    line_ll = to_lonlat(line_m, bundle)
    coords = [[round(float(x), 5), round(float(y), 5)] for x, y in line_ll.coords]
    return {
        "type": "Feature",
        "properties": {"role": role},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def polygon_feature(poly_m: Polygon, role: str, bundle) -> dict:
    poly_ll = to_lonlat(poly_m, bundle)
    return {
        "type": "Feature",
        "properties": {"role": role},
        "geometry": mapping(poly_ll),
    }


def endpoint_features(endpoints_m: dict[str, tuple[float, float]], bundle) -> list[dict]:
    features = []
    for role, (x, y) in endpoints_m.items():
        lon, lat = bundle.to_lonlat.transform(x, y)
        features.append(
            {
                "type": "Feature",
                "properties": {"role": f"endpoint_{role}"},
                "geometry": {"type": "Point", "coordinates": [round(float(lon), 5), round(float(lat), 5)]},
            }
        )
    return features


def write_transect_csv(rows: Iterable[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_date_corridor(
    water: np.ndarray,
    valid: np.ndarray,
    corridor: np.ndarray,
    guide_mask: np.ndarray,
    guide_lonlat: LineString,
    transform,
    *,
    close_m: float = DEFAULT_CLOSE_M,
) -> DateCorridor:
    """Full per-date envelope + banklines."""
    pixel_m = _pixel_m(transform) if _projected_grid(transform) else (
        abs(float(transform.a)) * 111_320.0 * math.cos(math.radians(27.0))
    )
    envelope = build_outer_river_envelope(
        water,
        corridor,
        pixel_m=pixel_m,
        close_m=close_m,
        guide_mask=guide_mask,
        valid=valid,
    )
    poly_grid = extract_outer_ring(envelope, transform)
    bundle, guide_m = _guide_frame(guide_lonlat)
    poly_m = poly_grid if _projected_grid(transform) else to_metres(poly_grid, bundle)
    if not isinstance(poly_m, Polygon):
        raise BanklineQCError("Projected envelope is not a polygon.")
    endpoints = find_endpoints(poly_m, guide_m)
    left, right = split_left_right_banks(poly_m, endpoints, guide_m)
    area = float(poly_m.area) / 1_000_000.0
    return DateCorridor(
        water=np.asarray(water, dtype=bool),
        valid=np.asarray(valid, dtype=bool),
        envelope=envelope,
        polygon=poly_m,
        left=left,
        right=right,
        endpoints=endpoints,
        area_km2=area,
    )


def compare_corridors(
    earlier: DateCorridor,
    later: DateCorridor,
    aoi: np.ndarray,
    transform,
    guide_lonlat: LineString,
    *,
    min_patch_m2: float = DEFAULT_MIN_PATCH_M2,
    elapsed_years: float = 0.0,
    transect_csv: Path | None = None,
    transect_step_m: float = DEFAULT_TRANSECT_STEP_M,
) -> dict:
    """Two-date envelope difference, bank GeoJSON, optional transect CSV."""
    pixel_m = _pixel_m(transform) if _projected_grid(transform) else (
        abs(float(transform.a)) * 111_320.0 * math.cos(math.radians(27.0))
    )
    erosion, deposition, persistent, valid, erosion_raw, deposition_raw = calculate_corridor_difference(
        earlier.envelope,
        later.envelope,
        earlier.valid,
        later.valid,
        aoi,
        min_patch_m2=min_patch_m2,
        pixel_m=pixel_m,
    )
    # Area accounting uses raw XOR so net matches later−earlier exactly.
    stats = calculate_area_statistics(
        earlier.envelope,
        later.envelope,
        erosion_raw,
        deposition_raw,
        persistent,
        valid,
        transform,
    )
    bundle, guide_m = _guide_frame(guide_lonlat)
    banks = [
        linestring_feature(earlier.left, "start_left", bundle),
        linestring_feature(earlier.right, "start_right", bundle),
        linestring_feature(later.left, "end_left", bundle),
        linestring_feature(later.right, "end_right", bundle),
    ]
    banks.extend(endpoint_features(earlier.endpoints, bundle))
    # Prefix later endpoints to distinguish.
    for feat in endpoint_features(later.endpoints, bundle):
        feat["properties"]["role"] = "later_" + feat["properties"]["role"]
        banks.append(feat)

    rows = sample_bank_transects(
        earlier.polygon, later.polygon, guide_m, step_m=transect_step_m
    )
    rows = calculate_bank_displacement(rows, elapsed_years)
    transect_qc = transect_coverage_summary(rows)
    if transect_csv is not None:
        write_transect_csv(rows, transect_csv)

    earlier_bl_qc = bankline_qc_report(earlier.left, earlier.right, guide_m, earlier.polygon)
    later_bl_qc = bankline_qc_report(later.left, later.right, guide_m, later.polygon)

    aoi = np.asarray(aoi, dtype=bool)
    earlier_obs = np.asarray(earlier.valid, dtype=bool) & aoi
    later_obs = np.asarray(later.valid, dtype=bool) & aoi
    aoi_pixels = int(aoi.sum())
    valid_pixels = int(valid.sum())
    observation = {
        "corridor_pixels": aoi_pixels,
        "earlier_valid_pixels": int(earlier_obs.sum()),
        "later_valid_pixels": int(later_obs.sum()),
        "common_valid_pixels": valid_pixels,
        "common_valid_fraction_of_corridor": round(valid_pixels / max(aoi_pixels, 1), 4),
        "earlier_observed_fraction": round(int(earlier_obs.sum()) / max(aoi_pixels, 1), 4),
        "later_observed_fraction": round(int(later_obs.sum()) / max(aoi_pixels, 1), 4),
        "nodata_both_fraction": round(int((aoi & ~earlier_obs & ~later_obs).sum()) / max(aoi_pixels, 1), 4),
        "coverage_threshold": MIN_VALID_FRACTION,
        "coverage_warning": (
            None
            if valid_pixels / max(aoi_pixels, 1) >= MIN_VALID_FRACTION
            else (
                f"Common valid coverage "
                f"{100 * valid_pixels / max(aoi_pixels, 1):.1f}% "
                f"is below {100 * MIN_VALID_FRACTION:.0f}%."
            )
        ),
    }
    bankline_qc = {
        "earlier_left": earlier_bl_qc["left"],
        "earlier_right": earlier_bl_qc["right"],
        "later_left": later_bl_qc["left"],
        "later_right": later_bl_qc["right"],
    }
    return {
        "erosion": erosion,
        "deposition": deposition,
        "persistent": persistent,
        "valid": valid,
        "erosion_raw": erosion_raw,
        "deposition_raw": deposition_raw,
        "banks": banks,
        "bankline_qc": bankline_qc,
        "banks_validated": all(
            bool(side.get("is_simple")) and float(side.get("pct_on_expected_side") or 0) >= 80
            for side in bankline_qc.values()
        ),
        "envelopes": {
            "earlier": polygon_feature(earlier.polygon, "earlier_envelope", bundle),
            "later": polygon_feature(later.polygon, "later_envelope", bundle),
        },
        "transects": rows,
        "transect_qc": transect_qc,
        "observation": observation,
        "stats": {
            **stats,
            "valid_pixels": valid_pixels,
            "valid_fraction": observation["common_valid_fraction_of_corridor"],
            "earlier_envelope_km2": round(float(stats["earlier_full_km2"]), 3),
            "later_envelope_km2": round(float(stats["later_full_km2"]), 3),
            "earlier_envelope_polygon_km2": round(earlier.area_km2, 3),
            "later_envelope_polygon_km2": round(later.area_km2, 3),
            "close_m": DEFAULT_CLOSE_M,
        },
        "method_note": (
            "Corridor expansion/contraction from filled outer river envelopes on common "
            "valid observations only. Unobserved pixels are never treated as land. "
            "Seasonal water-level differences may affect the result. "
            + (observation["coverage_warning"] or "")
        ),
    }


def guide_search_mask(height: int, width: int, transform, half_width_m: float = 4_000.0) -> np.ndarray:
    """Narrow belt around the guide used only to seed the main-stem network."""
    from rasterio.features import rasterize

    from .guide import load_guide_lonlat

    bundle = load_crs()
    if _projected_grid(transform):
        belt = to_metres(load_guide_lonlat(), bundle).buffer(half_width_m)
    else:
        belt = to_lonlat(to_metres(load_guide_lonlat(), bundle).buffer(half_width_m), bundle)
    return rasterize([(belt, 1)], out_shape=(height, width), transform=transform, fill=0, dtype="uint8").astype(bool)
