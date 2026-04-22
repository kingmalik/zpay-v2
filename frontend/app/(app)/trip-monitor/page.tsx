'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Activity, AlertTriangle, CheckCircle2, Clock, Phone,
  MessageSquare, ShieldAlert, Pause, RefreshCw, Layers,
} from 'lucide-react'
import { api } from '@/lib/api'
import PageHeader from '@/components/ui/PageHeader'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { cn } from '@/lib/utils'

// ─── Types ────────────────────────────────────────────────────────────

interface HealthResponse {
  scheduler_alive: boolean
  last_cycle_seconds_ago: number | null
  stale: boolean
  errors_in_last_cycle: number
  operating_hours: boolean
  interval_minutes: number
  operating_window_pdt: string
  current_time_pdt: string
  liveness_healthy: boolean
}

type Stage =
  | 'accept_sms' | 'accept_call' | 'accept_esc'
  | 'start_sms' | 'start_call' | 'start_esc'
  | 'overdue'

interface Contact {
  driver_name: string
  person_id: number
  trip_ref: string
  source: string
  trip_status: string
  pickup_time_pdt: string | null
  pickup_time_raw: string | null
  accept_sms_at: string | null
  accept_call_at: string | null
  accept_escalated_at: string | null
  accepted_at_pdt: string | null
  start_sms_at_pdt: string | null
  start_call_at_pdt: string | null
  start_escalated_at_pdt: string | null
  started_at_pdt: string | null
  overdue_alerted_at_pdt: string | null
  stages_fired: Stage[]
  concurrent_active: number
}

interface Totals {
  accept_sms: number
  accept_calls: number
  accept_escalations: number
  start_sms: number
  start_calls: number
  start_escalations: number
  overdue_alerts: number
  declines: number
  name_mismatches: number
  unknown_status_alerts: number
  start_suppressed_concurrent: number
}

interface LastCycle {
  ran_at: string | null
  trips_checked: number
  errors: string[]
  summary: Record<string, unknown>
}

interface TodayResponse {
  current_time_pdt: string
  today_pdt: string
  last_cycle: LastCycle
  totals_today: Totals
  contacts: Contact[]
}

// ─── Helpers ──────────────────────────────────────────────────────────

const REFRESH_MS = 30_000

function relTime(secondsAgo: number | null): string {
  if (secondsAgo == null) return 'never'
  if (secondsAgo < 60) return `${Math.round(secondsAgo)}s ago`
  if (secondsAgo < 3600) return `${Math.round(secondsAgo / 60)}m ago`
  return `${Math.round(secondsAgo / 3600)}h ago`
}

function healthState(h: HealthResponse | null): {
  label: string
  color: 'success' | 'warning' | 'danger' | 'info'
  pulse: boolean
} {
  if (!h) return { label: 'Loading', color: 'info', pulse: false }
  if (!h.scheduler_alive) return { label: 'Down', color: 'danger', pulse: true }
  if (!h.operating_hours) return { label: 'After hours', color: 'info', pulse: false }
  if (h.stale) return { label: 'Stale', color: 'warning', pulse: true }
  if (h.errors_in_last_cycle > 0) return { label: 'Cycle errors', color: 'warning', pulse: false }
  return { label: 'Healthy', color: 'success', pulse: true }
}

const STAGE_META: Record<Stage, { label: string; tone: 'sms' | 'call' | 'esc' | 'overdue'; icon: React.ReactNode }> = {
  accept_sms:  { label: 'Accept SMS',  tone: 'sms',     icon: <MessageSquare className="w-3 h-3" /> },
  accept_call: { label: 'Accept Call', tone: 'call',    icon: <Phone className="w-3 h-3" /> },
  accept_esc:  { label: 'Accept Esc',  tone: 'esc',     icon: <ShieldAlert className="w-3 h-3" /> },
  start_sms:   { label: 'Start SMS',   tone: 'sms',     icon: <MessageSquare className="w-3 h-3" /> },
  start_call:  { label: 'Start Call',  tone: 'call',    icon: <Phone className="w-3 h-3" /> },
  start_esc:   { label: 'Start Esc',   tone: 'esc',     icon: <ShieldAlert className="w-3 h-3" /> },
  overdue:     { label: 'Overdue',     tone: 'overdue', icon: <Clock className="w-3 h-3" /> },
}

