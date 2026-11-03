export type Status =
  | 'discovered'
  | 'queued'
  | 'processing'
  | 'processed'
  | 'failed_qc'
  | 'failed_processing'
  | 'no_usable_observation'

export interface StudyArea {
  name: string
  upstream: string
  downstream: string
  iwai_waterway: string
  endpoints: {
    upstream: { name: string; lon: number; lat: number }
    downstream: { name: string; lon: number; lat: number }
  }
  corridor_length_m: number
  disclaimer: string
  operational_pixel_m: number
  source?: string
  how_calculated?: string[]
  gee?: { available: boolean; reason?: string; project?: string }
}

export interface EpochSummary {
  id: string
  date: string
  sensors: string[]
  status: Status
  validation_status: string
  source: string
  method?: string
  scene_count?: number
}

export interface Acquisition {
  id: string
  sensor: string
  date: string
  status: string
  source: string
  scene_count?: number
  method?: string
}

export interface ReachStat {
  reach_id: string
  chainage_start_m: number
  chainage_end_m: number
  n_valid: number
  mean_width_a_m: number | null
  mean_width_b_m: number | null
  mean_left_delta_m: number | null
  mean_right_delta_m: number | null
  candidate_eroded_bank_length_m: number
  candidate_accreted_bank_length_m: number
  max_retreat_m: number
}

export interface Comparison {
  id: string
  epoch_a: string
  epoch_b: string
  epoch_a_id: string
  epoch_b_id: string
  tolerance_m: number
  disclaimer: string
  bank_changes?: GeoJSON.FeatureCollection
  change_polygons?: GeoJSON.FeatureCollection
  reach_statistics?: ReachStat[]
}
