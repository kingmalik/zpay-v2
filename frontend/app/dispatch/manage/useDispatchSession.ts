'use client'

import { useState, useEffect, useMemo } from 'react'
import { api } from '@/lib/api'

export type ChangeType = 'cover' | 'emergency' | 'swap' | 'reshuffle' | 'assign' | 'leave'
export type Company = 'firstalt' | 'everdriven' | 'both' | 'unknown'

export interface SessionChange {
  id: string
  type: ChangeType
  company: Company
  timestamp: string
  description: string
  detail: string
  pickup_time?: string   // HH:MM — used for time-conflict filtering
  dropoff_time?: string  // HH:MM — if unknown, pickup+60min assumed
  driverOut?: { person_id: number; name: string }
  driverIn?: { person_id: number; name: string }
}

interface TimeSlot { pickup: number; dropoff: number }

interface DispatchSession {
  date: string
  changes: SessionChange[]
}

const STORAGE_KEY_PREFIX = 'zpay_dispatch_session_'
const MAX_AGE_DAYS = 7

function storageKey(date: string) {
  return `${STORAGE_KEY_PREFIX}${date}`
}

function pruneOldSessions() {
  try {
    const cutoff = Date.now() - MAX_AGE_DAYS * 24 * 60 * 60 * 1000
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i)
      if (!key?.startsWith(STORAGE_KEY_PREFIX)) continue
      try {
        const raw = localStorage.getItem(key)
        if (!raw) continue
        const session: DispatchSession = JSON.parse(raw)
        const oldest = session.changes[0]?.timestamp
        if (oldest && new Date(oldest).getTime() < cutoff) localStorage.removeItem(key)
      } catch { localStorage.removeItem(key) }
    }
  } catch {}
}

function loadSession(date: string): DispatchSession {
  try {
    const raw = localStorage.getItem(storageKey(date))
    if (raw) return JSON.parse(raw)
  } catch {}
  return { date, changes: [] }
}

function saveSession(session: DispatchSession) {
  try { localStorage.setItem(storageKey(session.date), JSON.stringify(session)) } catch {}
}

// Parse "HH:MM", "H:MM AM/PM", "HH:MM:SS" → minutes since midnight
export function parseTimeToMinutes(t: string): number {
  if (!t) return -1
  const ampm = t.match(/(\d+):(\d+)(?::\d+)?\s*(AM|PM)?/i)
  if (!ampm) return -1
  let h = parseInt(ampm[1])
  const m = parseInt(ampm[2])
  const period = ampm[3]?.toUpperCase()
  if (period === 'PM' && h < 12) h += 12
  if (period === 'AM' && h === 12) h = 0
  return h * 60 + m
}

export function useDispatchSession(date: string) {
  const [session, setSession] = useState<DispatchSession>(() => {
    if (typeof window === 'undefined') return { date, changes: [] }
    pruneOldSessions()
    return loadSession(date)
  })

  useEffect(() => {
    if (typeof window === 'undefined') return
    setSession(loadSession(date))
  }, [date])

  useEffect(() => { saveSession(session) }, [session])

  // Map<person_id, TimeSlot[]> — for conflict checking
  const busySlots = useMemo<Map<number, TimeSlot[]>>(() => {
    const map = new Map<number, TimeSlot[]>()
    for (const c of session.changes) {
      if (!c.driverIn || !c.pickup_time) continue
      const pickup = parseTimeToMinutes(c.pickup_time)
      if (pickup < 0) continue
      const dropoff = c.dropoff_time ? parseTimeToMinutes(c.dropoff_time) : pickup + 60
      const existing = map.get(c.driverIn.person_id) ?? []
      map.set(c.driverIn.person_id, [...existing, { pickup, dropoff }])
    }
    return map
  }, [session.changes])

  function addChange(change: Omit<SessionChange, 'id' | 'timestamp'>) {
    const full: SessionChange = {
      ...change,
      id: typeof crypto !== 'undefined' ? crypto.randomUUID() : Math.random().toString(36).slice(2),
      timestamp: new Date().toISOString(),
    }
    setSession(prev => ({ ...prev, changes: [...prev.changes, full] }))
  }

  function removeChange(id: string) {
    setSession(prev => ({ ...prev, changes: prev.changes.filter(c => c.id !== id) }))
  }

  async function clearSession(saveLog = true) {
    if (saveLog && session.changes.length > 0) {
      try { await api.post('/dispatch/manage/session-log', { date: session.date, changes: session.changes }) } catch {}
    }
    const cleared: DispatchSession = { date: session.date, changes: [] }
    setSession(cleared)
    saveSession(cleared)
  }

  return { session, busySlots, addChange, removeChange, clearSession }
}

export function detectCompany(sources?: string[]): Company {
  if (!sources || sources.length === 0) return 'unknown'
  const hasFA = sources.some(s => s.toLowerCase().includes('first') || s === 'firstalt')
  const hasED = sources.some(s => s.toLowerCase().includes('ever') || s === 'everdriven')
  if (hasFA && hasED) return 'both'
  if (hasFA) return 'firstalt'
  if (hasED) return 'everdriven'
  return 'unknown'
}

// Filter recommendations by time-conflict with session assignments.
// Drivers are only deprioritized if the requested pickup_time genuinely
// overlaps an already-assigned slot — not just because they have any session change.
export function applySessionFilter(
  recs: { person_id: number; name: string; tier: number; tier_label: string; reason: string }[],
  busySlots: Map<number, TimeSlot[]>,
  newPickupTime?: string,
  newDropoffTime?: string,
): typeof recs {
  if (busySlots.size === 0 || !newPickupTime) return recs

  const np = parseTimeToMinutes(newPickupTime)
  if (np < 0) return recs
  const nd = newDropoffTime ? parseTimeToMinutes(newDropoffTime) : np + 60

  return recs.map(r => {
    const slots = busySlots.get(r.person_id)
    if (!slots) return r
    const conflict = slots.some(s => np < s.dropoff && nd > s.pickup)
    if (!conflict) return r
    return {
      ...r,
      tier: 5,
      tier_label: 'Time conflict (session)',
      reason: `${r.name} already has a session assignment that overlaps this time window`,
    }
  })
}
