"""Validate date flexibility, cache keys, and CLOSE_M net-area reconciliation.

Runs cases in parallel (sensor-only downloads) for speed.

  python scripts/validate_date_flexibility.py
"""

from __future__ import annotations

import json
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports" / "qc" / "date_flexibility.json"
OUT_MD = ROOT / "reports" / "qc" / "date_flexibility.md"

CASES = [
    {
        "name": "15_days_apart_april2026",
        "kwargs": {
            "mode": "dates",
            "sensor": "optical",
            "window_days": 15,
            "earlier": "2026-04-08",
            "later": "2026-04-22",
        },
    },
    {
        "name": "1_year_apart_2023_2024_premonsoon",
        "kwargs": {
            "mode": "dates",
            "sensor": "optical",
            "window_days": 30,
            "earlier": "2023-04-15",
            "later": "2024-04-15",
        },
    },
    {
        "name": "same_season_2020_2021",
        "kwargs": {
            "mode": "dates",
            "sensor": "optical",
            "window_days": 30,
            "earlier": "2020-04-15",
            "later": "2021-04-15",
        },
    },
    {
        "name": "5_years_apart_2019_2024_microwave",
        "kwargs": {
            "mode": "dates",
            "sensor": "microwave",
            "window_days": 30,
            "earlier": "2019-11-15",
            "later": "2024-11-15",
        },
    },
    {
        "name": "cloudy_monsoon_optical_2022",
        "kwargs": {
            "mode": "dates",
            "sensor": "optical",
            "window_days": 15,
            "earlier": "2022-07-15",
            "later": "2022-08-15",
        },
    },
    {
        "name": "unavailable_pre_s2_archive",
        "kwargs": {
            "mode": "dates",
            "sensor": "optical",
            "window_days": 15,
            "earlier": "2015-04-08",
            "later": "2020-04-08",
        },
    },
    {
        "name": "period_mode_2020_2021_dry",
        "kwargs": {
            "mode": "periods",
            "sensor": "optical",
            "earlier_start": "2020-02-01",
            "earlier_end": "2020-03-15",
            "later_start": "2021-02-01",
            "later_end": "2021-03-15",
        },
    },
]


def _areas(pair: dict) -> dict:
    s = pair["stats"]
    return {
        "earlier_km2": s["earlier_km2"],
        "later_km2": s["later_km2"],
        "erosion_km2": s["erosion_km2"],
        "deposition_km2": s["deposition_km2"],
        "net_km2": s["net_km2"],
        "valid_fraction": s["valid_fraction"],
        "close_m": pair.get("close_m"),
        "identity_ok": abs(s["net_km2"] - (s["erosion_km2"] - s["deposition_km2"])) < 1e-6,
    }


def run_case(name: str, kwargs: dict) -> dict:
    """Worker: one case, sensor-only EE downloads."""
    sys.path.insert(0, str(ROOT))
    from processing.bankline_compare import DEFAULT_CLOSE_M
    from processing.date_options import ALGORITHM_VERSION, build_compare_request
    from processing.live_extract import (
        ANALYSIS_CRS,
        SCALE_M,
        _PAIR_CACHE,
        _pair_from_request,
        preflight_availability,
    )

    print(f"[{name}] start", flush=True)
    try:
        req = build_compare_request(acknowledge_partial=True, **kwargs)
    except ValueError as exc:
        print(f"[{name}] rejected: {exc}", flush=True)
        return {"name": name, "status": "rejected", "detail": str(exc)}

    key = req.cache_key(close_m=DEFAULT_CLOSE_M, scale_m=SCALE_M, crs=ANALYSIS_CRS)
    if "if False" in key or key.endswith("|") or "||" in key:
        return {"name": name, "status": "cache_key_invalid", "key": key}

    try:
        flight = preflight_availability(req)
    except Exception as exc:  # noqa: BLE001
        print(f"[{name}] preflight_error: {exc}", flush=True)
        return {"name": name, "status": "preflight_error", "detail": str(exc), "key": key}

    if not flight["ok"]:
        print(f"[{name}] unavailable", flush=True)
        return {
            "name": name,
            "status": "unavailable",
            "detail": flight.get("detail"),
            "preflight": flight,
            "key": key,
        }

    try:
        _PAIR_CACHE.clear()
        pair = _pair_from_request(req, staged=False, fetch_both_sensors=False)
        out = {
            "name": name,
            "status": "ok",
            "key": key,
            "algorithm": ALGORITHM_VERSION,
            "preflight": {
                "earlier_scenes": flight["earlier"]["scene_count"],
                "later_scenes": flight["later"]["scene_count"],
                "earlier_acq": [
                    flight["earlier"]["earliest_acquisition"],
                    flight["earlier"]["latest_acquisition"],
                ],
                "later_acq": [
                    flight["later"]["earliest_acquisition"],
                    flight["later"]["latest_acquisition"],
                ],
            },
            "areas": _areas(pair),
            "transect_qc": pair.get("transect_qc"),
            "partial_coverage": pair.get("partial_coverage"),
        }
        print(f"[{name}] ok net={out['areas']['net_km2']}", flush=True)
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"[{name}] compute_error: {exc}", flush=True)
        return {
            "name": name,
            "status": "compute_error",
            "detail": str(exc),
            "traceback": traceback.format_exc(),
            "key": key,
            "preflight": flight,
        }


