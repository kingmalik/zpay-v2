// ─── Phase 7: Driver Reliability page — shared types ─────────────────────────

export interface AxisScore {
  raw: number
  normalized: number
  weighted: number
  sample_size: number
  available: boolean
}

export interface ScorecardRow {
  person_id: number
  driver_name: string
  week_iso: string
  total_trips: number
  tier: string        // 'gold' | 'silver' | 'bronze' | 'probation' | 'no_activity'
  tier_label: string
  composite_score: number | null
  axes: {
    acceptance_rate: AxisScore
    on_time_start: AxisScore
    on_time_arrival: AxisScore
    on_time_completion: AxisScore
    responsiveness: AxisScore
    reliability: AxisScore
  }
  wow_delta: number | null
  headline_metric: string | null
  focus_area: string | null
  low_sample: boolean
}

export type SortKey =
  | 'driver_name'
  | 'tier'
  | 'composite_score'
  | 'acceptance_rate'
  | 'on_time_start'
  | 'on_time_arrival'
  | 'on_time_completion'
  | 'responsiveness'
  | 'reliability'
  | 'wow_delta'
  | 'total_trips'

export type SortDir = 'asc' | 'desc'

export interface SortState {
  key: SortKey
  dir: SortDir
}

// Tier ordering for sort (gold=1, silver=2, bronze=3, probation=4, no_activity=5)
export const TIER_ORDER: Record<string, number> = {
  gold: 1,
  silver: 2,
  bronze: 3,
  probation: 4,
  no_activity: 5,
}
