# Brahmaputra Bank Change Portal

Assam main stem, Sadiya to Dhubri. Compare two Sentinel-2 or Sentinel-1 observations and map corridor expansion and contraction candidates.

## What it does

Mode A compares two dates. Each date is the end of a 1, 15, 30, or 60 day composite. The gap between the dates is not filled in.

Mode B compares two explicit periods. The later period must start after the earlier period ends.

Water baselines, recorded with every run and not treated as universal rules:

- Sentinel-2: MNDWI (B3, B11) greater than 0, after SCL masking
- Sentinel-1: VV less than -16 dB

The comparison uses a fixed 100 m Assam Albers grid. Areas are corridor expansion and contraction candidates on pixels observed in both dates. Unobserved pixels are not treated as land. River stage and season can produce a similar pattern.

## Run locally

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
cd frontend && npm install && npm run dev
```

Open http://localhost:5173

Downloads are cached under `data/live` and are not committed.

## Another computer

```bash
python -c "import ee; ee.Authenticate(auth_mode='localhost', scopes=['https://www.googleapis.com/auth/earthengine','https://www.googleapis.com/auth/cloud-platform'])"
```

The Earth Engine project is `community-hero-5c501`. Override it with `GEE_PROJECT`. Do not commit Google credentials.