def reconcile_close_m() -> dict:
    """Explain -276.922 (close≈750) vs -402.661 (close=300) for April 2026 pair."""
    from processing import bankline_compare as bc
    from processing.date_options import build_compare_request
    from processing.live_extract import _PAIR_CACHE, _pair_from_request

    req = build_compare_request(
        mode="dates",
        sensor="optical",
        window_days=15,
        earlier="2026-04-08",
        later="2026-04-22",
        acknowledge_partial=True,
    )
    results: dict = {}
    for close_m in (300.0, 750.0):
        _PAIR_CACHE.clear()
        original = bc.DEFAULT_CLOSE_M
        bc.DEFAULT_CLOSE_M = close_m
        bc.CLOSE_M = close_m
        try:
            pair = _pair_from_request(req, staged=False, fetch_both_sensors=False)
            results[str(close_m)] = _areas(pair)
            results[str(close_m)]["cache_key"] = pair["key"]
            results[str(close_m)]["full_earlier_km2"] = pair["stats"].get("earlier_full_km2")
            results[str(close_m)]["full_later_km2"] = pair["stats"].get("later_full_km2")
            print(f"[reconcile] close_m={close_m} net={results[str(close_m)]['net_km2']}", flush=True)
        finally:
            bc.DEFAULT_CLOSE_M = original
            bc.CLOSE_M = original
            _PAIR_CACHE.clear()
    results["explanation"] = (
        "Net area changed because CLOSE_M changed from 750 m to 300 m. "
        "A larger closing radius merges more braids/bars into the outer corridor, "
        "changing both date envelopes and therefore common-valid expansion/contraction. "
        "This is a parameter effect, not an accounting bug."
    )
    return results


def _write_md(report: dict) -> None:
    lines = [
        "# Date flexibility validation",
        "",
        "## CLOSE_M reconciliation (April 2026 optical 15-day)",
        "",
    ]
    recon = report.get("close_m_reconciliation") or {}
    for close in ("300.0", "750.0", "300", "750"):
        block = recon.get(close)
        if not block:
            continue
        lines.append(
            f"- CLOSE_M={close}: earlier={block.get('earlier_km2')} later={block.get('later_km2')} "
            f"erosion={block.get('erosion_km2')} deposition={block.get('deposition_km2')} "
            f"net={block.get('net_km2')} identity_ok={block.get('identity_ok')}"
        )
    if recon.get("explanation"):
        lines.extend(["", recon["explanation"], ""])
    lines.extend(["## Cases", ""])
    for case in report.get("cases") or []:
        status = case.get("status")
        name = case.get("name")
        lines.append(f"### {name} — `{status}`")
        if status == "ok":
            a = case["areas"]
            lines.append(
                f"- net={a['net_km2']} km² · valid={100 * a['valid_fraction']:.1f}% · "
                f"identity_ok={a['identity_ok']}"
            )
            pf = case.get("preflight") or {}
            lines.append(
                f"- scenes earlier={pf.get('earlier_scenes')} later={pf.get('later_scenes')} "
                f"acq {pf.get('earlier_acq')} → {pf.get('later_acq')}"
            )
            tq = case.get("transect_qc") or {}
            if tq:
                lines.append(
                    f"- transects both_ok={tq.get('both_ok')}/{tq.get('total_transects')} "
                    f"({tq.get('pct_of_mutual_span')}% mutual span)"
                )
        else:
            lines.append(f"- {case.get('detail') or status}")
        lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    print("Running cases in parallel…", flush=True)
    cases: list[dict] = []
    # Windows-safe: max_workers limited; EE auth inherited per process.
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(run_case, spec["name"], spec["kwargs"]): spec["name"]
            for spec in CASES
        }
        by_name: dict[str, dict] = {}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                by_name[name] = fut.result()
            except Exception as exc:  # noqa: BLE001
                by_name[name] = {
                    "name": name,
                    "status": "worker_crash",
                    "detail": str(exc),
                    "traceback": traceback.format_exc(),
                }
        cases = [by_name[spec["name"]] for spec in CASES]

    print("Reconciling CLOSE_M…", flush=True)
    try:
        recon = reconcile_close_m()
    except Exception as exc:  # noqa: BLE001
        recon = {"error": str(exc), "traceback": traceback.format_exc()}

    report = {"close_m_reconciliation": recon, "cases": cases}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_md(report)
    summary = {"wrote": str(OUT), "md": str(OUT_MD), "cases": [(c["name"], c["status"]) for c in cases]}
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    # Required on Windows for ProcessPoolExecutor.
    main()
