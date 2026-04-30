'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import Link from 'next/link'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Car,
  CheckCircle2,
  Circle,
  Clock,
  DollarSign,
  RefreshCw,
  TrendingUp,
  Users,
  XCircle,
  Zap,
} from 'lucide-react'
import { api } from '@/lib/api'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

interface TripBucket {
  total: number
  live: number
  completed: number
  canceled: number
  escalations: number
}

interface HealthCheck {
  name: string
  status: 'green' | 'yellow' | 'red' | 'unknown'
  last_checked_at: string | null
  consecutive_failures: number
}

interface LastPayroll {
  batch_id: number
  batch_ref: string
  company_name: string
  source: string
  finalized_at: string | null
  week_start: string | null
  week_end: string | null
  total_paid: number
  driver_count: number
}

interface WeekProgress {
  school_week: number | null
  days_into_week: number
  week_day_count: number
  today_total: number
  avg_daily_last_4w: number
  projected_week_total: number
}

interface MoneyFlow {
  week_start: string
  week_end: string
  partner_receipts: number
  driver_pay: number
  margin: number
  margin_pct: number
}

interface DashboardSummary {
  today_trips: {
    fa: TripBucket
    ed: TripBucket
    total: number
  }
  active_drivers: {
    count: number
    idle_over_2h: number
  }
  health: {
    overall: 'green' | 'yellow' | 'red' | 'unknown'
    checks: HealthCheck[]
    open_alerts: number
  }
  inflight_alerts: number
  last_payroll: LastPayroll | null
  week_progress: WeekProgress
  money_flow: MoneyFlow
  server_time: string
}

// ── Constants ─────────────────────────────────────────────────────────────────

const POLL_MS = 60_000

const FADE_RISE = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.32, ease: [0.16, 1, 0.3, 1] },
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt$(n: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(n)
}

function fmtRelTime(iso: string | null): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function getGreeting(): string {
  const h = new Date().getHours()
  if (h >= 5 && h < 12) return 'Good morning, Malik'
  if (h >= 12 && h < 17) return 'Good afternoon, Malik'
  return 'Good evening, Malik'
}

function healthColor(status: string): string {
  if (status === 'green') return '#10B981'
  if (status === 'yellow') return '#f59e0b'
  if (status === 'red') return '#ef4444'
  return '#6b7280'
}

function healthLabel(name: string): string {
  const map: Record<string, string> = {
    backend_alive: 'Backend',
    db_responsive: 'Database',
    everdriven_freshness: 'EverDriven',
    firstalt_freshness: 'FirstAlt',
    twilio_balance: 'Twilio',
    sms_canary: 'SMS Canary',
  }
  return map[name] ?? name.replace(/_/g, ' ')
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10px] font-semibold uppercase tracking-[0.08em] dark:text-white/30 text-gray-400 mb-3 px-0.5">
      {children}
    </p>
  )
}

function Tile({
  children,
  className,
  index = 0,
}: {
  children: React.ReactNode
  className?: string
  index?: number
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, delay: index * 0.055, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        'rounded-2xl transition-all duration-150',
        'dark:bg-white/[0.04] dark:border dark:border-white/[0.08]',
        'bg-white border border-gray-200',
        className
      )}
    >
      {children}
    </motion.div>
  )
}

// ── Trip Partner Card ─────────────────────────────────────────────────────────

