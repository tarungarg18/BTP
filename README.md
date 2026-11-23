# Brahmaputra Bank Change Portal

Assam main stem, Sadiya to Dhubri. Compare two Sentinel-2 or Sentinel-1 observations and map corridor expansion and contraction.

## Comparison

Mode A uses two dates. Each date is the last day of a composite window of 1, 15, 30, or 60 days. Both dates use the same window. The time between the two dates is not composited.

Mode B uses two periods. Each period has its own start and end. The later period must start after the earlier period ends.

Sentinel-2 water is MNDWI from bands B3 and B11, greater than 0, after the SCL mask. Sentinel-1 water is VV less than -16 dB. The analysis grid is a fixed 100 m Assam Albers raster. Areas are calculated only where both dates have a valid observation.

## Run locally

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
cd frontend && npm install && npm run dev
```

Open http://localhost:5173

Saved downloads stay in `data/live` and are not part of the repository.

## Another computer

```bash
python -c "import ee; ee.Authenticate(auth_mode='localhost', scopes=['https://www.googleapis.com/auth/earthengine','https://www.googleapis.com/auth/cloud-platform'])"
```

The Earth Engine project is `community-hero-5c501`. Set `GEE_PROJECT` to use another project.
