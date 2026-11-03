# Brahmaputra Bank Change Portal

Multi-sensor river-corridor monitoring for the **Assam main-stem Brahmaputra** (Sadiya to Dhubri). Candidate bankline change only — not an operational warning system.

## Layout

```
brahmaputra-bank-change-portal/
  processing/   Python geometry + GEE discovery
  backend/      FastAPI (source of truth)
  frontend/     React + Leaflet portal
  data/         Generated bootstrap store (created on first seed)
```

## Study area

Assam main stem, National Waterway 2: Sadiya → Bangladesh border near Dhubri. Tributaries excluded from primary geometry.

Copy this folder to `D:\SEM 7\BTP\brahmaputra-bank-change-portal`. Cloud edits do not appear on that drive until you copy or pull from GitHub.

## Run locally (Windows or Linux)

```bash
cd brahmaputra-bank-change-portal
python -m pip install -r backend/requirements.txt
python -m processing.bootstrap
cd frontend
npm install
npm run build
cd ..
python -m uvicorn backend.app.main:app --app-dir . --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 — FastAPI serves both the map UI and `/api`.

Dev mode (hot reload): keep the API on 8000, then `cd frontend && npm run dev` and open the Vite URL.

## GEE (optional)

Set `GEE_PROJECT` and authenticate (`earthengine authenticate`). Then:

```bash
python3 -m processing.gee_discover
```

Without credentials the API still serves bootstrap epochs built from the locked Assam corridor, labelled `bootstrap_pending_gee`.

## Honesty

Proxy banklines and candidate erosion/accretion/expansion/contraction are unvalidated research outputs. Water-level change can mimic bank movement.
