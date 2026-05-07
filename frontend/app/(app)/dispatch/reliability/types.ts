// ─── Driver Reliability page — shared types ───────────────────────────────────

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
    // Primary axes (drive composite)
    self_serve: AxisScore
    on_time_pickup_arrival: AxisScore
    // Legacy axes (informational, weight=0)
    acceptance: AxisScore
    on_time_start: AxisScore
    on_time_completion: AxisScore
    responsiveness: AxisScore
    reliability: AxisScore
  }
  wow_delta: number | null
  // Phase 4 — week-over-week delta from scorecard_cache
  wow_escalation_delta: number | null   // positive = more escalations (worse)
  wow_composite_delta: number | null    // positive = score improved
  headline_metric: string | null
  focus_area: string | null
  low_sample: boolean
  // Escalation signal — the primary coaching metric
  escalation_count: number
  self_serve_pct: number | null
  revenue_impact: number
  revenue_impact_per_trip: number
  revenue_rank: number | null
}

// Phase 4 — 30-day rolling average row (returned when window=30d)
export interface RollingRow {
  person_id: number
  driver_name: string
  window: '30d'
  weeks_found: number
  total_trips: number
  self_serve_pct: number | null
  on_time_pct: number | null
  escalation_count: number | null
  composite_score: number | null
}

export type ViewWindow = 'weekly' | '30d'

export type SortKey =
  | 'driver_name'
  | 'escalation_count'
  | 'self_serve_pct'
  | 'on_time_pickup_arrival'
  | 'composite_score'
  | 'total_trips'
  | 'revenue_impact'
  | 'wow_escalation_delta'

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
