import { API_URL, api } from '@/lib/api'
import type {
  BoardResponse, CapabilitiesFlags, DriverCapabilityRow, ImportReport, LoopOut, RideOut, SchoolRow,
} from './types'

export interface BoardQuery {
  season: string
  district?: string
  day_part?: string
  weekday?: string
}

function qs(params: Record<string, string | undefined>): string {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v) usp.set(k, v)
  }
  const s = usp.toString()
  return s ? `?${s}` : ''
}

function toParams(query: BoardQuery): Record<string, string | undefined> {
  return { season: query.season, district: query.district, day_part: query.day_part, weekday: query.weekday }
}

export function getBoard(query: BoardQuery): Promise<BoardResponse> {
  return api.get<BoardResponse>(`/api/data/season/board${qs(toParams(query))}`)
}

export async function getLoops(season: string): Promise<LoopOut[]> {
  // Backend envelope: {"loops": [...]}
  const res = await api.get<{ loops: LoopOut[] }>(`/api/data/season/loops${qs({ season })}`)
  return res.loops ?? []
}

export function proposeLoops(body: { season: string; day_part?: string; weekday?: string }): Promise<unknown> {
  return api.post('/api/data/season/loops/propose', body)
}

export function dismissLoop(loopId: number): Promise<unknown> {
  return api.post(`/api/data/season/loops/${loopId}/dismiss`)
}

export function unassignRide(rideId: number): Promise<unknown> {
  return api.post(`/api/data/season/rides/${rideId}/unassign`)
}

export function patchRide(rideId: number, body: Partial<RideOut> & Record<string, unknown>): Promise<RideOut> {
  return api.patch<RideOut>(`/api/data/season/rides/${rideId}`, body)
}

export function importFromInbox(): Promise<ImportReport> {
  return api.post<ImportReport>('/api/data/season/import', { from_intake: true })
}

export function importSheet(file: File): Promise<ImportReport> {
  const form = new FormData()
  form.append('file', file)
  return api.postForm<ImportReport>('/api/data/season/import', form)
}

export async function getSchools(): Promise<SchoolRow[]> {
  // Backend envelope: {"schools": [...]}
  const res = await api.get<{ schools: SchoolRow[] }>('/api/data/schools')
  return res.schools ?? []
}

export function patchSchool(schoolId: number, body: Partial<SchoolRow>): Promise<SchoolRow> {
  return api.patch<SchoolRow>(`/api/data/schools/${schoolId}`, body)
}

export function getCapabilities(): Promise<DriverCapabilityRow[]> {
  return api.get<DriverCapabilityRow[]>('/api/data/people/capabilities')
}

export function patchCapabilities(personId: number, capabilities: CapabilitiesFlags): Promise<DriverCapabilityRow> {
  return api.patch<DriverCapabilityRow>(`/api/data/people/${personId}/capabilities`, capabilities)
}

/** 409 = capability mismatch with a `reason`. Thrown as AssignConflictError so callers can offer an override. */
export class AssignConflictError extends Error {
  reason: string
  constructor(reason: string) {
    super(reason)
    this.name = 'AssignConflictError'
    this.reason = reason
  }
}

/**
 * Assigns a driver to a loop. The api client's generic error path collapses HTTP status codes,
 * so this call is made directly against the rewrite proxy to distinguish 409 (capability
 * mismatch — offer override) from other failures.
 */
export async function assignLoop(loopId: number, personId: number, override = false): Promise<LoopOut> {
  const res = await fetch(`${API_URL}/api/data/season/loops/${loopId}/assign`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    body: JSON.stringify({ person_id: personId, override }),
  })

  if (res.status === 409) {
    let reason = 'Driver capabilities do not cover this loop’s requirements'
    try {
      const body = await res.json()
      const detail = body?.detail
      reason = (typeof detail === 'string' ? detail : detail?.reason) || reason
    } catch {
      // body wasn't JSON — keep default reason
    }
    throw new AssignConflictError(reason)
  }

  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }

  return res.json()
}

export function extendLoop(confirmedLoopId: number, proposedLoopId: number): Promise<unknown> {
  return api.post(`/api/data/season/loops/${confirmedLoopId}/extend`, { proposed_loop_id: proposedLoopId })
}
