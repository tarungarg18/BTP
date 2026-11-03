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

## Run locally

```bash
cd brahmaputra-bank-change-portal
python3 -m pip install -r backend/requirements.txt
python3 -m processing.bootstrap
python3 -m uvicorn backend.app.main:app --app-dir . --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL. The UI talks to `http://127.0.0.1:8000`.

## GEE (optional)

Set `GEE_PROJECT` and authenticate (`earthengine authenticate`). Then:

```bash
python3 -m processing.gee_discover
```

Without credentials the API still serves bootstrap epochs built from the locked Assam corridor, labelled `bootstrap_pending_gee`.

## Honesty

Proxy banklines and candidate erosion/accretion/expansion/contraction are unvalidated research outputs. Water-level change can mimic bank movement.
