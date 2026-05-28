'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Activity, AlertTriangle, ChevronDown, ChevronUp,
  Clock, Info, Pause, Radio, RefreshCw, VolumeX, Zap,
  CheckCircle2, MessageSquare, Phone, ShieldAlert,
} from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Badge from '@/components/ui/Badge'
import TripHeatmap from './TripHeatmap'
import EventLogTimeline from './EventLogTimeline'

// ── Types ─────────────────────────────────────────────────────────────────────

interface LiveTrip {
  notif_id: number
  driver: string
  person_id: number
  source: string
  trip_ref: string
  pickup_time: string
  minutes_until_pickup: number | null
  state: 'unaccepted' | 'accepted_not_started'
  trip_status: string
  is_urgent: boolean
  accepted_at: string | null
  snoozed_until: string | null
  dispatch_severity: string
  escalated_at: string | null
}

interface AlertFeedItem {
  event_id: number
  created_at: string | null
  driver: string
  person_id: number
  trip_ref: string
  source: string
  event_type: string
  channel: 'sms' | 'call' | 'discord' | 'system'
  status: 'sent' | 'delivered' | 'failed' | 'operator'
  payload_summary: Record<string, unknown>
}

interface DriverConcurrency {
  person_id: number
  driver: string
  active_trips: number
  flagged: boolean
}

interface PartnerStatus {
  status: 'green' | 'yellow' | 'red' | 'unknown'
  last_contact_at: string | null
  consecutive_failures: number
}

interface SchedulerLiveness {
  last_cycle_at: string | null
  next_cycle_in_seconds: number | null
  is_stale: boolean
  enabled: boolean
}

interface DashboardData {
  live_trips: LiveTrip[]
  alerts_feed: AlertFeedItem[]
  driver_concurrency: DriverConcurrency[]
  partner_health: { fa: PartnerStatus; ed: PartnerStatus }
  scheduler_liveness: SchedulerLiveness
  monitor_paused: boolean
  active_trip_count: number
  generated_at: string
}

interface TripExplain {
  notif_id: number
  driver: string
  trip_ref: string
  source: string
  pickup_time: string
  trip_status: string
  bucket: string
  reason: string
  last_event: {
    event_type: string
    created_at: string | null
    payload: Record<string, unknown>
  } | null
  timeline: Record<string, string | null>
}

interface NonTapperOffender {
  person_id: number
  driver: string
  non_tap_count: number
}

interface NonTappersData {
  week: string
  offenders: NonTapperOffender[]
}

// ── Constants ─────────────────────────────────────────────────────────────────

const REFRESH_MS = 30_000

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(ts: string | null | undefined): string {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
  } catch {
    return ts
  }
}

function StatusDot({ status }: { status: 'green' | 'yellow' | 'red' | 'unknown' }) {
  const cls: Record<typeof status, string> = {
    green:   'bg-emerald-400',
    yellow:  'bg-amber-400 animate-pulse',
    red:     'bg-red-400 animate-pulse',
    unknown: 'bg-gray-500',
  }
  return <span className={cn('inline-block w-2 h-2 rounded-full shrink-0', cls[status])} />
}

function channelIcon(channel: AlertFeedItem['channel']) {
  if (channel === 'sms') return <MessageSquare className="w-3 h-3" />
  if (channel === 'call') return <Phone className="w-3 h-3" />
  if (channel === 'discord') return <ShieldAlert className="w-3 h-3" />
  return <Activity className="w-3 h-3" />
}

function alertStatusCls(s: AlertFeedItem['status']): string {
  if (s === 'delivered') return 'text-emerald-400'
  if (s === 'failed') return 'text-red-400'
  if (s === 'operator') return 'text-blue-400'
  return 'text-white/40'
}

function SectionLabel({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <span className="text-white/25">{icon}</span>
      <span className="text-[11px] font-bold uppercase tracking-widest text-white/35">{label}</span>
    </div>
  )
}

// ── Trip explain modal ────────────────────────────────────────────────────────

