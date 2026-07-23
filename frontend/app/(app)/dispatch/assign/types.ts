// Shared types for the Assignment Helper + Coverage feature (S5).
// Mirrors the backend API contract verbatim — see build brief for the source of truth.

export type Tier = 'trusted' | 'watch' | 'chronic'

export type Decision = 'take' | 'pass'

/** Driver suggestion shape — used by intake suggestions, backup candidates, and coverage direct options. */
export interface DriverSuggestion {
  person_id: number
  name: string
  tier: Tier
  score: number
  reasons: string[]
  familiar_rides: number
  load_recent: number
  home_area: string | null
}

/** Coverage's "direct" options are a lighter driver shape — no score/familiar/load fields. */
export interface CoverageDirectOption {
  person_id: number
  name: string
  tier: Tier
  reasons: string[]
}

export interface Pricing {
  predicted_rate: number
  margin: number
  margin_pct: number
  unprofitable: boolean
  evidence: string | null
  manual_review: boolean
  pass_through_suggestion: number | null
}

export interface ParsedRide {
  school: string
  direction: string
  number: string
  is_odt: boolean
  wheelchair: boolean
  miles: number
  net_pay: number
  days: string[] | string
  start_time: string
  notes: string
}

export interface IntakeResponse {
  intake_id: number
  parsed: ParsedRide
  suggestions: DriverSuggestion[]
  pricing: Pricing
  reply_draft: string
}

export interface IntakeListItem {
  intake_id: number
  created_at: string
  status: string
  parsed: ParsedRide
  decision_reason: string | null
}

export interface IntakesResponse {
  intakes: IntakeListItem[]
}

export interface SuggestResponse {
  suggestions: DriverSuggestion[]
  pricing: Pricing
}

export interface RosterBackup {
  person_id: number
  name: string
  rank: number
}

export interface RosterRow {
  roster_id: number
  source: string
  school: string
  direction: string
  number: string
  is_odt: boolean
  service_name_sample: string
  primary: { person_id: number; name: string } | null
  backups: RosterBackup[]
  last_seen_ride_ts: string | null
  active: boolean
}

export interface RostersResponse {
  rosters: RosterRow[]
}

export interface RosterSyncResult {
  created: number
  updated: number
  deactivated: number
}

export interface BackupCandidatesResponse {
  candidates: DriverSuggestion[]
}

export interface ChainMove {
  person_id: number
  name: string
  action: string
}

export interface CoverageChain {
  moves: ChainMove[]
  description: string
}

export interface CoverageResponse {
  direct: CoverageDirectOption[]
  chains: CoverageChain[]
  notes: string[]
}

export interface HomeGapDriver {
  person_id: number
  name: string
  recent_rides: number
}

export interface HomeGapsResponse {
  drivers: HomeGapDriver[]
}

// ── Small display helpers shared across components ──

export const TIER_STYLES: Record<Tier, { label: string; cls: string; dot: string }> = {
  trusted: {
    label: 'trusted',
    cls: 'bg-emerald-500/15 text-emerald-500 border border-emerald-500/30',
    dot: 'bg-emerald-400',
  },
  watch: {
    label: 'watch',
    cls: 'bg-amber-500/15 text-amber-500 border border-amber-500/30',
    dot: 'bg-amber-400',
  },
  chronic: {
    label: 'chronic',
    cls: 'bg-red-500/15 text-red-500 border border-red-500/30',
    dot: 'bg-red-400',
  },
}

export function daysToText(days: string[] | string | undefined): string {
  if (!days) return '—'
  return Array.isArray(days) ? days.join(', ') : days
}
