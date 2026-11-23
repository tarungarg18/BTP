# HOD readiness — pre-demo checklist

**Algorithm version:** `envv4`  
**Analysis CRS:** Assam Brahmaputra Albers (equal-area metres), 100 m pixels  
**Closing radius:** 300 m  
**Classification baselines (not claimed universal):** optical `MNDWI > 0`; microwave `VV < −16 dB`  
**Generated:** local incremental audit (unit tests + frontend build). Fresh EE re-runs for demo pairs still required on the presentation machine.

## Checklist

| # | Item | Status |
|---|------|--------|
| 1 | Projected analysis grid (Assam Albers 100 m) | **Done in code** (`gee7-` cache, `ANALYSIS_CRS`) |
| 2 | Main Brahmaputra component = guide-scored (not E–W span) | **Done in code** |
| 3 | Four banklines verified on satellite imagery | **Manual — do before HOD** |
| 4 | Right-bank side confidence improved / reported | **In progress / verify visually** |
| 5 | Raster vs vector areas on metric grid | **Code path ready**; re-measure on fresh EE pair |
| 6 | Optical threshold validation samples | **Baseline retained + documented**; full sample audit pending |
| 7 | SAR threshold validation samples | **Baseline retained + documented**; full sample audit pending |
| 8 | Mode B non-overlap + real-data test | **Non-overlap enforced**; finish EE Mode B on demo PC |
| 9 | Date changes clear stale frontend results + ack fingerprint | **Done** |
| 10 | Partial-coverage acknowledgment bound to request | **Done** |
| 11 | Python tests | **20 passed** |
| 12 | Frontend `npm run build` | **Passed** |
| 13 | Fresh EE QC report for demo pairs | **Pending on presentation machine** |

## Demo pairs (recommended)

1. **Main:** optical April 2023 vs April 2024, 30-day windows  
2. **SAR:** microwave Nov 2019 vs Nov 2024, 30-day windows  
3. **Limitation:** cloudy monsoon pair — show warning, do not treat NoData as land  

Do **not** lead with the April 2026 ~38% overlap case as the primary scientific result.

## Acceptance notes

- Scene count ≠ corridor coverage; final common-valid % is after compositing.  
- Ambiguous multi-intersection transects are rejected (`qc_status=ambiguous`).  
- Cache keys include `envv4`, CRS, classifier, mask method — old `envv1`/`envv2`/`gee6` entries are not reused.  
- Thresholds are **baselines**; record method per observation; do not claim universal accuracy.