function TripCard({
  label,
  color,
  data,
  index,
}: {
  label: string
  color: string
  data: TripBucket
  index: number
}) {
  const hasIssue = data.escalations > 0
  const completedPct = data.total > 0 ? Math.round((data.completed / data.total) * 100) : 0

  return (
    <Tile index={index} className="p-5" style={{ borderLeftWidth: 2, borderLeftColor: color } as React.CSSProperties}>
      <div className="flex items-center justify-between mb-4">
        <span
          className="px-2.5 py-0.5 rounded-full text-xs font-semibold border"
          style={{ background: `${color}18`, color, borderColor: `${color}40` }}
        >
          {label}
        </span>
        {hasIssue ? (
          <span className="flex items-center gap-1 text-xs text-red-400 font-medium">
            <AlertTriangle className="w-3 h-3" />
            {data.escalations} escalation{data.escalations !== 1 ? 's' : ''}
          </span>
        ) : data.total > 0 ? (
          <span className="flex items-center gap-1 text-xs text-emerald-400">
            <CheckCircle2 className="w-3 h-3" />
            Clean
          </span>
        ) : null}
      </div>

      {data.total === 0 ? (
        <p className="text-sm dark:text-white/30 text-gray-400">No trips today</p>
      ) : (
        <div className="space-y-4">
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-bold dark:text-white text-gray-900 tabular-nums">
              {data.total}
            </span>
            <span className="text-sm dark:text-white/40 text-gray-400">trips</span>
          </div>

          <div className="grid grid-cols-3 gap-2">
            {[
              { key: 'live', label: 'Live', val: data.live, hi: '#667eea' },
              { key: 'completed', label: 'Done', val: data.completed, hi: '#10B981' },
              { key: 'canceled', label: 'Canceled', val: data.canceled, hi: '#6b7280' },
            ].map(({ key, label: lb, val, hi }) => (
              <div key={key} className="rounded-xl dark:bg-white/[0.04] bg-gray-50 p-2.5 text-center">
                <p className="text-xs dark:text-white/40 text-gray-400 mb-1">{lb}</p>
                <p className="text-lg font-bold" style={{ color: val > 0 ? hi : undefined }}>
                  {val}
                </p>
              </div>
            ))}
          </div>

          {/* completion bar */}
          <div className="space-y-1">
            <div className="h-1.5 rounded-full dark:bg-white/[0.06] bg-gray-100 overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${completedPct}%` }}
                transition={{ duration: 0.7, ease: 'easeOut' }}
                className="h-full rounded-full"
                style={{ background: color }}
              />
            </div>
            <p className="text-[10px] dark:text-white/30 text-gray-400 text-right">
              {completedPct}% complete
            </p>
          </div>
        </div>
      )}
    </Tile>
  )
}

// ── Health Pill ───────────────────────────────────────────────────────────────

