# Brahmaputra Bank Change Portal

Assam main-stem Brahmaputra (Sadiya → Dhubri). The map shows **satellite water**, not a drawn corridor.

## How water is calculated

1. Sentinel-2 MNDWI = (Green − SWIR1) / (Green + SWIR1); water if MNDWI > 0.1.
2. Sentinel-1: VV darker than −16 dB. Never MNDWI on radar.
3. Keep water only inside an 11 km search belt from Sadiya to Dhubri.
4. Outer water edge = left/right banks looking downstream. Centreline = middle of that water.
5. Width every 300 m on a frozen centreline. Change is candidate only — water level can mimic erosion.

**Google Earth Engine:** set `GEE_PROJECT` and run `earthengine authenticate`, then `python -m processing.ingest`. That uses `COPERNICUS/S2_SR_HARMONIZED` and `COPERNICUS/S1_GRD`.

If Earth Engine is not logged in, ingest reads the **same Copernicus Sentinel-2 L2A** scenes via Planetary Computer STAC. That is still real satellite water, not mock geometry.

## Run

```bash
cd brahmaputra-bank-change-portal
python -m pip install -r backend/requirements.txt
python -m processing.ingest
cd frontend && npm install && npm run build && cd ..
PYTHONPATH=. python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000
