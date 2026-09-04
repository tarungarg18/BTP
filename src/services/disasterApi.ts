import { demoAnalysis } from '../data/demoData'
import type {
  AreaAnalysis,
  DrawnGeometry,
  RainfallScenario,
  RiskZoneFeature,
} from '../types/disaster'

const SCENARIO_FLOOD_RISK: Record<RainfallScenario, number> = {
  Normal: 48,
  'Heavy Rain': 71,
  'Extreme Rain': 88,
}

function delay(durationMs: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, durationMs))
}

function copyAnalysis(analysis: AreaAnalysis): AreaAnalysis {
  return structuredClone(analysis)
}

export async function analyzeArea(
  geometry: DrawnGeometry,
  scenario: RainfallScenario,
): Promise<AreaAnalysis> {
  await delay(650)
  const analysis = copyAnalysis(demoAnalysis)
  const scale = Math.min(1.18, Math.max(0.82, Math.sqrt(geometry.areaKm2 / 4.8)))

  analysis.areaKm2 = Number(geometry.areaKm2.toFixed(2))
  analysis.floodRisk = Math.min(94, Math.round(SCENARIO_FLOOD_RISK[scenario] * scale))
  analysis.landslideRisk = Math.min(79, Math.round(31 * (2 - scale)))
  analysis.overallRisk = analysis.floodRisk >= 78 ? 'High' : analysis.floodRisk >= 50 ? 'Moderate' : 'Low'
  analysis.exposure.population = Math.round(18430 * scale)
  analysis.exposure.buildings = Math.round(3210 * scale)

  return analysis
}

export async function analyzeRiskZone(
  zone: RiskZoneFeature,
  scenario: RainfallScenario,
): Promise<AreaAnalysis> {
  await delay(450)
  const analysis = copyAnalysis(demoAnalysis)
  const scenarioAdjustment = SCENARIO_FLOOD_RISK[scenario] - SCENARIO_FLOOD_RISK['Heavy Rain']

  analysis.id = zone.properties.id
  analysis.name = zone.properties.name
  analysis.areaKm2 = 5.6
  analysis.floodRisk = Math.min(96, Math.max(12, zone.properties.floodRisk + scenarioAdjustment))
  analysis.landslideRisk = zone.properties.landslideRisk
  analysis.elevation.average = zone.properties.elevation
  analysis.river.distanceKm = zone.properties.riverDistance
  analysis.overallRisk = Math.max(analysis.floodRisk, analysis.landslideRisk) >= 78
    ? 'High'
    : 'Moderate'

  return analysis
}

export function getScenarioFloodRisk(scenario: RainfallScenario): number {
  return SCENARIO_FLOOD_RISK[scenario]
}
