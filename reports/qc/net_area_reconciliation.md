# Net-area reconciliation (−276.922 vs −402.661 km²)

Same date pair: **2026-04-08 → 2026-04-22**, sensor **optical**, window **15 days**, shared EPSG:4326 100 m grid.

| Run | CLOSE_M | Earlier (common-valid) | Later (common-valid) | Erosion | Deposition | Net |
|-----|---------|------------------------|----------------------|---------|------------|-----|
| Prior QC (envv2 / 750 m era) | **750 m** | 780.686 | 503.764 | 30.467 | 307.390 | **−276.922** |
| Latest QC (CLOSE_M=300) | **300 m** | 662.881 | 260.220 | 21.415 | 424.076 | **−402.661** |

## Why the numbers differ

1. **Not an accounting bug.** In both runs  
   `later − earlier = erosion − deposition` held exactly on common-valid support.
2. **Morphology parameter.** `CLOSE_M` controls how aggressively braids and bars are bridged into the outer corridor.  
   750 m produces larger, more merged envelopes; 300 m keeps a tighter corridor. Different envelopes ⇒ different common-valid masks ⇒ different expansion/contraction areas.
3. **Current default** is `CLOSE_M = 300` (single assignment; no duplicate 750 leftover in code).
4. Cache keys now include `close_m`, sensor, periods, window, scale, CRS, classification and `envv3`, so a 300 m result cannot be served from a 750 m cache.

See `scripts/validate_date_flexibility.py` → `close_m_reconciliation` for a machine-readable re-run.