function TripExplainModal({ notifId, onClose }: { notifId: number; onClose: () => void }) {
  const [data, setData] = useState<TripExplain | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<TripExplain>(`/ops-dashboard/trip-explain/${notifId}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [notifId])

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.96, y: 8 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.96, opacity: 0 }}
        transition={{ type: 'spring', stiffness: 380, damping: 30 }}
        className="w-full max-w-md rounded-2xl bg-[#111318] border border-white/[0.1] p-5 shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white/90">Trip State</h3>
          <button
            onClick={onClose}
            className="text-white/35 hover:text-white/70 transition-colors text-lg leading-none"
          >
            ✕
          </button>
        </div>

        {loading && <div className="py-4"><LoadingSpinner /></div>}
        {!loading && !data && (
          <p className="text-xs text-red-400">Could not load trip details.</p>
        )}
        {!loading && data && (
          <div className="space-y-3 text-xs">
            <Row label="Driver" value={<span className="font-medium text-white/90">{data.driver}</span>} />
            <Row label="Trip ref" value={<span className="font-mono text-white/65">{data.trip_ref}</span>} />
            <Row label="Bucket" value={<span className="text-blue-400 font-semibold">{data.bucket}</span>} />
            <Row label="Status" value={<span className="text-white/60">{data.trip_status || '—'}</span>} />
            <div className="bg-white/[0.04] rounded-lg p-3 border border-white/[0.07]">
              <p className="text-white/75 leading-relaxed">{data.reason}</p>
            </div>
            {data.last_event && (
              <div>
                <p className="text-white/35 mb-1">Last event</p>
                <p className="font-semibold text-white/80">{data.last_event.event_type}</p>
                <p className="text-white/35">{fmt(data.last_event.created_at)}</p>
              </div>
            )}
            <div>
              <p className="text-white/35 mb-2">Timeline</p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                {Object.entries(data.timeline).map(([k, v]) =>
                  v ? (
                    <div key={k} className="flex justify-between gap-2">
                      <span className="text-white/35 truncate capitalize">{k.replace(/_at$/, '').replace(/_/g, ' ')}</span>
                      <span className="text-white/65 tabular-nums shrink-0">{fmt(v)}</span>
                    </div>
                  ) : null
                )}
              </div>
            </div>
          </div>
        )}
      </motion.div>
    </motion.div>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-2 items-start">
      <span className="text-white/35 w-16 shrink-0">{label}</span>
      <span>{value}</span>
    </div>
  )
}

// ── Live trips panel ──────────────────────────────────────────────────────────

function LiveTripsPanel({ trips }: { trips: LiveTrip[] }) {
  const [explainId, setExplainId] = useState<number | null>(null)

  if (trips.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-8 rounded-xl bg-white/[0.02] border border-white/[0.06]">
        <CheckCircle2 className="w-6 h-6 text-emerald-400/50" />
        <p className="text-xs text-white/35">No active trips right now</p>
      </div>
    )
  }

  return (
    <>
      <div className="rounded-xl overflow-hidden border border-white/[0.07] bg-white/[0.02]">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-white/[0.07] bg-white/[0.025]">
                {['Driver', 'Route', 'Pickup', 'Until', 'State', 'Status', ''].map(col => (
                  <th key={col} className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-white/25 whitespace-nowrap">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <AnimatePresence initial={false}>
                {trips.map((trip, i) => {
                  const isFa = trip.source.toLowerCase().includes('first')
                  const rowCls = trip.is_urgent
                    ? 'border-l-2 border-red-500 bg-red-500/[0.06]'
                    : trip.state === 'accepted_not_started'
                      ? 'border-l-2 border-blue-500/40'
                      : 'border-l-2 border-transparent'

                  return (
                    <motion.tr
                      key={trip.notif_id}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      transition={{ delay: i * 0.015 }}
                      className={cn(
                        'border-b last:border-0 border-white/[0.05] hover:bg-white/[0.04] transition-colors',
                        rowCls,
                      )}
                    >
                      <td className="px-3 py-2 font-medium text-white/85 whitespace-nowrap">{trip.driver}</td>
                      <td className="px-3 py-2">
                        <span className="flex items-center gap-1.5">
                          <Badge variant={isFa ? 'fa' : 'ed'}>{trip.source}</Badge>
                          <span className="text-white/35 font-mono text-[11px]">{trip.trip_ref}</span>
                        </span>
                      </td>
                      <td className="px-3 py-2 text-white/55 tabular-nums whitespace-nowrap">{trip.pickup_time || '—'}</td>
                      <td className="px-3 py-2 tabular-nums whitespace-nowrap">
                        {trip.minutes_until_pickup !== null ? (
                          <span className={cn(
                            'font-semibold',
                            trip.minutes_until_pickup < 0 ? 'text-red-400' :
                            trip.minutes_until_pickup < 15 ? 'text-amber-400' :
                            'text-white/45',
                          )}>
                            {trip.minutes_until_pickup < 0
                              ? `${Math.abs(trip.minutes_until_pickup)}m late`
                              : `${trip.minutes_until_pickup}m`}
                          </span>
                        ) : '—'}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <span className={cn(
                          'px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider',
                          trip.state === 'unaccepted'
                            ? 'bg-red-500/15 text-red-400 border border-red-500/20'
                            : 'bg-blue-500/15 text-blue-400 border border-blue-500/20',
                        )}>
                          {trip.state === 'unaccepted' ? 'unaccepted' : 'not started'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-white/35 whitespace-nowrap">{trip.trip_status || '—'}</td>
                      <td className="px-3 py-2">
                        <button
                          onClick={() => setExplainId(trip.notif_id)}
                          className="p-1 rounded hover:bg-white/10 transition-colors text-white/25 hover:text-white/65"
                          title="Explain state"
                        >
                          <Info className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </motion.tr>
                  )
                })}
              </AnimatePresence>
            </tbody>
          </table>
        </div>
      </div>

      <AnimatePresence>
        {explainId !== null && (
          <TripExplainModal notifId={explainId} onClose={() => setExplainId(null)} />
        )}
      </AnimatePresence>
    </>
  )
}

// ── Alerts feed ───────────────────────────────────────────────────────────────

function AlertsFeed({ feed }: { feed: AlertFeedItem[] }) {
  if (feed.length === 0) {
    return (
      <div className="flex items-center justify-center py-5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
        <p className="text-xs text-white/30">No alerts in the last 60 minutes</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] overflow-hidden" style={{ maxHeight: 300 }}>
      <div className="overflow-y-auto" style={{ maxHeight: 300 }}>
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10" style={{ background: '#111318' }}>
            <tr className="border-b border-white/[0.07]">
              {['Time', 'Driver', 'Event', 'Channel', 'Status'].map(col => (
                <th key={col} className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-widest text-white/25">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {feed.map((ev, i) => (
              <tr
                key={ev.event_id}
                className={cn('border-b last:border-0 border-white/[0.04]', i % 2 === 1 ? 'bg-white/[0.015]' : '')}
              >
                <td className="px-3 py-1.5 tabular-nums text-white/35 whitespace-nowrap">{fmt(ev.created_at)}</td>
                <td className="px-3 py-1.5 font-medium text-white/72 whitespace-nowrap">{ev.driver}</td>
                <td className="px-3 py-1.5 text-white/45 font-mono text-[11px]">{ev.event_type}</td>
                <td className="px-3 py-1.5">
                  <span className="flex items-center gap-1 text-white/45">
                    {channelIcon(ev.channel)}
                    {ev.channel}
                  </span>
                </td>
                <td className={cn('px-3 py-1.5 font-semibold', alertStatusCls(ev.status))}>
                  {ev.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Concurrency panel ─────────────────────────────────────────────────────────

function ConcurrencyPanel({ concurrency }: { concurrency: DriverConcurrency[] }) {
  return (
    <section>
      <SectionLabel icon={<AlertTriangle className="w-3.5 h-3.5" />} label="Driver Concurrency" />
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/[0.07] bg-white/[0.025]">
              {['Driver', 'Active Trips', 'Flag'].map(col => (
                <th key={col} className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-widest text-white/25">{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {concurrency.map(c => (
              <tr key={c.person_id} className="border-b last:border-0 border-white/[0.04]">
                <td className="px-3 py-2 font-medium text-white/78">{c.driver}</td>
                <td className="px-3 py-2 tabular-nums font-bold text-white/65">{c.active_trips}</td>
                <td className="px-3 py-2">
                  {c.flagged
                    ? <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-500/15 text-red-400 border border-red-500/20">OVERLAP</span>
                    : <span className="text-white/20">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

// ── Chronic non-tappers ───────────────────────────────────────────────────────

function ChronicNonTappers() {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<NonTappersData | null>(null)
  const [loading, setLoading] = useState(false)
  const [mutingId, setMutingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get<NonTappersData>('/ops-dashboard/chronic-non-tappers')
      setData(res)
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open && !data) load()
  }, [open, data, load])

  const mute = async (personId: number) => {
    setMutingId(personId)
    try {
      await api.post(`/dispatch/persons/${personId}/mute`, {
        minutes: 60,
        reason: 'chronic non-tapper — training target',
      })
    } finally {
      setMutingId(null)
    }
  }

  const offenders = data?.offenders ?? []

  return (
    <section>
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-2 w-full text-left group"
      >
        <SectionLabel
          icon={<Clock className="w-3.5 h-3.5" />}
          label={`This week's training targets${offenders.length > 0 ? ` (${offenders.length})` : ''}`}
        />
        <span className="text-white/20 ml-auto group-hover:text-white/50 transition-colors">
          {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
          >
            {loading && <div className="py-4"><LoadingSpinner /></div>}
            {!loading && offenders.length === 0 && (
              <div className="flex items-center justify-center py-5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
                <p className="text-xs text-white/30">No chronic non-tappers this week</p>
              </div>
            )}
            {!loading && offenders.length > 0 && (
              <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/[0.07] bg-white/[0.025]">
                      {['Driver', 'Non-taps this week', 'Action'].map(col => (
                        <th key={col} className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-widest text-white/25">{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {offenders.map(o => (
                      <tr key={o.person_id} className="border-b last:border-0 border-white/[0.04]">
                        <td className="px-3 py-2 font-medium text-white/78">{o.driver}</td>
                        <td className="px-3 py-2 tabular-nums font-bold text-amber-400">{o.non_tap_count}</td>
                        <td className="px-3 py-2">
                          <button
                            onClick={() => mute(o.person_id)}
                            disabled={mutingId === o.person_id}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold bg-white/[0.05] text-white/55 hover:bg-white/10 hover:text-white/85 transition-all disabled:opacity-50 cursor-pointer"
                          >
                            <VolumeX className="w-3 h-3" />
                            Mute 60m
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  )
}

// ── Status strip ──────────────────────────────────────────────────────────────

function StatusStrip({
  data,
  lastRefreshedAt,
}: {
  data: DashboardData
  lastRefreshedAt: number
}) {
  const { partner_health: ph, scheduler_liveness: sl } = data
  const secsAgo = Math.max(0, Math.round((Date.now() - lastRefreshedAt) / 1000))

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5 rounded-xl border text-xs"
      style={{ background: 'rgba(255,255,255,0.025)', borderColor: 'rgba(255,255,255,0.07)' }}
    >
      <span className="flex items-center gap-1.5">
        <StatusDot status={ph.fa.status} />
        <span className="font-semibold text-white/75">FA</span>
        <span className={cn(
          'uppercase tracking-wide text-[10px]',
          ph.fa.status === 'green' ? 'text-emerald-400' :
          ph.fa.status === 'red' ? 'text-red-400' :
          ph.fa.status === 'yellow' ? 'text-amber-400' :
          'text-white/35',
        )}>{ph.fa.status}</span>
      </span>

      <span className="flex items-center gap-1.5">
        <StatusDot status={ph.ed.status} />
        <span className="font-semibold text-white/75">ED</span>
        <span className={cn(
          'uppercase tracking-wide text-[10px]',
          ph.ed.status === 'green' ? 'text-emerald-400' :
          ph.ed.status === 'red' ? 'text-red-400' :
          ph.ed.status === 'yellow' ? 'text-amber-400' :
          'text-white/35',
        )}>{ph.ed.status}</span>
      </span>

      <span className="flex items-center gap-1.5">
        {sl.is_stale ? (
          <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
        ) : sl.enabled ? (
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse shrink-0" />
        ) : (
          <span className="w-2 h-2 rounded-full bg-gray-500 shrink-0" />
        )}
        <span className="font-semibold text-white/75">Scheduler</span>
        <span className={cn(
          'text-[10px]',
          sl.is_stale ? 'text-amber-400' : sl.enabled ? 'text-emerald-400' : 'text-gray-400',
        )}>
          {sl.is_stale ? 'stale' : sl.enabled ? 'ok' : 'stopped'}
        </span>
        {sl.last_cycle_at && (
          <span className="text-white/25">· last {fmt(sl.last_cycle_at)}</span>
        )}
      </span>

      <span className="flex items-center gap-1.5 text-white/50">
        <Radio className="w-3 h-3 text-white/25" />
        <span className="font-semibold text-white/75">{data.active_trip_count}</span>
        <span className="text-white/35">active</span>
      </span>

      <span className="ml-auto text-white/25 tabular-nums text-[11px]">refreshed {secsAgo}s ago</span>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function LiveOpsPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastRefreshedAt, setLastRefreshedAt] = useState(Date.now())
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchDashboard = useCallback(async () => {
    try {
      const d = await api.get<DashboardData>('/ops-dashboard/dashboard')
      setData(d)
      setError(null)
      setLastRefreshedAt(Date.now())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load ops dashboard')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDashboard()
    timerRef.current = setInterval(fetchDashboard, REFRESH_MS)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchDashboard])

  const runAction = async (key: string, endpoint: string, body?: unknown) => {
    setActionBusy(key)
    try {
      await api.post(endpoint, body)
      await fetchDashboard()
    } finally {
      setActionBusy(null)
    }
  }

  if (loading) return <LoadingSpinner fullPage />

  if (error && !data) {
    return (
      <div className="max-w-3xl mx-auto py-12 text-center">
        <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-red-400" />
        <p className="text-sm text-red-400 font-medium mb-4">{error}</p>
        <button
          onClick={fetchDashboard}
          className="px-4 py-2 rounded-xl bg-white/[0.06] text-white/65 text-sm hover:bg-white/10 transition-all cursor-pointer"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="min-h-screen" style={{ background: '#0d0d0d', color: '#e2e2e2' }}>
      <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">

        {/* ── Header ── */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2.5 flex-1 min-w-0">
            <div
              className="p-2 rounded-xl border"
              style={{ background: 'rgba(102,126,234,0.12)', borderColor: 'rgba(102,126,234,0.25)' }}
            >
              <Radio className="w-4 h-4" style={{ color: '#667eea' }} />
            </div>
            <div>
              <h1 className="text-xl font-bold text-white/95 leading-tight">Live Ops</h1>
              <p className="text-[11px] text-white/30 mt-0.5">
                {fmt(data.generated_at)}
                <span className="mx-1.5 text-white/15">·</span>
                auto-refresh 30s
              </p>
            </div>
          </div>

          {/* Quick actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={fetchDashboard}
              title="Refresh"
              className="p-2 rounded-xl bg-white/[0.04] border border-white/[0.07] text-white/40 hover:text-white/75 hover:bg-white/[0.08] transition-all cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>

            <button
              onClick={() => runAction('pause', '/ops-dashboard/pause-monitor')}
              disabled={actionBusy === 'pause'}
              title="Pause monitor flag"
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-pointer disabled:opacity-50',
                data.monitor_paused
                  ? 'bg-amber-500/15 border-amber-500/25 text-amber-400'
                  : 'bg-white/[0.04] border-white/[0.07] text-white/55 hover:bg-white/[0.08] hover:text-white/80',
              )}
            >
              <Pause className="w-3 h-3" />
              {data.monitor_paused ? 'Paused' : 'Pause Monitor'}
            </button>

            <button
              onClick={() => runAction('run', '/ops-dashboard/run-cycle-now')}
              disabled={actionBusy === 'run'}
              title="Trigger an immediate dispatch cycle"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-white/[0.04] border border-white/[0.07] text-white/55 hover:bg-white/[0.08] hover:text-white/80 transition-all cursor-pointer disabled:opacity-50"
            >
              <Zap className="w-3 h-3" />
              Run Now
            </button>

            <button
              onClick={() => runAction('mute', '/ops-dashboard/mute-all')}
              disabled={actionBusy === 'mute'}
              title="Mute all active drivers for 30 min"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-white/[0.04] border border-white/[0.07] text-white/55 hover:bg-white/[0.08] hover:text-white/80 transition-all cursor-pointer disabled:opacity-50"
            >
              <VolumeX className="w-3 h-3" />
              Mute All 30m
            </button>
          </div>
        </div>

        {/* ── Status strip ── */}
        <StatusStrip data={data} lastRefreshedAt={lastRefreshedAt} />

        {/* ── Alert banners ── */}
        {data.scheduler_liveness.is_stale && (
          <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-400">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            <span className="font-semibold">Scheduler stale</span>
            <span>— hasn&apos;t run in over 15 min. Check Railway logs.</span>
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-400">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            {error}
          </div>
        )}

        {/* ── Live trips ── */}
        <section>
          <SectionLabel
            icon={<Activity className="w-3.5 h-3.5" />}
            label={`Live Trips (${data.live_trips.length})`}
          />
          <LiveTripsPanel trips={data.live_trips} />
        </section>

        {/* ── Alerts feed ── */}
        <section>
          <SectionLabel
            icon={<MessageSquare className="w-3.5 h-3.5" />}
            label={`Alerts — last 60 min (${data.alerts_feed.length})`}
          />
          <AlertsFeed feed={data.alerts_feed} />
        </section>

        {/* ── Driver concurrency (only when present) ── */}
        {data.driver_concurrency.length > 0 && (
          <ConcurrencyPanel concurrency={data.driver_concurrency} />
        )}

        {/* ── Event timeline (replaces Discord paper trail) ── */}
        <section>
          <SectionLabel
            icon={<MessageSquare className="w-3.5 h-3.5" />}
            label="Event Timeline"
          />
          <EventLogTimeline />
        </section>

        {/* ── Trip heatmap ── */}
        <section>
          <SectionLabel
            icon={<Activity className="w-3.5 h-3.5" />}
            label="Trip Volume — 7 days × 24 hours"
          />
          <TripHeatmap />
        </section>

        {/* ── Chronic non-tappers (collapsible) ── */}
        <ChronicNonTappers />

      </div>
    </div>
  )
}
