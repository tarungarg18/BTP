# Brahmaputra bankline QC report

Pair: earlier **2026-04-08**, later **2026-04-22**, sensor **optical**.
Closing radius: **300.0 m** (single configurable parameter).

## 1. Grid and area accounting

- Shared grid shape `3340×7236`, CRS EPSG:4326, Assam-Albers pixel area **8874.859 m²** (0.008875 km²).
- Full envelope pixels: earlier **103724**, later **302807**.
- Full envelope area (same pixel area): earlier **920.536 km²**, later **2687.369 km²**.
- Common-valid envelope pixels: earlier **74692**, later **29321**.
- Common-valid areas (reported): earlier **662.881 km²**, later **260.22 km²**.
- Independent Albers polygonization: earlier **680.158 km²**, later **264.873 km²**.
- Erosion **21.415**, deposition **424.076**, net **-402.661**.
- Identity later−earlier = erosion−deposition: **True**.

**Root cause of the apparent pixel/area inconsistency:** the component pixel counts were full envelopes, while the reported km² values were common-valid only. Both are now reported explicitly.

## 2. Valid observation coverage

- Corridor pixels: **3143355**
- Earlier observed: **46.9%**
- Later observed: **88.9%**
- Common valid: **37.7%**
- NoData in both: **1.9%**

Common valid observation covers only 37.7% of the study corridor. Do not claim complete Brahmaputra coverage for this date pair.

See `observation_diagnostic.png` (green=common, cyan=earlier-only, amber=later-only, grey=nodata).

## 3. Transects

- both_ok **275** / 2961 (9.29% of full guide)
- earlier_only **536**, later_only **1542**, neither **608**
- left_ok **275**, right_ok **275**
- first both_ok chainage **386750.0 m**, last **455750.0 m**
- max consecutive missing **386750.0 m**
- within mutual envelope span: **99.28%** both_ok

Most guide transects fail because the two date envelopes do not both reach that chainage (cloud / water-mask gaps). Within the mutual envelope span, both_ok coverage should be near 100%.

CSV: `transects_qc.csv`. Map: `transect_diagnostic.png`.

## 4. Closing sensitivity (later date)

- 100 m → 284240 px, 3739 cols, 1 components
- 200 m → 292030 px, 3739 cols, 1 components
- 300 m → 302807 px, 3740 cols, 1 components
- 500 m → 363201 px, 4103 cols, 1 components

Active setting: **300.0 m** (was previously confused with a 750 m leftover).

## 5. Banklines

- **start_left**: 341.53 km, 2153 vertices, simple=True, side=85.4%, ends [93.10582, 26.59917] → [91.37388, 26.14912]
- **start_right**: 567.04 km, 3774 vertices, simple=True, side=68.3%, ends [93.10582, 26.60636] → [91.37298, 26.19314]
- **end_left**: 665.42 km, 4424 vertices, simple=True, side=92.7%, ends [95.66062, 27.78494] → [92.51294, 26.56504]
- **end_right**: 1204.12 km, 7992 vertices, simple=True, side=70.7%, ends [95.66421, 27.80471] → [92.51563, 26.58839]

Endpoints in `endpoints.geojson`. Overview `banklines_diagnostic.png`.

## Unresolved / limitations

- Common valid observation covers only 37.7% of the study corridor. Do not claim complete Brahmaputra coverage for this date pair.
- Only 275/2961 transects have both-date intersections (9.29% of full guide). Within the mutual envelope span, coverage is 99.28%.
- Optical-only envelopes for cloudy 15-day windows remain incomplete along parts of Sadiya–Dhubri; microwave is not silently fused into water.