const TONE_CLASS: Record<'sms' | 'call' | 'esc' | 'overdue', string> = {
  sms:     'bg-blue-500/10 text-blue-400 border border-blue-500/25',
  call:    'bg-indigo-500/10 text-indigo-400 border border-indigo-500/25',
  esc:     'bg-red-500/10 text-red-400 border border-red-500/25',
  overdue: 'bg-amber-500/10 text-amber-400 border border-amber-500/25',
}

function StageChip({ stage }: { stage: Stage }) {
  const meta = STAGE_META[stage]
  return (
    <span className={cn(
      'inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-semibold',
      TONE_CLASS[meta.tone],
    )}>
      {meta.icon}
      {meta.label}
    </span>
  )
}

function NumberTile({
  label, value, accent, hint,
}: { label: string; value: number; accent?: 'danger' | 'warning' | 'success' | 'info' | 'muted'; hint?: string }) {
  const accentRing: Record<NonNullable<typeof accent>, string> = {
    danger:  'ring-red-500/30',
    warning: 'ring-amber-500/30',
    success: 'ring-emerald-500/30',
    info:    'ring-blue-500/30',
    muted:   'ring-white/[0.06]',
  }
  const accentText: Record<NonNullable<typeof accent>, string> = {
    danger:  'text-red-400',
    warning: 'text-amber-400',
    success: 'text-emerald-400',
    info:    'text-blue-400',
    muted:   'dark:text-white/80 text-gray-700',
  }
  const a = accent ?? 'muted'
  return (
    <div className={cn(
      'rounded-xl px-4 py-3 ring-1',
      'dark:bg-white/[0.03] bg-white border dark:border-white/[0.06] border-gray-200',
      accentRing[a],
    )}>
      <div className="text-[10px] uppercase tracking-wider font-semibold dark:text-white/40 text-gray-500">{label}</div>
      <div className={cn('text-2xl font-bold tabular-nums leading-tight', accentText[a])}>{value}</div>
      {hint && <div className="text-[10px] dark:text-white/30 text-gray-400 mt-0.5">{hint}</div>}
    </div>
  )
}

function pickEarliestStageTime(c: Contact): string {
  // For the "Time PDT" column — earliest contact attempt today.
  const candidates = [
    c.accept_sms_at, c.accept_call_at, c.accept_escalated_at,
    c.start_sms_at_pdt, c.start_call_at_pdt, c.start_escalated_at_pdt,
    c.overdue_alerted_at_pdt,
  ].filter((v): v is string => Boolean(v))
  if (candidates.length === 0) return '—'
  // All are HH:MM strings — lexical sort is correct for same-day times.
  return candidates.sort()[0]
}

function statusTone(status: string): 'success' | 'warning' | 'danger' | 'default' {
  const s = status.toLowerCase()
  if (!s) return 'default'
  if (s.includes('complet') || s.includes('finish')) return 'success'
  if (s.includes('cancel') || s.includes('declin') || s.includes('noshow')) return 'danger'
  if (s.includes('progress') || s.includes('tostop') || s.includes('topickup') || s.includes('atstop') || s.includes('active') || s === 'started') return 'success'
  if (s.includes('accept') || s === 'scheduled') return 'warning'
  return 'default'
}

// ─── Page ─────────────────────────────────────────────────────────────

