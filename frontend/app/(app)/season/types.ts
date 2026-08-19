// Shared types for the Season Assignment Board (S10).
// Mirrors backend/routes/season_board.py contracts — see docs/SEASON-BOARD-PLAN.md §API.

export type DayPart = 'AM' | 'PM' | 'MID'
export type RideDirection = 'IB' | 'OB'
export type RideStatus = 'unassigned' | 'assigned' | 'inactive'
export type LoopStatus = 'proposed' | 'confirmed' | 'dismissed'
export type LoopOrigin = 'system' | 'manual'

export interface RequiresFlags {
  wheelchair?: boolean
  car_seat?: boolean
  booster?: boolean
  harness?: boolean
  monitor?: boolean
}

export interface CapabilitiesFlags {
  car_seat: boolean
  booster: boolean
  harness: boolean
  monitor_ok: boolean
  wheelchair_vehicle: boolean
}

// Only wheelchair gates assignment — car seat/booster/harness are equipment
// Maz hands out, and FirstAlt provides monitors. This drives the capabilities
// page columns; the other CapabilitiesFlags keys remain valid stored data.
export const CAPABILITY_FIELDS: (keyof CapabilitiesFlags)[] = [
  'wheelchair_vehicle',
]

export const CAPABILITY_LABELS: Record<keyof CapabilitiesFlags, string> = {
  car_seat: 'Car seat',
  booster: 'Booster',
  harness: 'Harness',
  monitor_ok: 'Monitor OK',
  wheelchair_vehicle: 'Wheelchair vehicle',
}

/** ride.requires key -> driver.capabilities key it must be covered by */
export const REQUIRES_TO_CAPABILITY: Record<keyof RequiresFlags, keyof CapabilitiesFlags> = {
  wheelchair: 'wheelchair_vehicle',
  car_seat: 'car_seat',
  booster: 'booster',
  harness: 'harness',
  monitor: 'monitor_ok',
}

export interface AssignedPerson {
  person_id: number
  name: string
}

export interface RideNeeds {
  address: boolean
  time: boolean
}

export interface RideOut {
  season_ride_id: number
  /** Partner company: 'firstalt' | 'everdriven' — exports are split per company. */
  source?: string
  school_display: string
  direction: RideDirection
  number: string
  is_odt: boolean
  days: string | null
  pickup_city: string | null
  dropoff_city: string | null
  pickup_address?: string | null
  dropoff_address?: string | null
  pickup_time: string | null
  dropoff_time: string | null
  requires: RequiresFlags
  status: RideStatus
  assigned_person: AssignedPerson | null
  loop_id: number | null
  needs: RideNeeds
  notes?: string | null
  /** Best-fit drivers for single-ride assignment, fairness-first (unassigned rides only). */
  suggestions?: DriverSuggestion[]
}

export interface Corridor {
  pickup_city: string | null
  dropoff_city: string | null
  rides: RideOut[]
}

export interface BoardStats {
  total: number
  assigned: number
  unassigned: number
  needs_info: number
}

export interface BoardResponse {
  stats: BoardStats
  corridors: Corridor[]
  unplaced: RideOut[]
  districts: string[]
  /** person_id -> assigned season rides, season-wide (ignores board filters). */
  driver_ride_counts?: Record<string, number>
}

export interface LoopMeta {
  /** Idle-gap minutes before each leg after the first (one entry per chained gap). */
  slack_minutes?: number[]
  requires_profile?: RequiresFlags
  companion_hint?: string
  builder_version?: string
  [key: string]: unknown
}

export interface LoopOut {
  loop_id: number
  season: string
  label: string
  day_part: DayPart
  days: string | null
  person_id: number | null
  person_name?: string | null
  status: LoopStatus
  origin: LoopOrigin
  meta: LoopMeta
  /** Top-level fields as actually serialized by GET /season/loops. */
  slack_minutes?: number[]
  requires_profile?: RequiresFlags
  companion_loop_id?: number | null
  /** Set when this proposal chains cleanly onto a confirmed loop's day. */
  extension_hint?: { loop_id: number; label: string; driver: string } | null
  person?: { person_id: number; name: string } | null
  suggestions?: DriverSuggestion[]
  rides: RideOut[]
}

export interface DriverSuggestion {
  person_id: number
  name: string
  score: number
  reasons: string[]
}

export interface ImportError {
  /** Sheet row number (null for file-level errors); intake imports use intake_id instead. */
  row?: number | null
  intake_id?: number
  message: string
}

export interface ImportReport {
  total_rows: number
  created: number
  updated: number
  schools_created: number
  /** PDFs accepted and parked for the background worker instead of imported
   *  inline — absent on older backend responses, so keep it optional. */
  queued?: number
  errors: ImportError[]
}

export interface SchoolRow {
  school_id: number
  name: string
  display_name: string
  address: string | null
  city: string | null
  district: string | null
  notes: string | null
  ride_count: number
  needs_address: boolean
}

export interface DriverCapabilityRow {
  person_id: number
  name: string
  capabilities: CapabilitiesFlags | null
}

export const DEFAULT_SEASON = '2026-27'

export const WEEKDAY_CHIPS: { code: string; label: string }[] = [
  { code: 'M', label: 'M' },
  { code: 'T', label: 'T' },
  { code: 'W', label: 'W' },
  { code: 'R', label: 'R' },
  { code: 'F', label: 'F' },
]
