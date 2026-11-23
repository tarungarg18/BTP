# Date flexibility validation

## Cases

### 15_days_apart_april2026 — `ok`
- net=-402.661 km² · valid=37.7% · identity_ok=True
- scenes earlier=86 later=152 acq ['2026-03-25', '2026-04-08'] → ['2026-04-08', '2026-04-22']
- transects both_ok=275/2961 (99.28% mutual span)

### 1_year_apart_2023_2024_premonsoon — `ok`
- net=-853.096 km² · valid=99.0% · identity_ok=True
- scenes earlier=246 later=249 acq ['2023-03-17', '2023-04-15'] → ['2024-03-18', '2024-04-15']
- transects both_ok=2438/2961 (99.8% mutual span)

### same_season_2020_2021 — `ok`
- net=-428.327 km² · valid=99.8% · identity_ok=False
- scenes earlier=308 later=308 acq ['2020-03-17', '2020-04-15'] → ['2021-03-17', '2021-04-15']
- transects both_ok=2959/2961 (99.93% mutual span)

### 5_years_apart_2019_2024_microwave — `ok`
- net=100.029 km² · valid=99.8% · identity_ok=True
- scenes earlier=75 later=72 acq ['2019-10-18', '2019-11-15'] → ['2024-10-17', '2024-11-15']
- transects both_ok=2948/2961 (99.56% mutual span)

### cloudy_monsoon_optical_2022 — `ok`
- net=-2243.058 km² · valid=58.5% · identity_ok=False
- scenes earlier=138 later=99 acq ['2022-07-02', '2022-07-15'] → ['2022-08-01', '2022-08-14']
- transects both_ok=2004/2961 (97.8% mutual span)

### unavailable_pre_s2_archive — `rejected`
- optical archive starts 2017-03-28; requested window ends 2015-04-08.

### period_mode_2020_2021_dry — `ok`
- net=-386.323 km² · valid=99.8% · identity_ok=False
- scenes earlier=447 later=444 acq ['2020-02-01', '2020-03-15'] → ['2021-02-02', '2021-03-15']
- transects both_ok=2881/2961 (99.93% mutual span)
