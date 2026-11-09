export interface Bounds {
  west: number
  south: number
  east: number
  north: number
}

export interface Endpoints {
  upstream: { name: string; lon: number; lat: number }
  downstream: { name: string; lon: number; lat: number }
}

export interface Highlight {
  id: string
  display: string
  label: string
  detail: string
}

export interface FeatureChip {
  icon: string
  title: string
  detail: string
}

export interface SourceStatus {
  id: string
  name: string
  kind: string
  status: string
  status_label: string
  scene_count: number
  latest_label: string | null
  detail: string
  validation_status: string
}

export interface ChangeRow {
  id: string
  label: string
  display: string | null
  tone: string
  detail: string
}

export interface ChangeStats {
  available: boolean
  earlier_id: string | null
  later_id: string | null
  earlier_label: string | null
  later_label: string | null
  earlier_short: string | null
  later_short: string | null
  erosion_km2: number | null
  deposition_km2: number | null
  persistent_km2: number | null
  erosion_display: string | null
  deposition_display: string | null
  persistent_display: string | null
  net_water_change_km2: number | null
  net_water_change_display: string | null
  earlier_water_km2: number | null
  later_water_km2: number | null
  unit: string
  validation_status: string
  disclaimer: string
  erosion_png: string | null
  deposition_png: string | null
  river_png?: string | null
  later_water_display?: string | null
  microwave_water_display?: string | null
  microwave_png?: string | null
  optical_scene?: string | null
  microwave_scene?: string | null
  bounds: Bounds | null
  note: string | null
  rows: ChangeRow[]
  centerline?: GeoJSON.Feature | null
}

export interface LatestObservation {
  available: boolean
  mask_id: string | null
  date_label: string | null
  sensor: string | null
  status_label: string
  validation_status: string
  water_display: string | null
  river_png: string | null
  bounds: Bounds | null
  note: string
}

export interface MethodStep {
  title: string
  short: string
  detail: string
}

export interface MethodParameters {
  opening_radius_m: number
  recovery_distance_m: number
  min_patch_ha: number
  min_patch_pixels: number
  water_value: number
  nodata_value: number
  reference: string
}

export interface StudyArea {
  coverage: string
  extent: string
  length_km: number
  length_display: string | null
  crs: string
  mask_coverage: string
  mask_length_km: number | null
  mask_length_display: string | null
  endpoints: Endpoints
  centerline: GeoJSON.Feature
  footprint: Bounds | null
}

export interface PortalSummary {
  portal: {
    title: string
    subtitle: string
    status_badge: string
    live: boolean
  }
  hero: {
    eyebrow?: string
    title: string
    accent?: string
    lede: string
  }
  features: FeatureChip[]
  highlights: Highlight[]
  study_area: StudyArea
  sources: SourceStatus[]
  latest_observation: LatestObservation
  recent_change: ChangeStats
  method_steps: MethodStep[]
  method: MethodParameters | null
  disclaimer: string
  year_min: number | null
  year_max: number | null
  mask_count: number
  files_on_disk: number
  catalog_built_at: string | null
  gee: { available: boolean; reason: string }
}

export interface WaterMask {
  id: string
  year: number
  season: string
  season_label: string
  copy_index: number
  label: string
  short_label: string
  filename: string
  water_km2: number
  water_display: string
  observed_fraction: number
  river_pixels: number
  status: string
  validation_status: string
  source_id: string
  river_png: string
  bounds: Bounds
}

export interface SectionHit {
  section_id: string
  reach_id: string
  chainage_m: number
  chainage_display: string
  distance_m: number
  width_earlier_m: number | null
  width_later_m: number | null
  left_delta_m: number | null
  right_delta_m: number | null
  left_class: string
  right_class: string
  left_label: string
  right_label: string
  qc: string
  lon: number
  lat: number
}

export interface ZoneHit {
  change_class: string
  area_km2: number
  area_display: string | null
  centroid_lat: number
  centroid_lon: number
  earlier_label: string
  later_label: string
}

export interface IdentifyResult {
  latitude: number
  longitude: number
  inside_footprint: boolean
  message: string
  pixel_class: string
  pixel_label: string
  earlier_label: string
  later_label: string
  section: SectionHit | null
  zone: ZoneHit | null
}

export interface ProfileSection {
  section_id: string
  reach_id: string
  chainage_m: number
  lon: number
  lat: number
  width_earlier_m: number | null
  width_later_m: number | null
  left_delta_m: number | null
  right_delta_m: number | null
  qc: string
  left_lon: number | null
  left_lat: number | null
  right_lon: number | null
  right_lat: number | null
}

export interface ProfileReach {
  reach_id: string
  chainage_start_m: number
  chainage_end_m: number
  n_sections: number
  n_valid: number
  mean_width_earlier_m: number | null
  mean_width_later_m: number | null
  mean_left_delta_m: number | null
  mean_right_delta_m: number | null
  max_retreat_m: number | null
  lon: number
  lat: number
}

export interface WidthProfile {
  earlier_id: string
  later_id: string
  earlier_label: string
  later_label: string
  section_step_m: number
  reach_step_m: number
  tolerance_m: number
  n_sections: number
  n_valid: number
  mean_width_earlier_m: number | null
  mean_width_later_m: number | null
  max_retreat_m: number | null
  sections: ProfileSection[]
  reaches: ProfileReach[]
}

export interface ChangePoint {
  rank: number
  area_km2: number
  area_display: string
  latitude: number
  longitude: number
}

export interface ChangePoints {
  later_id: string
  earlier_id: string
  later_label: string
  earlier_label: string
  shown: number
  erosion_count: number
  deposition_count: number
  erosion: ChangePoint[]
  deposition: ChangePoint[]
}

export type ViewId = 'analysis' | 'data'
