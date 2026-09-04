import type { FeatureCollection, LineString, Point, Polygon } from 'geojson'

import type {
  AreaAnalysis,
  LayerState,
  RiskZoneProperties,
  SearchPlace,
} from '../types/disaster'

export const GUWAHATI_CENTER: [number, number] = [26.1445, 91.7362]
export const GUWAHATI_BOUNDS: [[number, number], [number, number]] = [
  [25.99, 91.54],
  [26.24, 92.02],
]

export const defaultLayers: LayerState = {
  flood: true,
  landslide: false,
  combined: false,
  rivers: true,
  waterBodies: true,
  elevation: false,
  slope: false,
  rainfall: false,
  roads: false,
  buildings: false,
  hospitals: true,
  schools: false,
  bridges: true,
  population: false,
  criticalInfrastructure: false,
}

export const searchPlaces: SearchPlace[] = [
  { name: 'Guwahati', detail: 'City centre', coordinates: [26.1445, 91.7362], zoom: 12 },
  { name: 'Dispur', detail: 'Assam capital complex', coordinates: [26.1433, 91.7898], zoom: 14 },
  { name: 'Pan Bazaar', detail: 'Central Guwahati', coordinates: [26.1851, 91.7501], zoom: 14 },
  { name: 'Jalukbari', detail: 'Western Guwahati', coordinates: [26.1577, 91.6635], zoom: 14 },
  { name: 'Chandmari', detail: 'Eastern central Guwahati', coordinates: [26.1842, 91.7803], zoom: 14 },
  { name: 'Lokpriya Gopinath Bordoloi Airport', detail: 'Borjhar', coordinates: [26.1061, 91.5859], zoom: 13 },
  { name: 'Saraighat Bridge', detail: 'Brahmaputra crossing', coordinates: [26.1695, 91.6638], zoom: 14 },
  { name: 'Deepor Beel', detail: 'Ramsar wetland', coordinates: [26.1135, 91.6498], zoom: 14 },
]

export const riskZones: FeatureCollection<Polygon, RiskZoneProperties> = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { id: 'z01', name: 'Demo Zone 01 · Bharalumukh', floodRisk: 86, landslideRisk: 22, elevation: 49, riverDistance: 0.8, historicalEvents: 7 },
      geometry: { type: 'Polygon', coordinates: [[[91.714, 26.171], [91.738, 26.169], [91.744, 26.191], [91.718, 26.196], [91.704, 26.184], [91.714, 26.171]]] },
    },
    {
      type: 'Feature',
      properties: { id: 'z02', name: 'Demo Zone 02 · Pan Bazaar', floodRisk: 77, landslideRisk: 18, elevation: 52, riverDistance: 0.5, historicalEvents: 6 },
      geometry: { type: 'Polygon', coordinates: [[[91.742, 26.169], [91.773, 26.169], [91.776, 26.191], [91.748, 26.194], [91.742, 26.169]]] },
    },
    {
      type: 'Feature',
      properties: { id: 'z03', name: 'Demo Zone 03 · Chandmari', floodRisk: 64, landslideRisk: 37, elevation: 61, riverDistance: 2.1, historicalEvents: 5 },
      geometry: { type: 'Polygon', coordinates: [[[91.772, 26.161], [91.803, 26.159], [91.812, 26.184], [91.784, 26.193], [91.772, 26.161]]] },
    },
    {
      type: 'Feature',
      properties: { id: 'z04', name: 'Demo Zone 04 · Dispur', floodRisk: 58, landslideRisk: 43, elevation: 66, riverDistance: 5.4, historicalEvents: 4 },
      geometry: { type: 'Polygon', coordinates: [[[91.766, 26.119], [91.807, 26.116], [91.819, 26.147], [91.786, 26.159], [91.766, 26.119]]] },
    },
    {
      type: 'Feature',
      properties: { id: 'z05', name: 'Demo Zone 05 · Noonmati', floodRisk: 72, landslideRisk: 49, elevation: 72, riverDistance: 1.2, historicalEvents: 8 },
      geometry: { type: 'Polygon', coordinates: [[[91.817, 26.171], [91.852, 26.167], [91.861, 26.197], [91.829, 26.207], [91.817, 26.171]]] },
    },
    {
      type: 'Feature',
      properties: { id: 'z06', name: 'Demo Zone 06 · Kahilipara', floodRisk: 34, landslideRisk: 73, elevation: 118, riverDistance: 7.8, historicalEvents: 5 },
      geometry: { type: 'Polygon', coordinates: [[[91.744, 26.088], [91.778, 26.083], [91.794, 26.111], [91.765, 26.127], [91.744, 26.088]]] },
    },
    {
      type: 'Feature',
      properties: { id: 'z07', name: 'Demo Zone 07 · Jalukbari', floodRisk: 81, landslideRisk: 29, elevation: 47, riverDistance: 0.9, historicalEvents: 7 },
      geometry: { type: 'Polygon', coordinates: [[[91.633, 26.143], [91.674, 26.137], [91.686, 26.166], [91.651, 26.177], [91.633, 26.143]]] },
    },
  ],
}