function HealthDot({ status }: { status: string }) {
  const c = healthColor(status)
  return (
    <span
      className="inline-block w-2 h-2 rounded-full flex-shrink-0"
      style={{ background: c, boxShadow: status === 'red' ? `0 0 6px ${c}` : undefined }}
    />
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [data, setData] = useState<DashboardSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const result = await api.get<DashboardSummary>('/api/data/dashboard/summary')
      setData(result)
      setLastRefresh(new Date())
      setError('')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load dashboard')
    }
  }, [])

  useEffect(() => {
    fetchData().finally(() => setLoading(false))
    timerRef.current = setInterval(fetchData, POLL_MS)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchData])

  if (loading) return <LoadingSpinner fullPage />

  const d = data
  const wp = d?.week_progress
  const mf = d?.money_flow
  const ad = d?.active_drivers
  const health = d?.health

  const weekLabel = wp?.school_week != null ? `W${wp.school_week}` : 'This week'
  const weekPct = wp
    ? Math.min(100, Math.round((wp.days_into_week / wp.week_day_count) * 100))
    : 0

  return (
    <div className="max-w-5xl mx-auto space-y-7 py-6 pb-12">

      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold dark:text-white text-gray-900 tracking-tight">
            {getGreeting()}
          </h1>
          <p className="text-sm dark:text-white/40 text-gray-400 mt-0.5">
            {new Date().toLocaleDateString('en-US', {
              weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
            })}
            {lastRefresh && (
              <span className="ml-2 dark:text-white/20 text-gray-300">
                &middot; updated {fmtRelTime(lastRefresh.toISOString())}
              </span>
            )}
          </p>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm dark:text-white/50 text-gray-500 dark:hover:bg-white/[0.08] hover:bg-gray-100 transition-all cursor-pointer border dark:border-white/[0.08] border-gray-200"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      <AnimatePresence>
        {error && (
          <motion.div
            key="err"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm"
          >
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Today's Trips ── */}
      <section>
        <SectionLabel>Today&apos;s trips</SectionLabel>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <TripCard label="FirstAlt" color="#667eea" data={d?.today_trips.fa ?? { total: 0, live: 0, completed: 0, canceled: 0, escalations: 0 }} index={0} />
          <TripCard label="EverDriven" color="#06b6d4" data={d?.today_trips.ed ?? { total: 0, live: 0, completed: 0, canceled: 0, escalations: 0 }} index={1} />
        </div>
      </section>

      {/* ── Row: Drivers + In-flight Alerts ── */}
      <section>
        <SectionLabel>Operations</SectionLabel>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">

          {/* Active Drivers */}
          <Tile index={2} className="p-5">
            <div className="flex items-start justify-between mb-3">
              <div className="w-9 h-9 rounded-xl bg-[#667eea]/10 flex items-center justify-center text-[#667eea]">
                <Users className="w-4 h-4" />
              </div>
              {ad && ad.idle_over_2h > 0 && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-500 border border-amber-500/20 font-medium">
                  {ad.idle_over_2h} idle &gt;2h
                </span>
              )}
            </div>
            <p className="text-4xl font-bold dark:text-white text-gray-900 tabular-nums mb-1">
              {ad?.count ?? 0}
            </p>
            <p className="text-sm dark:text-white/40 text-gray-400">active drivers today</p>
          </Tile>

          {/* In-flight Alerts */}
          <Tile index={3} className="p-5">
            <div className="flex items-start justify-between mb-3">
              <div className={cn(
                'w-9 h-9 rounded-xl flex items-center justify-center',
                (d?.inflight_alerts ?? 0) > 0
                  ? 'bg-red-500/10 text-red-400'
                  : 'bg-emerald-500/10 text-emerald-400'
              )}>
                <Zap className="w-4 h-4" />
              </div>
              <Link
                href="/dispatch/monitor"
                className="text-xs dark:text-white/40 text-gray-400 hover:dark:text-white/70 hover:text-gray-600 flex items-center gap-1 transition-colors"
              >
                Monitor <ArrowRight className="w-3 h-3" />
              </Link>
            </div>
            <p className={cn(
              'text-4xl font-bold tabular-nums mb-1',
              (d?.inflight_alerts ?? 0) > 0 ? 'text-red-400' : 'dark:text-white text-gray-900'
            )}>
              {d?.inflight_alerts ?? 0}
            </p>
            <p className="text-sm dark:text-white/40 text-gray-400">in-flight escalations</p>
          </Tile>
        </div>
      </section>

      {/* ── Row: Week Progress + Money Flow ── */}
      <section>
        <SectionLabel>This week &mdash; {weekLabel}</SectionLabel>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">

          {/* Week Progress */}
          <Tile index={4} className="p-5">
            <div className="flex items-start justify-between mb-4">
              <div className="w-9 h-9 rounded-xl bg-[#667eea]/10 flex items-center justify-center text-[#667eea]">
                <TrendingUp className="w-4 h-4" />
              </div>
              <span className="text-xs dark:text-white/40 text-gray-400 tabular-nums">
                Day {wp?.days_into_week ?? '—'} of {wp?.week_day_count ?? 5}
              </span>
            </div>

            <div className="mb-4">
              <p className="text-[10px] uppercase tracking-wide dark:text-white/30 text-gray-400 mb-1">
                Projected total
              </p>
              <p className="text-3xl font-bold dark:text-white text-gray-900 tabular-nums">
                {wp?.projected_week_total ?? 0}
                <span className="text-base font-normal dark:text-white/30 text-gray-400 ml-1">trips</span>
              </p>
              <p className="text-xs dark:text-white/30 text-gray-400 mt-0.5">
                {wp?.avg_daily_last_4w ?? 0}/day avg &middot; {wp?.today_total ?? 0} today
              </p>
            </div>

            {/* week progress bar */}
            <div className="space-y-1.5">
              <div className="h-2 rounded-full dark:bg-white/[0.06] bg-gray-100 overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${weekPct}%` }}
                  transition={{ duration: 0.8, ease: 'easeOut' }}
                  className="h-full rounded-full bg-[#667eea]"
                />
              </div>
              <p className="text-[10px] dark:text-white/30 text-gray-400 text-right">
                {weekPct}% through the week
              </p>
            </div>
          </Tile>

          {/* Money Flow */}
          <Tile index={5} className="p-5">
            <div className="flex items-start justify-between mb-4">
              <div className="w-9 h-9 rounded-xl bg-emerald-500/10 flex items-center justify-center text-emerald-500">
                <DollarSign className="w-4 h-4" />
              </div>
              <span className="text-xs dark:text-white/40 text-gray-400">Week margin</span>
            </div>

            <p className="text-3xl font-bold tabular-nums mb-1" style={{ color: (mf?.margin ?? 0) >= 0 ? '#10B981' : '#ef4444' }}>
              {fmt$(mf?.margin ?? 0)}
            </p>
            <p className="text-xs dark:text-white/30 text-gray-400 mb-4">
              {(mf?.margin_pct ?? 0).toFixed(1)}% margin
            </p>

            <div className="space-y-2">
              {[
                { label: 'Partner receipts', val: mf?.partner_receipts ?? 0, color: '#10B981' },
                { label: 'Driver pay', val: mf?.driver_pay ?? 0, color: '#667eea' },
              ].map(({ label, val, color }) => (
                <div key={label} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
                    <span className="text-xs dark:text-white/50 text-gray-500">{label}</span>
                  </div>
                  <span className="text-xs font-semibold dark:text-white/80 text-gray-700 tabular-nums">
                    {fmt$(val)}
                  </span>
                </div>
              ))}

              {/* stacked bar */}
              {(mf?.partner_receipts ?? 0) > 0 && (
                <div className="h-1.5 rounded-full dark:bg-white/[0.06] bg-gray-100 overflow-hidden mt-2">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.min(100, ((mf?.driver_pay ?? 0) / (mf?.partner_receipts ?? 1)) * 100)}%` }}
                    transition={{ duration: 0.8, ease: 'easeOut' }}
                    className="h-full rounded-full bg-[#667eea]"
                  />
                </div>
              )}
            </div>
          </Tile>
        </div>
      </section>

      {/* ── Last Payroll ── */}
      {d?.last_payroll && (
        <section>
          <SectionLabel>Last payroll</SectionLabel>
          <Tile index={6} className="p-5">
            <div className="flex items-center gap-4 flex-wrap">
              <div className="w-9 h-9 rounded-xl bg-[#06b6d4]/10 flex items-center justify-center text-[#06b6d4] flex-shrink-0">
                <Car className="w-4 h-4" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold dark:text-white text-gray-900">
                  {d.last_payroll.company_name}
                  <span className="ml-2 text-xs dark:text-white/40 text-gray-400 font-normal">
                    {d.last_payroll.batch_ref}
                  </span>
                </p>
                <p className="text-xs dark:text-white/40 text-gray-400 mt-0.5">
                  Finalized {fmtRelTime(d.last_payroll.finalized_at)}
                  {d.last_payroll.week_start && (
                    <span className="ml-2">
                      &middot; {new Date(d.last_payroll.week_start + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                      {d.last_payroll.week_end && (
                        <> – {new Date(d.last_payroll.week_end + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</>
                      )}
                    </span>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-6 ml-auto flex-shrink-0">
                <div className="text-right">
                  <p className="text-xs dark:text-white/30 text-gray-400">Drivers paid</p>
                  <p className="text-xl font-bold dark:text-white text-gray-900 tabular-nums">
                    {d.last_payroll.driver_count}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-xs dark:text-white/30 text-gray-400">Total paid out</p>
                  <p className="text-xl font-bold text-emerald-500 tabular-nums">
                    {fmt$(d.last_payroll.total_paid)}
                  </p>
                </div>
              </div>
            </div>
          </Tile>
        </section>
      )}

      {/* ── Health Checks ── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <SectionLabel>System health</SectionLabel>
          <Link
            href="/health"
            className="text-xs dark:text-white/40 text-gray-400 hover:dark:text-white/60 hover:text-gray-600 flex items-center gap-1 transition-colors mb-3"
          >
            <Activity className="w-3 h-3" />
            Full monitor
          </Link>
        </div>

        <Tile index={7} className="divide-y dark:divide-white/[0.06] divide-gray-100">
          {/* overall badge */}
          <div className="px-5 py-3.5 flex items-center justify-between">
            <span className="text-sm font-semibold dark:text-white text-gray-900">
              Overall
            </span>
            <span
              className="flex items-center gap-1.5 text-sm font-semibold capitalize px-3 py-1 rounded-full border"
              style={{
                color: healthColor(health?.overall ?? 'unknown'),
                background: `${healthColor(health?.overall ?? 'unknown')}15`,
                borderColor: `${healthColor(health?.overall ?? 'unknown')}30`,
              }}
            >
              <span
                className="w-2 h-2 rounded-full"
                style={{ background: healthColor(health?.overall ?? 'unknown') }}
              />
              {health?.overall ?? 'unknown'}
              {(health?.open_alerts ?? 0) > 0 && (
                <span className="ml-1 text-xs">· {health!.open_alerts} open alert{health!.open_alerts !== 1 ? 's' : ''}</span>
              )}
            </span>
          </div>

          {/* per-check rows */}
          {(health?.checks ?? []).length === 0 ? (
            <div className="px-5 py-4 text-sm dark:text-white/30 text-gray-400">
              No health data — monitor may be disabled
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2">
              {(health?.checks ?? []).map((check, i) => (
                <motion.div
                  key={check.name}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.35 + i * 0.04 }}
                  className={cn(
                    'flex items-center justify-between px-5 py-3',
                    'dark:border-white/[0.06] border-gray-100',
                    i % 2 === 0 ? 'sm:border-r' : '',
                    i < (health?.checks.length ?? 0) - 2 ? 'border-b' : '',
                    i === (health?.checks.length ?? 0) - 1 && (health?.checks.length ?? 0) % 2 !== 0 ? 'sm:col-span-2' : '',
                  )}
                >
                  <div className="flex items-center gap-2.5">
                    <HealthDot status={check.status} />
                    <span className="text-sm dark:text-white/70 text-gray-700">
                      {healthLabel(check.name)}
                    </span>
                  </div>
                  <span className="text-xs dark:text-white/30 text-gray-400">
                    {fmtRelTime(check.last_checked_at)}
                  </span>
                </motion.div>
              ))}
            </div>
          )}
        </Tile>
      </section>

    </div>
  )
}
