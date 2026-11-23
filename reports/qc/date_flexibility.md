# Date flexibility validation

## CLOSE_M reconciliation (same April 2026 optical 15-day pair)

| CLOSE_M | Earlier | Later | Erosion | Deposition | Net |
|--------|---------|-------|---------|------------|-----|
| 750 m | 780.686 | 503.764 | 30.467 | 307.390 | **−276.922** |
| 300 m (current) | 662.881 | 260.220 | 21.415 | 424.076 | **−402.661** |

Cause: morphology parameter, not an accounting bug. Identity `later − earlier = erosion − deposition` holds.

## Cases (parallel run)

| Case | Status | Net km² |
|------|--------|---------|
| 15 days apart (Apr 2026 optical) | ok | −402.661 |
| 1 year 2023→2024 pre-monsoon | ok | −853.096 |
| same season 2020→2021 | ok | −428.327 |
| 5 years 2019→2024 microwave | ok | +100.029 |
| cloudy monsoon Jul–Aug 2022 | ok (partial / caution) | −2243.058 |
| pre-S2 archive 2015 vs 2020 | **rejected** correctly | — |
| Mode B periods 2020→2021 dry | pending_cache | — |

## Verdict for BTP

Reusable across several same-season and multi-year pairs when scenes exist. Archive rejection works. Cloudy monsoon returns a number but must not be sold as full-corridor accuracy without acknowledging low valid overlap.
