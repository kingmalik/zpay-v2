'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ShieldCheck, Zap, ArrowLeftRight, Repeat2, Plus, UserPlus,
  CalendarOff, Activity, Handshake, BarChart2, Loader2,
  CheckCircle2, AlertTriangle, Star, ArrowLeft, Search,
  Trash2, Clock, ChevronDown, BarChart, X, RefreshCw,
  MapPin, FileText
} from 'lucide-react'
import { api } from '@/lib/api'
import { todayStr } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Link from 'next/link'

// ─── Types ──────────────────────────────────────────────────────────────────

interface Trip {
  id?: string | number
  firstPickUp?: string
  tripStatus?: string
  status?: string
  serviceName?: string
  service_name?: string
  service_code?: string
  name?: string
  _source?: string
  pickupAddress?: string
  origin?: string
}

interface Driver {
  person_id: number
  name: string
  phone?: string
  address?: string
  trips?: Trip[]
  trip_count?: number
  sources?: string[]
}

interface Recommendation {
  person_id: number
  name: string
  tier: number
  tier_label: string
  reason: string
}

interface Promise_ {
  id: number
  person_id: number
  driver_name: string
  description: string
  promised_at: string
  fulfilled_at: string | null
  notes: string | null
}

interface Blackout {
  id: number
  person_id: number
  driver_name: string
  start_date: string
  end_date: string
  reason: string | null
  recurring: boolean
  recurring_days: number[] | null
}

interface Reliability {
  [person_id: number]: {
    total_trips: number
    acceptance_rate: number
    started_rate: number
    escalation_rate: number
    tier: number
  }
}