export default function TripMonitorPage() {
  const [data, setData] = useState<TodayResponse | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshedAt, setRefreshedAt] = useState<number>(Date.now())
  const [now, setNow] = useState<number>(Date.now())
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const tickerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function refresh() {
    try {
      const [t, h] = await Promise.all([
        api.get<TodayResponse>('/trip-monitor/today'),
        api.get<HealthResponse>('/trip-monitor/health'),
      ])
      setData(t)
      setHealth(h)
      setError(null)
      setRefreshedAt(Date.now())
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to load monitor data'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    intervalRef.current = setInterval(refresh, REFRESH_MS)
    tickerRef.current = setInterval(() => setNow(Date.now()), 1000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
      if (tickerRef.current) clearInterval(tickerRef.current)
    }
  }, [])

  const updatedSecondsAgo = Math.max(0, Math.round((now - refreshedAt) / 1000))

  const contactsSorted = useMemo(() => {
    if (!data) return []
    // Sort by pickup time (lexical works because pickup_time_pdt has consistent
    // YYYY-MM-DD HH:MM prefix; falls back by earliest-stage time).
    return [...data.contacts].sort((a, b) => {
      const ka = a.pickup_time_pdt ?? pickEarliestStageTime(a)
      const kb = b.pickup_time_pdt ?? pickEarliestStageTime(b)
      return ka.localeCompare(kb)
    })
  }, [data])

  const totals = data?.totals_today
  const lastCycle = data?.last_cycle
  const h = healthState(health)

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">
      <PageHeader
        title="Trip Monitor — Today"
        subtitle="Live view of dispatcher caller — who got contacted, what fired, and why"
        icon={<Activity className="w-5 h-5" />}
        actions={
          <button
            onClick={refresh}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm font-medium text-white transition-all cursor-pointer hover:opacity-90"
            style={{ background: '#667eea' }}
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
        }
      />

      {error && (
        <div className="px-4 py-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-sm text-red-400">
          <span className="font-semibold">Error:</span> {error}
        </div>
      )}

      {/* ── Status strip ───────────────────────────────────────── */}
      <div className="rounded-2xl px-4 py-3 dark:bg-white/[0.03] bg-white border dark:border-white/[0.06] border-gray-200 flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="flex items-center gap-2">
          {h.pulse && <span className={cn(
            'w-2 h-2 rounded-full animate-pulse',
            h.color === 'success' && 'bg-emerald-400',
            h.color === 'warning' && 'bg-amber-400',
            h.color === 'danger' && 'bg-red-400',
            h.color === 'info' && 'bg-blue-400',
          )} />}
          <span className={cn(
            'px-2.5 py-0.5 rounded-md text-xs font-bold uppercase tracking-wider',
            h.color === 'success' && 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30',
            h.color === 'warning' && 'bg-amber-500/15 text-amber-400 border border-amber-500/30',
            h.color === 'danger' && 'bg-red-500/15 text-red-400 border border-red-500/30',
            h.color === 'info' && 'bg-blue-500/15 text-blue-400 border border-blue-500/30',
          )}>
            {h.label}
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-xs dark:text-white/60 text-gray-600">
          <Clock className="w-3.5 h-3.5 dark:text-white/40 text-gray-400" />
          Last cycle:&nbsp;
          <span className="font-semibold dark:text-white/80 text-gray-700">
            {relTime(health?.last_cycle_seconds_ago ?? null)}
          </span>
        </div>

        <div className="text-xs dark:text-white/60 text-gray-600">
          Window: <span className="font-semibold dark:text-white/80 text-gray-700">{health?.operating_window_pdt ?? '—'}</span>
        </div>

        <div className="text-xs dark:text-white/60 text-gray-600">
          Interval: <span className="font-semibold dark:text-white/80 text-gray-700">{health?.interval_minutes ?? '—'}m</span>
        </div>

        {!health?.operating_hours && (
          <span className="inline-flex items-center gap-1 text-xs text-blue-400">
            <Pause className="w-3 h-3" /> Outside operating hours
          </span>
        )}

        {(health?.errors_in_last_cycle ?? 0) > 0 && (
          <span className="inline-flex items-center gap-1 text-xs text-amber-400">
            <AlertTriangle className="w-3 h-3" /> {health?.errors_in_last_cycle} error{health?.errors_in_last_cycle === 1 ? '' : 's'} last cycle
          </span>
        )}

        <div className="ml-auto text-[11px] dark:text-white/40 text-gray-400 tabular-nums">
          updated {updatedSecondsAgo}s ago
        </div>
      </div>

      {/* ── Cycle errors detail ─────────────────────────────────── */}
      {lastCycle?.errors && lastCycle.errors.length > 0 && (
        <div className="rounded-xl px-4 py-3 bg-red-500/5 border border-red-500/20 space-y-1">
          <div className="text-xs font-semibold text-red-400 uppercase tracking-wider">Last cycle errors</div>
          {lastCycle.errors.map((e, i) => (
            <div key={i} className="text-xs text-red-300/90 font-mono">{e}</div>
          ))}
        </div>
      )}

      {/* ── Totals strip ────────────────────────────────────────── */}
      {totals && (
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider dark:text-white/40 text-gray-500 mb-2 flex items-center gap-2">
            <Layers className="w-3.5 h-3.5" />
            Today&apos;s scoreboard
            {lastCycle?.trips_checked != null && (
              <span className="dark:text-white/30 text-gray-400 normal-case tracking-normal font-normal">
                · last cycle checked {lastCycle.trips_checked} trip{lastCycle.trips_checked === 1 ? '' : 's'}
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-2.5">
            <NumberTile label="Accept SMS" value={totals.accept_sms} accent="info" />
            <NumberTile label="Accept Calls" value={totals.accept_calls} accent="info" />
            <NumberTile label="Start SMS" value={totals.start_sms} accent="info" />
            <NumberTile label="Start Calls" value={totals.start_calls} accent="info" />
            <NumberTile
              label="Escalations"
              value={totals.accept_escalations + totals.start_escalations}
              accent={(totals.accept_escalations + totals.start_escalations) > 0 ? 'danger' : 'muted'}
            />
            <NumberTile
              label="Overdue"
              value={totals.overdue_alerts}
              accent={totals.overdue_alerts > 0 ? 'warning' : 'muted'}
            />
            <NumberTile
              label="Suppressed"
              value={totals.start_suppressed_concurrent}
              accent="muted"
              hint="busy on another trip"
            />
          </div>
        </div>
      )}

      {/* ── Contacts table ──────────────────────────────────────── */}
      <div>
        <div className="text-xs font-semibold uppercase tracking-wider dark:text-white/40 text-gray-500 mb-2">
          Contacts today ({contactsSorted.length})
        </div>

        {contactsSorted.length === 0 ? (
          <div className="rounded-xl px-6 py-12 text-center dark:bg-white/[0.02] bg-white border dark:border-white/[0.06] border-gray-200">
            <CheckCircle2 className="w-8 h-8 mx-auto mb-2 text-emerald-400/70" />
            <div className="text-sm font-medium dark:text-white/70 text-gray-700">Quiet morning — no contacts today</div>
            <div className="text-xs dark:text-white/40 text-gray-500 mt-1">
              The dispatcher caller hasn&apos;t needed to reach anyone yet.
            </div>
          </div>
        ) : (
          <div className="rounded-xl overflow-hidden dark:bg-white/[0.03] bg-white border dark:border-white/[0.06] border-gray-200">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b dark:border-white/[0.06] border-gray-100 dark:bg-white/[0.02] bg-gray-50/60">
                    {[
                      'Time PDT', 'Driver', 'Trip', 'Source', 'Pickup PDT', 'Stages Fired', 'Status', 'Concurrent',
                    ].map(h => (
                      <th key={h} className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-wider dark:text-white/50 text-gray-500 whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <AnimatePresence initial={false}>
                    {contactsSorted.map((c, i) => {
                      const src = c.source.toLowerCase()
                      const isFa = src.includes('first') || src === 'fa'
                      const earliest = pickEarliestStageTime(c)
                      const tone = statusTone(c.trip_status)
                      const stripe = i % 2 === 1 ? 'dark:bg-white/[0.015] bg-gray-50/40' : ''
                      return (
                        <motion.tr
                          key={`${c.source}-${c.trip_ref}`}
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0 }}
                          transition={{ duration: 0.18, delay: Math.min(i * 0.015, 0.4) }}
                          className={cn(
                            'border-b last:border-0 dark:border-white/[0.04] border-gray-100 dark:hover:bg-white/[0.05] hover:bg-gray-50 transition-colors',
                            stripe,
                          )}
                        >
                          <td className="px-3 py-2.5 font-mono dark:text-white/80 text-gray-700 tabular-nums whitespace-nowrap">
                            {earliest}
                          </td>
                          <td className="px-3 py-2.5 font-medium dark:text-white/90 text-gray-800 whitespace-nowrap">
                            {c.driver_name}
                          </td>
                          <td className="px-3 py-2.5 dark:text-white/50 text-gray-500 font-mono whitespace-nowrap">
                            {c.trip_ref}
                          </td>
                          <td className="px-3 py-2.5">
                            <Badge variant={isFa ? 'fa' : 'ed'}>
                              {isFa ? 'FA' : 'ED'}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 dark:text-white/60 text-gray-600 whitespace-nowrap">
                            {c.pickup_time_pdt ?? c.pickup_time_raw ?? '—'}
                          </td>
                          <td className="px-3 py-2.5">
                            <div className="flex flex-wrap gap-1">
                              {c.stages_fired.length === 0
                                ? <span className="dark:text-white/30 text-gray-400">—</span>
                                : c.stages_fired.map(s => <StageChip key={s} stage={s} />)}
                            </div>
                          </td>
                          <td className="px-3 py-2.5">
                            <Badge variant={tone === 'default' ? 'default' : tone}>
                              {c.trip_status || 'unknown'}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5">
                            {c.concurrent_active > 0 ? (
                              <Badge variant="warning">{c.concurrent_active}</Badge>
                            ) : (
                              <span className="dark:text-white/30 text-gray-400">—</span>
                            )}
                          </td>
                        </motion.tr>
                      )
                    })}
                  </AnimatePresence>
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
