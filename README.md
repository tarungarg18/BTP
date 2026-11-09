# Brahmaputra Bank Change Portal

Assam main stem, Sadiya to Dhubri. Choose a start date and an end date, press Compute, and the map shows Sentinel-2 water, Sentinel-1 water, and the difference between those two dates.

## What the numbers mean

Each chosen date is the last day of a 15-day composite. Red is erosion. Amber is deposition. The centreline is the middle of the optical water.

## Run on this computer

Earth Engine is already signed in here. You do not sign in again for each date.

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
cd frontend && npm install && npm run dev
```

Open http://localhost:5173

A new date is downloaded once and saved under `data/live`. The same dates then open from disk. Those files are not part of the git repository.

## Another computer

Clone the repo, install the same requirements, then sign in to Earth Engine once:

```bash
python -c "import ee; ee.Authenticate(auth_mode='localhost', scopes=['https://www.googleapis.com/auth/earthengine','https://www.googleapis.com/auth/cloud-platform'])"
```

The project used by this portal is `community-hero-5c501`. Set `GEE_PROJECT` if you use a different one. GitHub does not store the Google login.