interface WeeklyLoad {
  week_start: string
  week_end: string
  average: number
  drivers: { person_id: number; name: string; ride_count: number; gross_pay: number; vs_avg: number }[]
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const MODES = [
  { id: 'cover',     label: 'Cover a Ride',     icon: ShieldCheck, color: 'text-[#667eea]',  bg: 'bg-[#667eea]/15' },
  { id: 'emergency', label: 'Emergency',         icon: Zap,         color: 'text-red-400',    bg: 'bg-red-500/15' },
  { id: 'reshuffle', label: 'Reshuffle Driver',  icon: ArrowLeftRight, color: 'text-orange-400', bg: 'bg-orange-500/15' },
  { id: 'swap',      label: 'Ride Swap',         icon: Repeat2,     color: 'text-amber-400',  bg: 'bg-amber-500/15' },
  { id: 'assign',    label: 'New Ride',          icon: Plus,        color: 'text-emerald-400',bg: 'bg-emerald-500/15' },
  { id: 'rampup',    label: 'New Driver',        icon: UserPlus,    color: 'text-cyan-400',   bg: 'bg-cyan-500/15' },
  { id: 'blackout',  label: 'Blackout',          icon: CalendarOff, color: 'text-rose-400',   bg: 'bg-rose-500/15' },
  { id: 'capacity',  label: 'Capacity Check',    icon: Activity,    color: 'text-violet-400', bg: 'bg-violet-500/15' },
  { id: 'promises',  label: 'Promises',          icon: Handshake,   color: 'text-pink-400',   bg: 'bg-pink-500/15' },
  { id: 'load',      label: 'Load Balance',      icon: BarChart2,   color: 'text-teal-400',   bg: 'bg-teal-500/15' },
]

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function tierStyle(tier: number) {
  switch (tier) {
    case 1: return { bg: 'bg-emerald-500/15 border-emerald-500/30', text: 'text-emerald-400', label: 'Best Match' }
    case 2: return { bg: 'bg-blue-500/15 border-blue-500/30',       text: 'text-blue-400',    label: 'Great' }
    case 3: return { bg: 'bg-amber-500/15 border-amber-500/30',     text: 'text-amber-400',   label: 'Good' }
    case 4: return { bg: 'bg-orange-500/15 border-orange-500/30',   text: 'text-orange-400',  label: 'Possible' }
    default: return { bg: 'bg-red-500/15 border-red-500/30',        text: 'text-red-400',     label: 'Conflict' }
  }
}

function reliabilityBadge(r?: { acceptance_rate: number; tier: number }) {
  if (!r) return null
  const color = r.tier === 1 ? 'text-emerald-400 bg-emerald-500/10' :
                r.tier === 2 ? 'text-blue-400 bg-blue-500/10' :
                r.tier === 3 ? 'text-amber-400 bg-amber-500/10' :
                               'text-red-400 bg-red-500/10'
  return <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${color}`}>{r.acceptance_rate}% acc.</span>
}

function tripLabel(t: Trip) {
  return t.serviceName || t.service_name || t.name || t.service_code || 'Trip'
}

function AutoManualToggle({ mode, setMode }: { mode: 'auto' | 'manual'; setMode: (m: 'auto' | 'manual') => void }) {
  return (
    <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100 w-fit">
      {(['auto', 'manual'] as const).map(m => (
        <button key={m} onClick={() => setMode(m)}
          className={`px-3 py-1 rounded-lg text-xs font-medium capitalize transition-all cursor-pointer
            ${mode === m ? 'bg-[#667eea] text-white' : 'dark:text-white/50 text-gray-500'}`}>
          {m}
        </button>
      ))}
    </div>
  )
}

function DriverSelect({ drivers, value, onChange, placeholder = 'Select driver', reliability }:
  { drivers: Driver[]; value: number | null; onChange: (id: number) => void; placeholder?: string; reliability: Reliability }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const selected = drivers.find(d => d.person_id === value)
  const filtered = drivers.filter(d => d.name.toLowerCase().includes(q.toLowerCase()))

  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2.5 rounded-xl text-sm
          dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200
          dark:text-white text-gray-700 focus:outline-none cursor-pointer">
        <span>{selected ? selected.name : <span className="dark:text-white/30 text-gray-400">{placeholder}</span>}</span>
        <ChevronDown className={`w-4 h-4 dark:text-white/30 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }}
            className="absolute z-50 top-full left-0 right-0 mt-1 rounded-xl shadow-xl
              dark:bg-[#1a1f2e] bg-white border dark:border-white/10 border-gray-200 overflow-hidden">
            <div className="p-2">
              <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search..."
                className="w-full px-3 py-2 rounded-lg text-sm dark:bg-white/5 bg-gray-50
                  dark:text-white text-gray-700 border dark:border-white/10 border-gray-200 focus:outline-none" />
            </div>
            <div className="max-h-52 overflow-y-auto divide-y dark:divide-white/5 divide-gray-50">
              {filtered.map(d => (
                <button key={d.person_id} onClick={() => { onChange(d.person_id); setOpen(false); setQ('') }}
                  className="w-full flex items-center justify-between gap-2 px-3 py-2.5 text-sm text-left
                    dark:hover:bg-white/5 hover:bg-gray-50 transition-colors cursor-pointer">
                  <div>
                    <p className="dark:text-white/80 text-gray-700 font-medium">{d.name}</p>
                    <p className="text-xs dark:text-white/30 text-gray-400">{d.trip_count || 0} trips today</p>
                  </div>
                  {reliabilityBadge(reliability[d.person_id])}
                </button>
              ))}
              {filtered.length === 0 && <p className="px-3 py-3 text-sm dark:text-white/30 text-gray-400">No results</p>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function RecommendationList({ recs, onConfirm, confirming, confirmed }:
  { recs: Recommendation[]; onConfirm?: (r: Recommendation) => void; confirming?: number | null; confirmed?: number | null }) {
  if (recs.length === 0)
    return <p className="text-sm dark:text-white/40 text-gray-400 text-center py-6">No available drivers found.</p>

  return (
    <div className="space-y-2">
      {recs.map((rec, i) => {
        const s = tierStyle(rec.tier)
        const isDone = confirmed === rec.person_id
        return (
          <motion.div key={rec.person_id} initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }}>
            <div className={`flex items-center gap-3 px-4 py-3 rounded-xl border ${s.bg} ${isDone ? 'ring-2 ring-emerald-500/40' : ''}`}>
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold flex-shrink-0 dark:bg-white/10 bg-white ${s.text}`}>
                #{i + 1}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="font-semibold dark:text-white text-gray-900 text-sm">{rec.name}</p>
                  <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${s.bg} ${s.text}`}>{rec.tier_label}</span>
                </div>
                <p className="text-xs dark:text-white/40 text-gray-400 mt-0.5 line-clamp-1">{rec.reason}</p>
              </div>
              {onConfirm && (
                isDone ? (
                  <div className="flex items-center gap-1 text-emerald-400 text-sm font-medium flex-shrink-0">
                    <CheckCircle2 className="w-4 h-4" /> Assigned
                  </div>
                ) : (
                  <button onClick={() => onConfirm(rec)} disabled={confirming !== null && confirming !== undefined}
                    className="px-3 py-2 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-sm font-semibold
                      hover:bg-emerald-500/25 transition-all disabled:opacity-40 cursor-pointer flex-shrink-0">
                    {confirming === rec.person_id ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Assign'}
                  </button>
                )
              )}
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}

// ─── Mode: Cover a Ride ───────────────────────────────────────────────────────

function CoverMode({ drivers, date, reliability }: { drivers: Driver[]; date: string; reliability: Reliability }) {
  const [subMode, setSubMode] = useState<'auto' | 'manual'>('auto')
  const [driverId, setDriverId] = useState<number | null>(null)
  const [tripIdx, setTripIdx] = useState<number | null>(null)
  const [searching, setSearching] = useState(false)
  const [recs, setRecs] = useState<Recommendation[]>([])
  const [confirming, setConfirming] = useState<number | null>(null)
  const [confirmed, setConfirmed] = useState<number | null>(null)

  const driver = drivers.find(d => d.person_id === driverId)
  const trips = driver?.trips || []
  const trip = tripIdx !== null ? trips[tripIdx] : null

  async function findCoverage() {
    if (!driver || !trip) return
    setSearching(true)
    setRecs([])
    try {
      const res = await api.post<{ recommendations: Recommendation[] }>('/dispatch/manage/cover-search', {
        exclude_person_id: driver.person_id,
        pickup_address: trip.pickupAddress || trip.origin || '',
        pickup_time: trip.firstPickUp || '',
        dropoff_time: '',
        ride_date: date,
        service_name: tripLabel(trip),
      })
      setRecs(res.recommendations || [])
    } catch (e) { console.error(e) }
    finally { setSearching(false) }
  }

  async function handleConfirm(rec: Recommendation) {
    if (!trip) return
    setConfirming(rec.person_id)
    try {
      await api.post('/dispatch/assign/confirm', {
        person_id: rec.person_id,
        pickup_address: trip.pickupAddress || trip.origin || 'TBD',
        dropoff_address: '',
        pickup_time: trip.firstPickUp || '',
        dropoff_time: '',
        ride_date: date,
        notes: `Cover for ${driver?.name}: ${tripLabel(trip)}`,
      })
      setConfirmed(rec.person_id)
    } catch (e) { console.error(e) }
    finally { setConfirming(null) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p className="text-sm dark:text-white/50 text-gray-500">Driver calls in sick. Pick their ride and find who covers it.</p>
        <AutoManualToggle mode={subMode} setMode={setSubMode} />
      </div>

      <GlassCard>
        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">Driver who can't make it</label>
            <DriverSelect drivers={drivers} value={driverId} onChange={id => { setDriverId(id); setTripIdx(null); setRecs([]); setConfirmed(null) }} reliability={reliability} />
          </div>

          {driver && trips.length > 0 && (
            <div>
              <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">Which ride needs coverage?</label>
              <div className="space-y-1.5">
                {trips.map((t, i) => (
                  <button key={i} onClick={() => { setTripIdx(i); setRecs([]); setConfirmed(null) }}
                    className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl border text-sm transition-all cursor-pointer
                      ${tripIdx === i
                        ? 'bg-[#667eea]/15 border-[#667eea]/40 dark:text-white text-gray-900'
                        : 'dark:bg-white/5 bg-gray-50 dark:border-white/8 border-gray-200 dark:text-white/70 text-gray-600 dark:hover:bg-white/8 hover:bg-gray-100'}`}>
                    <span>{tripLabel(t)}</span>
                    <span className="text-xs dark:text-white/40 text-gray-400">{t.firstPickUp || '—'}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {driver && trips.length === 0 && (
            <p className="text-sm dark:text-white/40 text-gray-400 italic">No trips today for {driver.name}.</p>
          )}
        </div>
      </GlassCard>

      {trip && subMode === 'auto' && (
        <div className="space-y-3">
          <button onClick={findCoverage} disabled={searching}
            className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-[#667eea] hover:bg-[#5a6fd6] text-white text-sm font-semibold transition-all disabled:opacity-40 cursor-pointer">
            {searching ? <><Loader2 className="w-4 h-4 animate-spin" /> Finding coverage...</> : <><Search className="w-4 h-4" /> Find Coverage</>}
          </button>
          {recs.length > 0 && <RecommendationList recs={recs} onConfirm={handleConfirm} confirming={confirming} confirmed={confirmed} />}
        </div>
      )}

      {trip && subMode === 'manual' && (
        <GlassCard>
          <p className="text-xs font-medium dark:text-white/50 text-gray-500 mb-3">Pick the driver yourself</p>
          <DriverSelect
            drivers={drivers.filter(d => d.person_id !== driverId)}
            value={confirmed}
            onChange={id => setConfirmed(id)}
            placeholder="Choose cover driver"
            reliability={reliability}
          />
          {confirmed && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              className="mt-3 flex items-center gap-2 text-emerald-400 text-sm font-medium">
              <CheckCircle2 className="w-4 h-4" />
              {drivers.find(d => d.person_id === confirmed)?.name} assigned to cover
            </motion.div>
          )}
        </GlassCard>
      )}
    </div>
  )
}

// ─── Mode: Emergency Scramble ─────────────────────────────────────────────────

function EmergencyMode({ drivers, date, reliability }: { drivers: Driver[]; date: string; reliability: Reliability }) {
  const [driverId, setDriverId] = useState<number | null>(null)
  const [tripIdx, setTripIdx] = useState<number | null>(null)
  const [minutesOut, setMinutesOut] = useState('')
  const [searching, setSearching] = useState(false)
  const [recs, setRecs] = useState<Recommendation[]>([])
  const [confirmed, setConfirmed] = useState<number | null>(null)
  const [confirming, setConfirming] = useState<number | null>(null)

  const driver = drivers.find(d => d.person_id === driverId)
  const trips = driver?.trips || []
  const trip = tripIdx !== null ? trips[tripIdx] : null

  async function scramble() {
    if (!driver || !trip) return
    setSearching(true)
    setRecs([])
    try {
      const res = await api.post<{ recommendations: Recommendation[] }>('/dispatch/manage/cover-search', {
        exclude_person_id: driver.person_id,
        pickup_address: trip.pickupAddress || trip.origin || '',
        pickup_time: trip.firstPickUp || '',
        dropoff_time: '',
        ride_date: date,
        service_name: tripLabel(trip),
        minutes_until_pickup: minutesOut ? parseInt(minutesOut) : 45,
      })
      setRecs(res.recommendations || [])
    } catch (e) { console.error(e) }
    finally { setSearching(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20">
        <Zap className="w-4 h-4 text-red-400 flex-shrink-0" />
        <p className="text-sm text-red-400">Driver ghosted or no-show. Time-sensitive — filters only drivers who can physically make it.</p>
      </div>

      <GlassCard>
        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">Who's not showing up</label>
            <DriverSelect drivers={drivers} value={driverId} onChange={id => { setDriverId(id); setTripIdx(null); setRecs([]) }} reliability={reliability} />
          </div>

          {driver && trips.length > 0 && (
            <div>
              <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">Affected ride</label>
              <div className="space-y-1.5">
                {trips.map((t, i) => (
                  <button key={i} onClick={() => { setTripIdx(i); setRecs([]) }}
                    className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl border text-sm transition-all cursor-pointer
                      ${tripIdx === i ? 'bg-red-500/10 border-red-500/30 text-red-400' : 'dark:bg-white/5 bg-gray-50 dark:border-white/8 border-gray-200 dark:text-white/70 text-gray-600'}`}>
                    <span>{tripLabel(t)}</span>
                    <span className="text-xs dark:text-white/40 text-gray-400">{t.firstPickUp || '—'}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">
              <Clock className="w-3.5 h-3.5 inline mr-1" />Minutes until pickup
            </label>
            <input type="number" value={minutesOut} onChange={e => setMinutesOut(e.target.value)} placeholder="45"
              className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200
                dark:text-white text-gray-700 focus:outline-none focus:border-red-500/60" />
          </div>
        </div>
      </GlassCard>

      {trip && (
        <>
          <button onClick={scramble} disabled={searching}
            className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-red-500 hover:bg-red-600 text-white text-sm font-semibold transition-all disabled:opacity-40 cursor-pointer">
            {searching ? <><Loader2 className="w-4 h-4 animate-spin" /> Scrambling...</> : <><Zap className="w-4 h-4" /> Scramble Now</>}
          </button>
          {recs.length > 0 && <RecommendationList recs={recs} onConfirm={r => setConfirmed(r.person_id)} confirming={confirming} confirmed={confirmed} />}
        </>
      )}
    </div>
  )
}

// ─── Mode: Reshuffle Driver ───────────────────────────────────────────────────

function ReshuffleMode({ drivers, date, reliability }: { drivers: Driver[]; date: string; reliability: Reliability }) {
  const [subMode, setSubMode] = useState<'auto' | 'manual'>('auto')
  const [driverId, setDriverId] = useState<number | null>(null)
  const [startDate, setStartDate] = useState(date)
  const [endDate, setEndDate] = useState(date)
  const [assignments, setAssignments] = useState<{ tripIdx: number; coverId: number | null }[]>([])
  const [optimizing, setOptimizing] = useState(false)
  const [autoResult, setAutoResult] = useState<{ trip: string; rec: string }[]>([])

  const driver = drivers.find(d => d.person_id === driverId)
  const trips = driver?.trips || []

  useEffect(() => {
    if (trips.length > 0) {
      setAssignments(trips.map((_, i) => ({ tripIdx: i, coverId: null })))
    }
  }, [driverId])

  async function autoOptimize() {
    if (!driver || trips.length === 0) return
    setOptimizing(true)
    try {
      const others = drivers.filter(d => d.person_id !== driverId)
      const body = {
        drivers: others.map(d => ({ person_id: d.person_id, name: d.name, address: d.address || '', trips: d.trips || [] })),
        trips_to_optimize: trips.map(t => ({
          name: tripLabel(t),
          pickup_time: t.firstPickUp || '',
          dropoff_time: '',
          pickup_address: t.pickupAddress || t.origin || '',
        })),
      }
      const res = await api.post<{ suggestions: { trip_name: string; recommendations: Recommendation[] }[] }>('/dispatch/simulate/optimize', body)
      setAutoResult((res.suggestions || []).map(s => ({
        trip: s.trip_name,
        rec: s.recommendations[0]?.name || 'No driver available',
      })))
    } catch (e) { console.error(e) }
    finally { setOptimizing(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p className="text-sm dark:text-white/50 text-gray-500">Driver is out for a period. Redistribute their rides.</p>
        <AutoManualToggle mode={subMode} setMode={setSubMode} />
      </div>

      <GlassCard>
        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">Driver who's out</label>
            <DriverSelect drivers={drivers} value={driverId} onChange={id => { setDriverId(id); setAutoResult([]) }} reliability={reliability} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">From</label>
              <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
                className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
            </div>
            <div>
              <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">To</label>
              <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
                className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
            </div>
          </div>
        </div>
      </GlassCard>

      {driver && trips.length > 0 && subMode === 'auto' && (
        <>
          <button onClick={autoOptimize} disabled={optimizing}
            className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl text-white text-sm font-semibold transition-all disabled:opacity-40 cursor-pointer"
            style={{ background: 'linear-gradient(135deg, #f97316, #ef4444)' }}>
            {optimizing ? <><Loader2 className="w-4 h-4 animate-spin" /> Redistributing...</> : <><ArrowLeftRight className="w-4 h-4" /> Auto Redistribute</>}
          </button>
          {autoResult.length > 0 && (
            <GlassCard>
              <p className="text-xs font-semibold dark:text-white/50 text-gray-500 uppercase tracking-wide mb-3">Suggested Assignments</p>
              <div className="space-y-2">
                {autoResult.map((r, i) => (
                  <div key={i} className="flex items-center justify-between px-3 py-2 rounded-xl dark:bg-white/5 bg-gray-50 border dark:border-white/8 border-gray-100">
                    <span className="text-sm dark:text-white/70 text-gray-600 truncate">{r.trip}</span>
                    <span className="text-sm font-medium text-emerald-400 ml-2 flex-shrink-0">→ {r.rec}</span>
                  </div>
                ))}
              </div>
            </GlassCard>
          )}
        </>
      )}

      {driver && trips.length > 0 && subMode === 'manual' && (
        <GlassCard>
          <p className="text-xs font-semibold dark:text-white/50 text-gray-500 uppercase tracking-wide mb-3">Assign each ride manually</p>
          <div className="space-y-3">
            {trips.map((t, i) => (
              <div key={i}>
                <p className="text-xs dark:text-white/60 text-gray-500 mb-1">{tripLabel(t)} · {t.firstPickUp || '—'}</p>
                <DriverSelect
                  drivers={drivers.filter(d => d.person_id !== driverId)}
                  value={assignments[i]?.coverId ?? null}
                  onChange={id => setAssignments(prev => prev.map((a, idx) => idx === i ? { ...a, coverId: id } : a))}
                  placeholder="Pick cover driver"
                  reliability={reliability}
                />
              </div>
            ))}
          </div>
        </GlassCard>
      )}
    </div>
  )
}

// ─── Mode: Ride Swap ──────────────────────────────────────────────────────────

function SwapMode({ drivers, reliability }: { drivers: Driver[]; reliability: Reliability }) {
  const [driverA, setDriverA] = useState<number | null>(null)
  const [tripA, setTripA] = useState<number | null>(null)
  const [driverB, setDriverB] = useState<number | null>(null)
  const [tripB, setTripB] = useState<number | null>(null)
  const [swapped, setSwapped] = useState(false)

  const dA = drivers.find(d => d.person_id === driverA)
  const dB = drivers.find(d => d.person_id === driverB)
  const tA = tripA !== null ? dA?.trips?.[tripA] : null
  const tB = tripB !== null ? dB?.trips?.[tripB] : null

  return (
    <div className="space-y-4">
      <p className="text-sm dark:text-white/50 text-gray-500">Two drivers want to trade routes. Pick one ride from each.</p>

      <div className="grid md:grid-cols-2 gap-4">
        <GlassCard>
          <p className="text-xs font-semibold dark:text-white/50 text-gray-500 uppercase tracking-wide mb-3">Driver A</p>
          <div className="space-y-3">
            <DriverSelect drivers={drivers.filter(d => d.person_id !== driverB)} value={driverA}
              onChange={id => { setDriverA(id); setTripA(null) }} reliability={reliability} />
            {dA && (dA.trips || []).map((t, i) => (
              <button key={i} onClick={() => setTripA(i)}
                className={`w-full text-left px-3 py-2 rounded-xl border text-sm transition-all cursor-pointer
                  ${tripA === i ? 'bg-[#667eea]/15 border-[#667eea]/40 dark:text-white text-gray-900' : 'dark:bg-white/5 bg-gray-50 dark:border-white/8 border-gray-100 dark:text-white/70 text-gray-600'}`}>
                {tripLabel(t)} · {t.firstPickUp || '—'}
              </button>
            ))}
          </div>
        </GlassCard>

        <GlassCard>
          <p className="text-xs font-semibold dark:text-white/50 text-gray-500 uppercase tracking-wide mb-3">Driver B</p>
          <div className="space-y-3">
            <DriverSelect drivers={drivers.filter(d => d.person_id !== driverA)} value={driverB}
              onChange={id => { setDriverB(id); setTripB(null) }} reliability={reliability} />
            {dB && (dB.trips || []).map((t, i) => (
              <button key={i} onClick={() => setTripB(i)}
                className={`w-full text-left px-3 py-2 rounded-xl border text-sm transition-all cursor-pointer
                  ${tripB === i ? 'bg-amber-500/15 border-amber-500/40 text-amber-400' : 'dark:bg-white/5 bg-gray-50 dark:border-white/8 border-gray-100 dark:text-white/70 text-gray-600'}`}>
                {tripLabel(t)} · {t.firstPickUp || '—'}
              </button>
            ))}
          </div>
        </GlassCard>
      </div>

      {tA && tB && !swapped && (
        <GlassCard>
          <p className="text-xs font-semibold dark:text-white/50 text-gray-500 uppercase tracking-wide mb-3">Swap Preview</p>
          <div className="flex items-center gap-3 text-sm">
            <span className="flex-1 px-3 py-2 rounded-xl dark:bg-white/5 bg-gray-50 dark:text-white/70 text-gray-600">{dA?.name} gets → {tripLabel(tB)}</span>
            <Repeat2 className="w-5 h-5 dark:text-white/30 text-gray-400 flex-shrink-0" />
            <span className="flex-1 px-3 py-2 rounded-xl dark:bg-white/5 bg-gray-50 dark:text-white/70 text-gray-600">{dB?.name} gets → {tripLabel(tA)}</span>
          </div>
          <button onClick={() => setSwapped(true)}
            className="mt-4 w-full px-5 py-3 rounded-xl bg-amber-500 hover:bg-amber-600 text-white text-sm font-semibold transition-all cursor-pointer">
            Confirm Swap
          </button>
        </GlassCard>
      )}

      {swapped && (
        <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
          className="flex items-center gap-3 px-4 py-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0" />
          <p className="text-sm text-emerald-400 font-medium">
            Swap recorded — {dA?.name} ↔ {dB?.name}. Update manually in EverDriven/FirstAlt.
          </p>
        </motion.div>
      )}
    </div>
  )
}

// ─── Mode: New Ride ───────────────────────────────────────────────────────────

function NewRideMode({ drivers, date, reliability }: { drivers: Driver[]; date: string; reliability: Reliability }) {
  const [subMode, setSubMode] = useState<'auto' | 'manual'>('auto')
  const [pickup, setPickup] = useState('')
  const [dropoff, setDropoff] = useState('')
  const [pickupTime, setPickupTime] = useState('')
  const [dropoffTime, setDropoffTime] = useState('')
  const [notes, setNotes] = useState('')
  const [searching, setSearching] = useState(false)
  const [recs, setRecs] = useState<Recommendation[]>([])
  const [confirmed, setConfirmed] = useState<number | null>(null)
  const [confirming, setConfirming] = useState<number | null>(null)
  const [manualPick, setManualPick] = useState<number | null>(null)

  async function search() {
    if (!pickup || !pickupTime) return
    setSearching(true)
    setRecs([])
    try {
      const form = new FormData()
      form.append('pickup_address', pickup)
      form.append('dropoff_address', dropoff)
      form.append('pickup_time', pickupTime)
      form.append('dropoff_time', dropoffTime)
      form.append('ride_date', date)
      form.append('notes', notes)
      const res = await api.postForm<{ recommendations: Recommendation[] }>('/dispatch/assign/search', form)
      setRecs(res.recommendations || [])
    } catch (e) { console.error(e) }
    finally { setSearching(false) }
  }

  async function confirm(rec: Recommendation) {
    setConfirming(rec.person_id)
    try {
      const form = new FormData()
      form.append('person_id', String(rec.person_id))
      form.append('pickup_address', pickup)
      form.append('dropoff_address', dropoff)
      form.append('pickup_time', pickupTime)
      form.append('dropoff_time', dropoffTime)
      form.append('ride_date', date)
      form.append('notes', notes)
      await api.postForm('/dispatch/assign/confirm', form)
      setConfirmed(rec.person_id)
    } catch (e) { console.error(e) }
    finally { setConfirming(null) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p className="text-sm dark:text-white/50 text-gray-500">New route coming in. Find the best driver for it.</p>
        <AutoManualToggle mode={subMode} setMode={setSubMode} />
      </div>

      <GlassCard>
        <div className="grid md:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5"><MapPin className="w-3.5 h-3.5 inline mr-1" />Pickup Address</label>
            <input value={pickup} onChange={e => setPickup(e.target.value)} placeholder="123 Main St"
              className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/20 placeholder:text-gray-300 focus:outline-none focus:border-[#667eea]/60" />
          </div>
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5"><MapPin className="w-3.5 h-3.5 inline mr-1" />Drop-off Address</label>
            <input value={dropoff} onChange={e => setDropoff(e.target.value)} placeholder="456 School Rd"
              className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/20 placeholder:text-gray-300 focus:outline-none focus:border-[#667eea]/60" />
          </div>
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5"><Clock className="w-3.5 h-3.5 inline mr-1" />Pickup Time</label>
            <input type="time" value={pickupTime} onChange={e => setPickupTime(e.target.value)}
              className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
          </div>
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5"><Clock className="w-3.5 h-3.5 inline mr-1" />Drop-off Time</label>
            <input type="time" value={dropoffTime} onChange={e => setDropoffTime(e.target.value)}
              className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
          </div>
        </div>
        <div className="mt-4">
          <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5"><FileText className="w-3.5 h-3.5 inline mr-1" />Notes</label>
          <input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Student name, special instructions..."
            className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/20 placeholder:text-gray-300 focus:outline-none focus:border-[#667eea]/60" />
        </div>
      </GlassCard>

      {subMode === 'auto' && (
        <>
          <button onClick={search} disabled={searching || !pickup || !pickupTime}
            className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-semibold transition-all disabled:opacity-40 cursor-pointer">
            {searching ? <><Loader2 className="w-4 h-4 animate-spin" /> Searching...</> : <><Search className="w-4 h-4" /> Find Best Driver</>}
          </button>
          {recs.length > 0 && <RecommendationList recs={recs} onConfirm={confirm} confirming={confirming} confirmed={confirmed} />}
        </>
      )}

      {subMode === 'manual' && (
        <GlassCard>
          <p className="text-xs font-medium dark:text-white/50 text-gray-500 mb-3">Pick the driver yourself</p>
          <DriverSelect drivers={drivers} value={manualPick} onChange={id => setManualPick(id)} placeholder="Choose driver" reliability={reliability} />
          {manualPick && (
            <button onClick={async () => { if (manualPick) { const r = drivers.find(d => d.person_id === manualPick); if (r) await confirm({ person_id: r.person_id, name: r.name, tier: 1, tier_label: 'Manual', reason: 'Manually selected' }) }}}
              className="mt-3 w-full px-5 py-2.5 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-sm font-semibold hover:bg-emerald-500/25 transition-all cursor-pointer">
              Confirm Assignment
            </button>
          )}
        </GlassCard>
      )}
    </div>
  )
}

// ─── Mode: New Driver Ramp-up ─────────────────────────────────────────────────

function RampupMode({ drivers, reliability }: { drivers: Driver[]; reliability: Reliability }) {
  const newDrivers = drivers.filter(d => {
    const r = reliability[d.person_id]
    return !r || r.total_trips < 10
  })

  const [driverId, setDriverId] = useState<number | null>(null)
  const driver = drivers.find(d => d.person_id === driverId)

  const candidates = drivers
    .filter(d => d.person_id !== driverId && (d.trip_count || 0) <= 2)
    .slice(0, 5)

  return (
    <div className="space-y-4">
      <p className="text-sm dark:text-white/50 text-gray-500">
        New hire or returning driver. Find the right first route — light load, close to home.
      </p>

      <GlassCard>
        <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">New driver</label>
        <DriverSelect drivers={newDrivers.length > 0 ? newDrivers : drivers} value={driverId} onChange={setDriverId} reliability={reliability} />
        {newDrivers.length === 0 && (
          <p className="text-xs dark:text-white/30 text-gray-400 mt-2">All drivers have history. Showing full roster.</p>
        )}
      </GlassCard>

      {driver && (
        <GlassCard>
          <p className="text-xs font-semibold dark:text-white/50 text-gray-500 uppercase tracking-wide mb-3">
            Recommended First Routes for {driver.name}
          </p>
          {candidates.length === 0 ? (
            <p className="text-sm dark:text-white/40 text-gray-400">No light routes available today. Check back tomorrow.</p>
          ) : (
            <div className="space-y-2">
              {candidates.map((c, i) => (
                <div key={c.person_id} className="flex items-center justify-between px-3 py-2.5 rounded-xl dark:bg-white/5 bg-gray-50 border dark:border-white/8 border-gray-100">
                  <div>
                    <p className="text-sm font-medium dark:text-white/80 text-gray-700">
                      {(c.trips || []).map(t => tripLabel(t)).join(', ') || 'No trips'}
                    </p>
                    <p className="text-xs dark:text-white/30 text-gray-400">{c.trip_count || 0} trips/day · {c.address || 'Address unknown'}</p>
                  </div>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-400 border border-cyan-500/30 font-medium">
                    Light load
                  </span>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      )}
    </div>
  )
}

// ─── Mode: Driver Blackout ────────────────────────────────────────────────────

function BlackoutMode({ drivers, blackouts, onAdd, onDelete }:
  { drivers: Driver[]; blackouts: Blackout[]; onAdd: (b: Omit<Blackout, 'id' | 'driver_name' | 'created_at'>) => Promise<void>; onDelete: (id: number) => Promise<void> }) {
  const [driverId, setDriverId] = useState<number | null>(null)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [reason, setReason] = useState('')
  const [recurring, setRecurring] = useState(false)
  const [recurringDays, setRecurringDays] = useState<number[]>([])
  const [saving, setSaving] = useState(false)
  const reliability: Reliability = {}

  async function save() {
    if (!driverId || !startDate || !endDate) return
    setSaving(true)
    try {
      await onAdd({ person_id: driverId, start_date: startDate, end_date: endDate, reason: reason || null, recurring, recurring_days: recurring ? recurringDays : null })
      setDriverId(null); setStartDate(''); setEndDate(''); setReason(''); setRecurring(false); setRecurringDays([])
    } finally { setSaving(false) }
  }

  const upcoming = blackouts.filter(b => b.end_date >= todayStr())
  const past = blackouts.filter(b => b.end_date < todayStr())

  return (
    <div className="space-y-4">
      <p className="text-sm dark:text-white/50 text-gray-500">Mark drivers as unavailable in advance so the system routes around them.</p>

      <GlassCard>
        <p className="text-sm font-semibold dark:text-white/70 text-gray-700 mb-4">Add Blackout</p>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">Driver</label>
            <DriverSelect drivers={drivers} value={driverId} onChange={setDriverId} reliability={reliability} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">From</label>
              <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
                className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
            </div>
            <div>
              <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">To</label>
              <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
                className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">Reason (optional)</label>
            <input value={reason} onChange={e => setReason(e.target.value)} placeholder="Vacation, doctor, etc."
              className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/20 focus:outline-none" />
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="recurring" checked={recurring} onChange={e => setRecurring(e.target.checked)}
              className="w-4 h-4 rounded accent-[#667eea] cursor-pointer" />
            <label htmlFor="recurring" className="text-sm dark:text-white/60 text-gray-600 cursor-pointer">Recurring weekly</label>
          </div>
          {recurring && (
            <div className="flex gap-1.5 flex-wrap">
              {WEEKDAYS.map((day, i) => (
                <button key={i} onClick={() => setRecurringDays(prev => prev.includes(i) ? prev.filter(d => d !== i) : [...prev, i])}
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all cursor-pointer
                    ${recurringDays.includes(i) ? 'bg-[#667eea] text-white' : 'dark:bg-white/5 bg-gray-100 dark:text-white/50 text-gray-500'}`}>
                  {day}
                </button>
              ))}
            </div>
          )}
          <button onClick={save} disabled={saving || !driverId || !startDate || !endDate}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-rose-500/15 border border-rose-500/30 text-rose-400 text-sm font-semibold hover:bg-rose-500/25 transition-all disabled:opacity-40 cursor-pointer">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CalendarOff className="w-4 h-4" />}
            Add Blackout
          </button>
        </div>
      </GlassCard>

      {upcoming.length > 0 && (
        <div>
          <p className="text-xs font-semibold dark:text-white/50 text-gray-500 uppercase tracking-wide mb-2">Upcoming Blackouts</p>
          <div className="space-y-2">
            {upcoming.map(b => (
              <div key={b.id} className="flex items-center justify-between px-4 py-3 rounded-xl dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200">
                <div>
                  <p className="text-sm font-medium dark:text-white/80 text-gray-700">{b.driver_name}</p>
                  <p className="text-xs dark:text-white/40 text-gray-400">{b.start_date} → {b.end_date}{b.reason ? ` · ${b.reason}` : ''}{b.recurring ? ' · Recurring' : ''}</p>
                </div>
                <button onClick={() => onDelete(b.id)} className="p-1.5 rounded-lg hover:bg-red-500/10 text-red-400 transition-colors cursor-pointer">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {upcoming.length === 0 && <p className="text-sm dark:text-white/30 text-gray-400 text-center py-6">No upcoming blackouts.</p>}
    </div>
  )
}

// ─── Mode: Capacity Check ─────────────────────────────────────────────────────

function CapacityMode({ drivers, reliability }: { drivers: Driver[]; reliability: Reliability }) {
  const [pickup, setPickup] = useState('')
  const [dropoff, setDropoff] = useState('')
  const [time, setTime] = useState('')
  const [checked, setChecked] = useState(false)

  const availableDrivers = drivers.filter(d => (d.trip_count || 0) < 3)
  const lightDrivers = drivers.filter(d => (d.trip_count || 0) <= 1)

  function check() { setChecked(true) }

  return (
    <div className="space-y-4">
      <p className="text-sm dark:text-white/50 text-gray-500">Before accepting a new contract, verify you can staff it.</p>

      <GlassCard>
        <div className="space-y-3">
          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">Route / Pickup Area</label>
              <input value={pickup} onChange={e => setPickup(e.target.value)} placeholder="Neighborhood or address"
                className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/20 focus:outline-none" />
            </div>
            <div>
              <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">School / Drop-off</label>
              <input value={dropoff} onChange={e => setDropoff(e.target.value)} placeholder="School name or address"
                className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/20 focus:outline-none" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">Pickup Time</label>
            <input type="time" value={time} onChange={e => setTime(e.target.value)}
              className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
          </div>
          <button onClick={check}
            className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl text-white text-sm font-semibold transition-all cursor-pointer"
            style={{ background: 'linear-gradient(135deg, #667eea, #8b5cf6)' }}>
            <Activity className="w-4 h-4" /> Check Capacity
          </button>
        </div>
      </GlassCard>

      {checked && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <div className="px-4 py-3 rounded-xl dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 text-center">
              <p className="text-2xl font-bold dark:text-white text-gray-900">{drivers.length}</p>
              <p className="text-xs dark:text-white/40 text-gray-400 mt-1">Total Drivers</p>
            </div>
            <div className="px-4 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-center">
              <p className="text-2xl font-bold text-emerald-400">{availableDrivers.length}</p>
              <p className="text-xs text-emerald-400/70 mt-1">Available (&lt;3 trips)</p>
            </div>
            <div className="px-4 py-3 rounded-xl bg-blue-500/10 border border-blue-500/20 text-center">
              <p className="text-2xl font-bold text-blue-400">{lightDrivers.length}</p>
              <p className="text-xs text-blue-400/70 mt-1">Light (&le;1 trip)</p>
            </div>
          </div>
          <GlassCard>
            <div className={`flex items-center gap-3 ${availableDrivers.length >= 3 ? 'text-emerald-400' : availableDrivers.length >= 1 ? 'text-amber-400' : 'text-red-400'}`}>
              {availableDrivers.length >= 3 ? <CheckCircle2 className="w-5 h-5 flex-shrink-0" /> : <AlertTriangle className="w-5 h-5 flex-shrink-0" />}
              <p className="text-sm font-medium">
                {availableDrivers.length >= 3
                  ? `You can take this contract. ${availableDrivers.length} drivers available.`
                  : availableDrivers.length >= 1
                  ? `Tight capacity. Only ${availableDrivers.length} driver(s) available — consider carefully.`
                  : 'Not enough capacity. You\'d need to hire before taking this route.'}
              </p>
            </div>
          </GlassCard>
        </motion.div>
      )}
    </div>
  )
}

// ─── Mode: Driver Promises ────────────────────────────────────────────────────

function PromisesMode({ drivers, promises, onAdd, onFulfill, onDelete }:
  { drivers: Driver[]; promises: Promise_[]; onAdd: (p: { person_id: number; description: string; notes?: string }) => Promise<void>; onFulfill: (id: number) => Promise<void>; onDelete: (id: number) => Promise<void> }) {
  const [driverId, setDriverId] = useState<number | null>(null)
  const [desc, setDesc] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const reliability: Reliability = {}

  async function save() {
    if (!driverId || !desc.trim()) return
    setSaving(true)
    try {
      await onAdd({ person_id: driverId, description: desc.trim(), notes: notes.trim() || undefined })
      setDriverId(null); setDesc(''); setNotes('')
    } finally { setSaving(false) }
  }

  const open = promises.filter(p => !p.fulfilled_at)
  const done = promises.filter(p => !!p.fulfilled_at)

  return (
    <div className="space-y-4">
      <p className="text-sm dark:text-white/50 text-gray-500">Track commitments you made to drivers — "next ride I get is yours."</p>

      <GlassCard>
        <p className="text-sm font-semibold dark:text-white/70 text-gray-700 mb-4">Add Promise</p>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">Driver you made a promise to</label>
            <DriverSelect drivers={drivers} value={driverId} onChange={setDriverId} reliability={reliability} />
          </div>
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">What you promised</label>
            <input value={desc} onChange={e => setDesc(e.target.value)} placeholder="Next available ride, specific route, higher z-rate..."
              className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/20 focus:outline-none" />
          </div>
          <div>
            <label className="text-xs font-medium dark:text-white/50 text-gray-500 block mb-1.5">Notes (optional)</label>
            <input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Context, when, why..."
              className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/20 focus:outline-none" />
          </div>
          <button onClick={save} disabled={saving || !driverId || !desc.trim()}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-pink-500/15 border border-pink-500/30 text-pink-400 text-sm font-semibold hover:bg-pink-500/25 transition-all disabled:opacity-40 cursor-pointer">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Handshake className="w-4 h-4" />}
            Record Promise
          </button>
        </div>
      </GlassCard>

      {open.length > 0 && (
        <div>
          <p className="text-xs font-semibold dark:text-white/50 text-gray-500 uppercase tracking-wide mb-2">Open Promises ({open.length})</p>
          <div className="space-y-2">
            {open.map(p => (
              <div key={p.id} className="flex items-start gap-3 px-4 py-3 rounded-xl dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium dark:text-white/80 text-gray-700">{p.driver_name}</p>
                  <p className="text-sm dark:text-white/50 text-gray-500 mt-0.5">{p.description}</p>
                  {p.notes && <p className="text-xs dark:text-white/30 text-gray-400 mt-0.5 italic">{p.notes}</p>}
                  <p className="text-xs dark:text-white/20 text-gray-300 mt-1">{new Date(p.promised_at).toLocaleDateString()}</p>
                </div>
                <div className="flex gap-1.5 flex-shrink-0">
                  <button onClick={() => onFulfill(p.id)}
                    className="p-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 transition-colors cursor-pointer" title="Mark fulfilled">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => onDelete(p.id)}
                    className="p-1.5 rounded-lg hover:bg-red-500/10 text-red-400 transition-colors cursor-pointer" title="Delete">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {open.length === 0 && <p className="text-sm dark:text-white/30 text-gray-400 text-center py-4">No open promises.</p>}

      {done.length > 0 && (
        <details className="group">
          <summary className="text-xs dark:text-white/30 text-gray-400 cursor-pointer hover:dark:text-white/50 hover:text-gray-600">
            {done.length} fulfilled promises
          </summary>
          <div className="mt-2 space-y-1.5">
            {done.map(p => (
              <div key={p.id} className="flex items-center gap-3 px-4 py-2.5 rounded-xl dark:bg-white/3 bg-gray-50 opacity-60">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm dark:text-white/60 text-gray-500">{p.driver_name} — {p.description}</p>
                </div>
                <button onClick={() => onDelete(p.id)} className="p-1 hover:text-red-400 transition-colors cursor-pointer">
                  <X className="w-3 h-3 dark:text-white/20 text-gray-300" />
                </button>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

// ─── Mode: Load Balance ───────────────────────────────────────────────────────

function LoadMode({ weeklyLoad, loading }: { weeklyLoad: WeeklyLoad | null; loading: boolean }) {
  if (loading) return <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin dark:text-white/30 text-gray-400" /></div>
  if (!weeklyLoad) return <p className="text-sm dark:text-white/30 text-gray-400 text-center py-8">No weekly data available.</p>

  const max = Math.max(...weeklyLoad.drivers.map(d => d.ride_count), 1)
  const avg = weeklyLoad.average

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p className="text-sm dark:text-white/50 text-gray-500">
          Week of {weeklyLoad.week_start} · Avg {avg} rides/driver
        </p>
        <div className="flex gap-3 text-xs">
          <span className="flex items-center gap-1 text-red-400"><span className="w-2 h-2 rounded-full bg-red-400" />Overloaded (&gt;{Math.ceil(avg * 1.5)})</span>
          <span className="flex items-center gap-1 text-amber-400"><span className="w-2 h-2 rounded-full bg-amber-400" />Under ({`<`}{Math.floor(avg * 0.5)})</span>
        </div>
      </div>

      <GlassCard>
        <div className="space-y-2">
          {weeklyLoad.drivers.map(d => {
            const pct = (d.ride_count / max) * 100
            const isOver = d.ride_count > avg * 1.5
            const isUnder = d.ride_count < avg * 0.5
            const barColor = isOver ? 'bg-red-500' : isUnder ? 'bg-amber-500' : 'bg-[#667eea]'
            return (
              <div key={d.person_id} className="flex items-center gap-3">
                <p className="text-sm dark:text-white/70 text-gray-600 w-36 truncate flex-shrink-0">{d.name}</p>
                <div className="flex-1 h-2 rounded-full dark:bg-white/5 bg-gray-100 overflow-hidden">
                  <motion.div initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.6 }}
                    className={`h-full rounded-full ${barColor}`} />
                </div>
                <p className={`text-sm font-semibold w-8 text-right flex-shrink-0 ${isOver ? 'text-red-400' : isUnder ? 'text-amber-400' : 'dark:text-white/70 text-gray-600'}`}>
                  {d.ride_count}
                </p>
                <p className={`text-xs w-12 text-right flex-shrink-0 ${d.vs_avg > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                  {d.vs_avg > 0 ? `+${d.vs_avg}` : d.vs_avg}
                </p>
              </div>
            )
          })}
          {weeklyLoad.drivers.length === 0 && (
            <p className="text-sm dark:text-white/40 text-gray-400 text-center py-4">No ride data for this week yet.</p>
          )}
        </div>
      </GlassCard>

      <div className="grid grid-cols-3 gap-3">
        <div className="px-4 py-3 rounded-xl dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 text-center">
          <p className="text-xl font-bold dark:text-white text-gray-900">{weeklyLoad.drivers.length}</p>
          <p className="text-xs dark:text-white/40 text-gray-400 mt-1">Active Drivers</p>
        </div>
        <div className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
          <p className="text-xl font-bold text-red-400">{weeklyLoad.drivers.filter(d => d.ride_count > avg * 1.5).length}</p>
          <p className="text-xs text-red-400/70 mt-1">Overloaded</p>
        </div>
        <div className="px-4 py-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-center">
          <p className="text-xl font-bold text-amber-400">{weeklyLoad.drivers.filter(d => d.ride_count < avg * 0.5 && d.ride_count > 0).length}</p>
          <p className="text-xs text-amber-400/70 mt-1">Under-used</p>
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function DispatchManagePage() {
  const [activeMode, setActiveMode] = useState('cover')
  const [date, setDate] = useState(todayStr())
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [reliability, setReliability] = useState<Reliability>({})
  const [promises, setPromises] = useState<Promise_[]>([])
  const [blackouts, setBlackouts] = useState<Blackout[]>([])
  const [weeklyLoad, setWeeklyLoad] = useState<WeeklyLoad | null>(null)
  const [loadingBase, setLoadingBase] = useState(true)
  const [loadingWeekly, setLoadingWeekly] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const fetchBase = useCallback(async () => {
    try {
      const [dispatchRes, reliabilityRes, promisesRes, blackoutsRes] = await Promise.all([
        api.get<{ drivers: Driver[] }>(`/dispatch/data?date=${date}`),
        api.get<Reliability>('/dispatch/manage/reliability').catch(() => ({})),
        api.get<Promise_[]>('/dispatch/manage/promises').catch(() => []),
        api.get<Blackout[]>('/dispatch/manage/blackouts').catch(() => []),
      ])
      setDrivers(dispatchRes.drivers || [])
      setReliability(reliabilityRes || {})
      setPromises(promisesRes || [])
      setBlackouts(blackoutsRes || [])
    } catch (e) { console.error(e) }
    finally { setLoadingBase(false) }
  }, [date])

  const fetchWeekly = useCallback(async () => {
    setLoadingWeekly(true)
    try {
      const res = await api.get<WeeklyLoad>('/dispatch/manage/weekly-load')
      setWeeklyLoad(res)
    } catch (e) { console.error(e) }
    finally { setLoadingWeekly(false) }
  }, [])

  useEffect(() => { fetchBase() }, [fetchBase])
  useEffect(() => { if (activeMode === 'load') fetchWeekly() }, [activeMode, fetchWeekly])

  async function refresh() {
    setRefreshing(true)
    await fetchBase()
    if (activeMode === 'load') await fetchWeekly()
    setRefreshing(false)
  }

  // Promise CRUD
  async function addPromise(p: { person_id: number; description: string; notes?: string }) {
    await api.post('/dispatch/manage/promises', p)
    const res = await api.get<Promise_[]>('/dispatch/manage/promises').catch(() => [])
    setPromises(res)
  }
  async function fulfillPromise(id: number) {
    await api.put(`/dispatch/manage/promises/${id}`, {})
    const res = await api.get<Promise_[]>('/dispatch/manage/promises').catch(() => [])
    setPromises(res)
  }
  async function deletePromise(id: number) {
    await api.delete(`/dispatch/manage/promises/${id}`)
    setPromises(prev => prev.filter(p => p.id !== id))
  }

  // Blackout CRUD
  async function addBlackout(b: Omit<Blackout, 'id' | 'driver_name' | 'created_at'>) {
    await api.post('/dispatch/manage/blackouts', b)
    const res = await api.get<Blackout[]>('/dispatch/manage/blackouts').catch(() => [])
    setBlackouts(res)
  }
  async function deleteBlackout(id: number) {
    await api.delete(`/dispatch/manage/blackouts/${id}`)
    setBlackouts(prev => prev.filter(b => b.id !== id))
  }

  const currentMode = MODES.find(m => m.id === activeMode)!

  if (loadingBase) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-3xl mx-auto py-6 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/dispatch"
          className="p-2 rounded-xl dark:bg-white/5 bg-gray-100 dark:hover:bg-white/10 hover:bg-gray-200 transition-all">
          <ArrowLeft className="w-4 h-4 dark:text-white/60 text-gray-500" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-bold dark:text-white text-gray-900">Dispatch Manage</h1>
          <p className="text-sm dark:text-white/40 text-gray-400">{drivers.length} drivers · {date}</p>
        </div>
        <input type="date" value={date} onChange={e => setDate(e.target.value)}
          className="px-3 py-1.5 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
        <button onClick={refresh} disabled={refreshing}
          className="p-2 rounded-xl dark:bg-white/5 bg-gray-100 dark:hover:bg-white/10 hover:bg-gray-200 transition-all cursor-pointer">
          <RefreshCw className={`w-4 h-4 dark:text-white/60 text-gray-500 ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Mode tabs — horizontal scroll */}
      <p className="text-xs dark:text-white/25 text-gray-400 -mb-1">← scroll for more modes →</p>
      <div className="flex gap-2 overflow-x-auto pb-2 -mx-1 px-1 scrollbar-hide snap-x">
        {MODES.map(m => {
          const Icon = m.icon
          const active = activeMode === m.id
          return (
            <button key={m.id} onClick={() => setActiveMode(m.id)}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium whitespace-nowrap transition-all cursor-pointer flex-shrink-0 snap-start
                ${active ? `${m.bg} ${m.color} border ${m.color.replace('text-', 'border-').replace('-400', '-500/40')}` : 'dark:bg-white/5 bg-gray-100 dark:text-white/50 text-gray-500 dark:hover:bg-white/8 hover:bg-gray-200'}`}>
              <Icon className="w-3.5 h-3.5" />
              {m.label}
            </button>
          )
        })}
      </div>

      {/* Mode icon + title */}
      <div className={`flex items-center gap-3 px-4 py-3 rounded-2xl border ${currentMode.bg} ${currentMode.color.replace('text-', 'border-').replace('-400', '-500/30')}`}>
        {(() => { const Icon = currentMode.icon; return <Icon className={`w-5 h-5 ${currentMode.color} flex-shrink-0`} /> })()}
        <div>
          <p className={`font-semibold text-sm ${currentMode.color}`}>{currentMode.label}</p>
        </div>
      </div>

      {/* Mode content */}
      <AnimatePresence mode="wait">
        <motion.div key={activeMode} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} transition={{ duration: 0.15 }}>
          {activeMode === 'cover'     && <CoverMode drivers={drivers} date={date} reliability={reliability} />}
          {activeMode === 'emergency' && <EmergencyMode drivers={drivers} date={date} reliability={reliability} />}
          {activeMode === 'reshuffle' && <ReshuffleMode drivers={drivers} date={date} reliability={reliability} />}
          {activeMode === 'swap'      && <SwapMode drivers={drivers} reliability={reliability} />}
          {activeMode === 'assign'    && <NewRideMode drivers={drivers} date={date} reliability={reliability} />}
          {activeMode === 'rampup'    && <RampupMode drivers={drivers} reliability={reliability} />}
          {activeMode === 'blackout'  && <BlackoutMode drivers={drivers} blackouts={blackouts} onAdd={addBlackout} onDelete={deleteBlackout} />}
          {activeMode === 'capacity'  && <CapacityMode drivers={drivers} reliability={reliability} />}
          {activeMode === 'promises'  && <PromisesMode drivers={drivers} promises={promises} onAdd={addPromise} onFulfill={fulfillPromise} onDelete={deletePromise} />}
          {activeMode === 'load'      && <LoadMode weeklyLoad={weeklyLoad} loading={loadingWeekly} />}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