export const brahmaputraRiver: FeatureCollection<LineString, { name: string; source: string }> = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    properties: { name: 'Brahmaputra River', source: 'Simplified cartographic reference aligned to OpenStreetMap' },
    geometry: {
      type: 'LineString',
      coordinates: [
        [91.55, 26.196], [91.62, 26.19], [91.68, 26.205], [91.74, 26.213],
        [91.81, 26.219], [91.88, 26.214], [91.95, 26.225], [92.02, 26.218],
      ],
    },
  }],
}

export const waterBodies: FeatureCollection<Polygon, { name: string; source: string }> = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    properties: { name: 'Deepor Beel', source: 'Illustrative simplified extent; verify against authoritative wetland data' },
    geometry: {
      type: 'Polygon',
      coordinates: [[[91.613, 26.108], [91.628, 26.095], [91.657, 26.093], [91.68, 26.106], [91.665, 26.122], [91.636, 26.124], [91.613, 26.108]]],
    },
  }],
}

export const infrastructure: FeatureCollection<Point, { name: string; kind: 'hospital' | 'school' | 'bridge' }> = {
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', properties: { name: 'Gauhati Medical College & Hospital', kind: 'hospital' }, geometry: { type: 'Point', coordinates: [91.7686, 26.1542] } },
    { type: 'Feature', properties: { name: 'Dr. B. Borooah Cancer Institute', kind: 'hospital' }, geometry: { type: 'Point', coordinates: [91.766, 26.16] } },
    { type: 'Feature', properties: { name: 'Gauhati University', kind: 'school' }, geometry: { type: 'Point', coordinates: [91.6659, 26.1543] } },
    { type: 'Feature', properties: { name: 'Cotton University', kind: 'school' }, geometry: { type: 'Point', coordinates: [91.7509, 26.1878] } },
    { type: 'Feature', properties: { name: 'Saraighat Bridge', kind: 'bridge' }, geometry: { type: 'Point', coordinates: [91.6638, 26.1695] } },
    { type: 'Feature', properties: { name: 'New Saraighat Bridge', kind: 'bridge' }, geometry: { type: 'Point', coordinates: [91.6612, 26.1718] } },
  ],
}

export const demoAnalysis: AreaAnalysis = {
  id: 'demo-analysis',
  name: 'User Selected Area',
  areaKm2: 4.8,
  floodRisk: 82,
  landslideRisk: 31,
  overallRisk: 'High',
  elevation: { average: 58, minimum: 41, maximum: 86 },
  slope: 7.4,
  rainfall: { daily: 182, weekly: 412 },
  river: { name: 'Brahmaputra', distanceKm: 1.4, floodAssociation: 'High', floodplainClass: 'Near floodplain · illustrative' },
  drainageDensity: 4.8,
  soil: 'Alluvial sandy loam · demo',
  landUse: { builtUp: 54, vegetation: 27, water: 8, other: 11 },
  exposure: { population: 18430, buildings: 3210, hospitals: 3, schools: 12, roadsKm: 18 },
  history: [
    { id: 'h18', year: 2018, type: 'Flood', severity: 'Moderate', detail: 'Illustrative urban inundation record.' },
    { id: 'h19', year: 2019, type: 'Flood', severity: 'High', detail: 'Illustrative high-rainfall flood record.' },
    { id: 'h21', year: 2021, type: 'Flood', severity: 'High', detail: 'Illustrative flood disruption record.' },
    { id: 'h22', year: 2022, type: 'Landslide', severity: 'Moderate', detail: 'Illustrative slope-failure record.' },
    { id: 'h24', year: 2024, type: 'Flood', severity: 'High', detail: 'Illustrative recent flood record.' },
  ],
  trends: [
    { year: 2018, floodIncidents: 2, rainfall: 132, risk: 58 },
    { year: 2019, floodIncidents: 4, rainfall: 178, risk: 74 },
    { year: 2020, floodIncidents: 3, rainfall: 151, risk: 66 },
    { year: 2021, floodIncidents: 5, rainfall: 196, risk: 81 },
    { year: 2022, floodIncidents: 3, rainfall: 164, risk: 69 },
    { year: 2023, floodIncidents: 2, rainfall: 143, risk: 61 },
    { year: 2024, floodIncidents: 5, rainfall: 204, risk: 84 },
  ],
  modelExplanation: [
    { factor: 'Rainfall', contribution: 0.34 },
    { factor: 'Low elevation', contribution: 0.27 },
    { factor: 'River proximity', contribution: 0.21 },
    { factor: 'Slope', contribution: 0.12 },
    { factor: 'Drainage density', contribution: 0.1 },
    { factor: 'Land use', contribution: 0.07 },
  ],
  confidence: 76,
}
