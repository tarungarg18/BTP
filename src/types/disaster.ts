import type { Feature, Polygon } from 'geojson'

export type HazardMode = 'flood' | 'landslide' | 'combined'
export type RiskLevel = 'Low' | 'Moderate' | 'High' | 'Very High'
export type RainfallScenario = 'Normal' | 'Heavy Rain' | 'Extreme Rain'

export interface RiskZoneProperties {
  id: string
  name: string
  floodRisk: number
  landslideRisk: number
  elevation: number
  riverDistance: number
  historicalEvents: number
}

export type RiskZoneFeature = Feature<Polygon, RiskZoneProperties>

export interface HistoricalEvent {
  id: string
  year: number
  type: 'Flood' | 'Landslide'
  severity: RiskLevel
  detail: string
}

export interface TrendPoint {
  year: number
  floodIncidents: number
  rainfall: number
  risk: number
}

export interface ModelFactor {
  factor: string
  contribution: number
}

export interface AreaAnalysis {
  id: string
  name: string
  areaKm2: number
  floodRisk: number
  landslideRisk: number
  overallRisk: RiskLevel
  elevation: { average: number; minimum: number; maximum: number }
  slope: number
  rainfall: { daily: number; weekly: number }
  river: {
    name: string
    distanceKm: number
    floodAssociation: RiskLevel
    floodplainClass: string
  }
  drainageDensity: number
  soil: string
  landUse: { builtUp: number; vegetation: number; water: number; other: number }
  exposure: {
    population: number
    buildings: number
    hospitals: number
    schools: number
    roadsKm: number
  }
  history: HistoricalEvent[]
  trends: TrendPoint[]
  modelExplanation: ModelFactor[]
  confidence: number
}

export interface LayerState {
  flood: boolean
  landslide: boolean
  combined: boolean
  rivers: boolean
  waterBodies: boolean
  elevation: boolean
  slope: boolean
  rainfall: boolean
  roads: boolean
  buildings: boolean
  hospitals: boolean
  schools: boolean
  bridges: boolean
  population: boolean
  criticalInfrastructure: boolean
}

export interface SearchPlace {
  name: string
  detail: string
  coordinates: [number, number]
  zoom: number
}

export interface DrawnGeometry {
  feature: Feature<Polygon>
  areaKm2: number
}
