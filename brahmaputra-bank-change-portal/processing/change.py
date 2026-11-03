"""Bank-normal displacement on fixed sections plus corridor expansion/contraction."""

from __future__ import annotations

from typing import Any

from shapely.geometry import mapping, shape

TOLERANCE_M = 30.0


def classify(delta: float | None, tolerance: float = TOLERANCE_M) -> str:
    if delta is None:
        return "invalid"
    if delta > tolerance:
        return "candidate_erosion"
    if delta < -tolerance:
        return "candidate_accretion"
    return "stable"


def compare_epochs(
    epoch_a: dict[str, Any],
    epoch_b: dict[str, Any],
    reaches: list[dict[str, Any]],
    tolerance_m: float = TOLERANCE_M,
) -> dict[str, Any]:
    by_id_a = {row["section_id"]: row for row in epoch_a["width_samples"]}
    by_id_b = {row["section_id"]: row for row in epoch_b["width_samples"]}
    bank_features: list[dict[str, Any]] = []
    per_reach: dict[str, dict[str, Any]] = {
        r["reach_id"]: {
            "reach_id": r["reach_id"],
            "n_valid": 0,
            "mean_width_a": [],
            "mean_width_b": [],
            "left_dd": [],
            "right_dd": [],
            "eroded_len_m": 0.0,
            "accreted_len_m": 0.0,
            "max_retreat_m": 0.0,
        }
        for r in reaches
    }

    for sid, a in by_id_a.items():
        b = by_id_b.get(sid)
        if not b:
            continue
        valid = a["qc_flag"] == "ok" and b["qc_flag"] == "ok"
        left_dd = None
        right_dd = None
        if valid and a["left_offset_m"] is not None and b["left_offset_m"] is not None:
            left_dd = b["left_offset_m"] - a["left_offset_m"]
        if valid and a["right_offset_m"] is not None and b["right_offset_m"] is not None:
            right_dd = b["right_offset_m"] - a["right_offset_m"]
        left_cls = classify(left_dd, tolerance_m)
        right_cls = classify(right_dd, tolerance_m)
        bucket = per_reach.get(a["reach_id"])
        if bucket and valid:
            bucket["n_valid"] += 1
            bucket["mean_width_a"].append(a["width_m"])
            bucket["mean_width_b"].append(b["width_m"])
            if left_dd is not None:
                bucket["left_dd"].append(left_dd)
            if right_dd is not None:
                bucket["right_dd"].append(right_dd)
            for dd, cls in ((left_dd, left_cls), (right_dd, right_cls)):
                if cls == "candidate_erosion":
                    bucket["eroded_len_m"] += 300.0
                    bucket["max_retreat_m"] = max(bucket["max_retreat_m"], dd or 0)
                elif cls == "candidate_accretion":
                    bucket["accreted_len_m"] += 300.0
        bank_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [a["lon"], a["lat"]]},
                "properties": {
                    "section_id": sid,
                    "reach_id": a["reach_id"],
                    "chainage_m": a["chainage_m"],
                    "width_a_m": a["width_m"],
                    "width_b_m": b["width_m"],
                    "left_delta_m": None if left_dd is None else round(left_dd, 1),
                    "right_delta_m": None if right_dd is None else round(right_dd, 1),
                    "left_class": left_cls,
                    "right_class": right_cls,
                    "qc_ok": valid,
                },
            }
        )

    env_a = shape(epoch_a["river_envelope"]["features"][0]["geometry"])
    env_b = shape(epoch_b["river_envelope"]["features"][0]["geometry"])
    expansion = env_b.difference(env_a)
    contraction = env_a.difference(env_b)
    overlap = env_a.intersection(env_b)
    change_polygons = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(expansion),
                "properties": {"class": "candidate_corridor_expansion"},
            },
            {
                "type": "Feature",
                "geometry": mapping(contraction),
                "properties": {"class": "candidate_corridor_contraction"},
            },
            {
                "type": "Feature",
                "geometry": mapping(overlap),
                "properties": {"class": "corridor_overlap"},
            },
        ],
    }

    reach_stats = []
    for r in reaches:
        b = per_reach[r["reach_id"]]

        def avg(vals: list[float]) -> float | None:
            nums = [v for v in vals if v is not None]
            return None if not nums else round(sum(nums) / len(nums), 1)

        reach_stats.append(
            {
                "reach_id": r["reach_id"],
                "chainage_start_m": r["chainage_start_m"],
                "chainage_end_m": r["chainage_end_m"],
                "n_valid": b["n_valid"],
                "mean_width_a_m": avg(b["mean_width_a"]),
                "mean_width_b_m": avg(b["mean_width_b"]),
                "mean_left_delta_m": avg(b["left_dd"]),
                "mean_right_delta_m": avg(b["right_dd"]),
                "candidate_eroded_bank_length_m": round(b["eroded_len_m"], 1),
                "candidate_accreted_bank_length_m": round(b["accreted_len_m"], 1),
                "max_retreat_m": round(b["max_retreat_m"], 1),
                "expansion_area_km2": round(expansion.area, 6)
                if False
                else None,
            }
        )

    return {
        "epoch_a": epoch_a["date"],
        "epoch_b": epoch_b["date"],
        "tolerance_m": tolerance_m,
        "disclaimer": (
            "Candidate satellite proxy-bankline change. Water-level and season can "
            "mimic erosion or accretion. Not field-validated."
        ),
        "bank_changes": {"type": "FeatureCollection", "features": bank_features},
        "change_polygons": change_polygons,
        "reach_statistics": reach_stats,
        "expansion_area_deg2": expansion.area,
        "contraction_area_deg2": contraction.area,
    }
