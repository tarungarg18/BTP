# Guwahati Disaster Intelligence

Frontend-first BTech prototype for GIS-based hazard analysis and risk
visualization in Guwahati, Assam.

## Run locally

```bash
npm install
npm run dev
```

Production validation:

```bash
npm run lint
npm run build
npm run preview
```

## Deploy to Vercel

From the project root:

```bash
npm install
npm run build
npx vercel login
npx vercel
npx vercel --prod
```

Accept Vercel's detected Vite settings. The production output directory is
`dist`. The included `vercel.json` preserves SPA deep links and browser
refreshes.

## Prototype scope

- OpenStreetMap and Esri imagery basemaps
- Interactive Leaflet layers, search, popups, drawing, and area selection
- Illustrative flood, landslide, terrain, rainfall, and exposure overlays
- Simulated area analysis, historical charts, scenario analysis, and model explanation
- API abstraction prepared for a future FastAPI GIS/ML service

All hazard predictions, environmental metrics, historical records, and exposure
figures are explicitly demo data. They are not operational forecasts or
scientific outputs.
