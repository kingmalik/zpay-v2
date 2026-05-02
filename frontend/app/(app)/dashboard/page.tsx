'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import Link from 'next/link'
import { motion, AnimatePresence } from 'framer-motion'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  DollarSign,
  Radio,
  RefreshCw,
  TrendingUp,
  Users,
  Zap,
  Activity,
  GitBranch,
  BarChart2,
  Navigation2,
  AlertCircle,
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

interface MissingPaychex {
  person_id: number
  name: string
  missing_fa: boolean
  missing_ed: boolean
}

interface WithheldDriver {
  person_id: number
  name: string
  amount: number
  batch_id: number
}

interface OpenBatch {
  batch_id: number
  batch_ref: string
  source: string
  company_name: string
  ride_count: number
  week_start: string | null
}

interface PendingPayroll {
  open_batch: OpenBatch | null
  missing_paychex_count: number
  missing_paychex: MissingPaychex[]
  withheld_count: number
  withheld_drivers: WithheldDriver[]
  nuraynie_owed: number | null
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
  pending_payroll: PendingPayroll
  server_time: string
}

// ── Constants ─────────────────────────────────────────────────────────────────

const POLL_MS = 60_000
const EASE_OUT_EXPO: [number, number, number, number] = [0.16, 1, 0.3, 1]

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
  if (h >= 5 && h < 12) return 'Morning'
  if (h >= 12 && h < 17) return 'Afternoon'
  return 'Evening'
}

function healthColor(status: string): string {
  if (status === 'green') return '#10B981'
  if (status === 'yellow') return '#f59e0b'
  if (status === 'red') return '#ef4444'
  return '#9ca3af'
}

// ── Animation ─────────────────────────────────────────────────────────────────

function fadeRise(delay = 0) {
  return {
    initial: { opacity: 0, y: 16 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.38, delay, ease: EASE_OUT_EXPO },
  }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-stone-400 dark:text-white/30 mb-2.5">
      {children}
    </p>
  )
}

function Tile({
  children,
  className,
  delay = 0,
  accent,
}: {
  children: React.ReactNode
  className?: string
  delay?: number
  accent?: string
}) {
  return (
    <motion.div
      {...fadeRise(delay)}
      className={cn(
        'relative rounded-2xl overflow-hidden',
        'bg-white border border-stone-200/80 shadow-[0_1px_3px_rgba(0,0,0,0.06)]',
        'dark:bg-white/[0.04] dark:border-white/[0.08] dark:shadow-none',
        className
      )}
      style={accent ? ({ borderTopColor: accent, borderTopWidth: 2 } as React.CSSProperties) : undefined}
    >
      {children}
    </motion.div>
  )
}

// ── Partner trip tile ─────────────────────────────────────────────────────────

function PartnerTile({
  label,
  color,
  data,
  delay,
}: {
  label: string
  color: string
  data: TripBucket
  delay: number
}) {
  const completedPct = data.total > 0 ? Math.round((data.completed / data.total) * 100) : 0
  const hasIssue = data.escalations > 0

  return (
    <Tile delay={delay} accent={color} className="p-6">
      <div className="flex items-start justify-between mb-5">
        <span
          className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border"
          style={{ color, background: `${color}12`, borderColor: `${color}30` }}
        >
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
          {label}
        </span>
        {hasIssue ? (
          <span className="flex items-center gap-1 text-xs text-red-500 font-medium">
            <AlertTriangle className="w-3 h-3" />
            {data.escalations} escalation{data.escalations !== 1 ? 's' : ''}
          </span>
        ) : data.total > 0 ? (
          <CheckCircle2 className="w-4 h-4 text-emerald-500" />
        ) : null}
      </div>

      {data.total === 0 ? (
        <p className="text-sm text-stone-400 dark:text-white/30 mt-2">No trips today</p>
      ) : (
        <>
          <div className="flex items-baseline gap-2 mb-5">
            <motion.span
              key={data.total}
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, ease: EASE_OUT_EXPO }}
              className="text-5xl font-bold text-stone-900 dark:text-white tabular-nums"
              style={{ letterSpacing: '-0.02em' }}
            >
              {data.total}
            </motion.span>
            <span className="text-base text-stone-400 dark:text-white/30">trips</span>
          </div>

          <div className="grid grid-cols-3 gap-2 mb-4">
            {([
              { key: 'live', label: 'Live', val: data.live, hi: color },
              { key: 'done', label: 'Done', val: data.completed, hi: '#10B981' },
              { key: 'cancel', label: 'Canceled', val: data.canceled, hi: '#9ca3af' },
            ] as const).map((item) => (
              <div key={item.key} className="rounded-xl bg-stone-50 dark:bg-white/[0.04] p-3 text-center">
                <p className="text-[10px] text-stone-400 dark:text-white/30 mb-1 uppercase tracking-wide">{item.label}</p>
                <p className="text-xl font-bold tabular-nums" style={{ color: item.val > 0 ? item.hi : '#9ca3af' }}>
                  {item.val}
                </p>
              </div>
            ))}
          </div>

          <div className="space-y-1">
            <div className="h-1 rounded-full bg-stone-100 dark:bg-white/[0.06] overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${completedPct}%` }}
                transition={{ duration: 0.9, ease: 'easeOut', delay: delay + 0.2 }}
                className="h-full rounded-full"
                style={{ background: color }}
              />
            </div>
            <p className="text-[10px] text-stone-400 dark:text-white/30 text-right tabular-nums">
              {completedPct}% complete
            </p>
          </div>
        </>
      )}
    </Tile>
  )
}

// ── Money tile ────────────────────────────────────────────────────────────────

function MoneyTile({ mf, wp, delay }: { mf: MoneyFlow | undefined; wp: WeekProgress | undefined; delay: number }) {
  const margin = mf?.margin ?? 0
  const receipts = mf?.partner_receipts ?? 0
  const driverPay = mf?.driver_pay ?? 0
  const pct = mf?.margin_pct ?? 0
  const driverShare = receipts > 0 ? Math.min(100, (driverPay / receipts) * 100) : 0

  return (
    <Tile delay={delay} className="p-6" accent="#10B981">
      <div className="flex items-start justify-between mb-1">
        <Label>This week</Label>
        <span className="text-[10px] text-stone-400 dark:text-white/30 font-medium">
          {wp?.school_week != null ? `Week ${wp.school_week}` : ''}
        </span>
      </div>

      <motion.p
        key={margin}
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.35, ease: EASE_OUT_EXPO }}
        className="text-4xl font-bold tabular-nums mb-0.5"
        style={{ color: margin >= 0 ? '#10B981' : '#ef4444', letterSpacing: '-0.02em' }}
      >
        {fmt$(margin)}
      </motion.p>
      <p className="text-xs text-stone-400 dark:text-white/30 mb-5">
        {pct.toFixed(1)}% margin
      </p>

      <div className="space-y-2.5">
        {([
          { label: 'Partner in', val: receipts, color: '#10B981' },
          { label: 'Driver pay', val: driverPay, color: '#667eea' },
        ] as const).map(({ label, val, color }) => (
          <div key={label} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
              <span className="text-xs text-stone-500 dark:text-white/50">{label}</span>
            </div>
            <span className="text-xs font-semibold text-stone-700 dark:text-white/80 tabular-nums">{fmt$(val)}</span>
          </div>
        ))}

        {receipts > 0 && (
          <div className="pt-1">
            <div className="h-1.5 rounded-full bg-stone-100 dark:bg-white/[0.06] overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${driverShare}%` }}
                transition={{ duration: 0.9, ease: 'easeOut', delay: delay + 0.3 }}
                className="h-full rounded-full bg-indigo-500"
              />
            </div>
            <p className="text-[10px] text-stone-400 dark:text-white/20 mt-1">
              Driver cost is {driverShare.toFixed(0)}% of receipts
            </p>
          </div>
        )}
      </div>
    </Tile>
  )
}

// ── Pending payroll actions tile ──────────────────────────────────────────────

function PayrollActionsTile({ pp, delay }: { pp: PendingPayroll | undefined; delay: number }) {
  if (!pp) return null

  const totalActions =
    (pp.open_batch ? 1 : 0) +
    pp.missing_paychex_count +
    (pp.nuraynie_owed ? 1 : 0)
  const hasActions = totalActions > 0 || pp.withheld_count > 0

  return (
    <Tile delay={delay} accent={hasActions ? '#f59e0b' : '#10B981'} className="p-6">
      <div className="flex items-center justify-between mb-4">
        <Label>Payroll actions</Label>
        {hasActions ? (
          <span className="flex items-center gap-1 text-xs font-semibold text-amber-600 dark:text-amber-400">
            <AlertCircle className="w-3.5 h-3.5" />
            {totalActions} item{totalActions !== 1 ? 's' : ''}
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="w-3.5 h-3.5" />
            Clear
          </span>
        )}
      </div>

      <div className="space-y-2.5">
        {pp.open_batch && (
          <Link href={`/payroll/workflow/${pp.open_batch.batch_id}`}>
            <div className="flex items-start gap-3 p-3 rounded-xl bg-amber-50 dark:bg-amber-500/10 border border-amber-200/60 dark:border-amber-500/20 cursor-pointer hover:bg-amber-100 dark:hover:bg-amber-500/20 transition-colors">
              <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
              <div className="min-w-0">
                <p className="text-xs font-semibold text-amber-800 dark:text-amber-300 leading-tight">
                  Open batch — {pp.open_batch.company_name}
                </p>
                <p className="text-[10px] text-amber-600 dark:text-amber-400/80 mt-0.5">
                  {pp.open_batch.ride_count} rides, not finalized
                </p>
              </div>
            </div>
          </Link>
        )}

        {pp.nuraynie_owed !== null && (
          <div className="flex items-start gap-3 p-3 rounded-xl bg-orange-50 dark:bg-orange-500/10 border border-orange-200/60 dark:border-orange-500/20">
            <Clock className="w-4 h-4 text-orange-500 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-semibold text-orange-800 dark:text-orange-300">
                Nuraynie — {fmt$(pp.nuraynie_owed)} owed
              </p>
              <p className="text-[10px] text-orange-600 dark:text-orange-400/80 mt-0.5">
                Pay when Paychex ID confirmed
              </p>
            </div>
          </div>
        )}

        {pp.missing_paychex_count > 0 && (
          <Link href="/people">
            <div className="flex items-start gap-3 p-3 rounded-xl bg-red-50 dark:bg-red-500/10 border border-red-200/60 dark:border-red-500/20 cursor-pointer hover:bg-red-100 dark:hover:bg-red-500/20 transition-colors">
              <AlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-semibold text-red-800 dark:text-red-300">
                  {pp.missing_paychex_count} driver{pp.missing_paychex_count !== 1 ? 's' : ''} missing Paychex code
                </p>
                <p className="text-[10px] text-red-600 dark:text-red-400/80 mt-0.5">
                  {pp.missing_paychex.slice(0, 2).map((m) => m.name).join(', ')}
                  {pp.missing_paychex_count > 2 ? ` +${pp.missing_paychex_count - 2} more` : ''}
                </p>
              </div>
            </div>
          </Link>
        )}

        {pp.withheld_count > 0 && (
          <Link href="/payroll/workflow">
            <div className="flex items-center justify-between p-3 rounded-xl bg-stone-50 dark:bg-white/[0.04] border border-stone-200/60 dark:border-white/[0.06] cursor-pointer hover:bg-stone-100 dark:hover:bg-white/[0.06] transition-colors">
              <div className="flex items-center gap-2.5">
                <div className="w-7 h-7 rounded-lg bg-indigo-100 dark:bg-indigo-500/15 flex items-center justify-center">
                  <DollarSign className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" />
                </div>
                <div>
                  <p className="text-xs font-semibold text-stone-700 dark:text-white/80">
                    {pp.withheld_count} driver{pp.withheld_count !== 1 ? 's' : ''} withheld
                  </p>
                  <p className="text-[10px] text-stone-400 dark:text-white/30">
                    {fmt$(pp.withheld_drivers.reduce((s, w) => s + w.amount, 0))} total held
                  </p>
                </div>
              </div>
              <ArrowRight className="w-3.5 h-3.5 text-stone-400" />
            </div>
          </Link>
        )}

        {!hasActions && pp.withheld_count === 0 && (
          <p className="text-xs text-stone-400 dark:text-white/30">No payroll actions needed.</p>
        )}
      </div>
    </Tile>
  )
}

// ── Week pace tile ────────────────────────────────────────────────────────────

function WeekTile({ wp, delay }: { wp: WeekProgress | undefined; delay: number }) {
  const weekPct = wp ? Math.min(100, Math.round((wp.days_into_week / wp.week_day_count) * 100)) : 0

  return (
    <Tile delay={delay} className="p-5">
      <Label>Trip pace</Label>
      <div className="flex items-baseline gap-1.5 mb-1">
        <span className="text-3xl font-bold text-stone-900 dark:text-white tabular-nums" style={{ letterSpacing: '-0.02em' }}>
          {wp?.today_total ?? 0}
        </span>
        <span className="text-sm text-stone-400 dark:text-white/30">today</span>
      </div>
      <p className="text-xs text-stone-400 dark:text-white/30 mb-4">
        {wp?.projected_week_total ?? 0} projected this week &middot; {wp?.avg_daily_last_4w ?? 0}/day avg
      </p>
      <div className="space-y-1">
        <div className="h-1.5 rounded-full bg-stone-100 dark:bg-white/[0.06] overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${weekPct}%` }}
            transition={{ duration: 0.9, ease: 'easeOut', delay: delay + 0.2 }}
            className="h-full rounded-full bg-indigo-500"
          />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-stone-400 dark:text-white/20">Day {wp?.days_into_week ?? '—'} of {wp?.week_day_count ?? 5}</span>
          <span className="text-[10px] text-stone-400 dark:text-white/20 tabular-nums">{weekPct}%</span>
        </div>
      </div>
    </Tile>
  )
}

// ── Ops stats tile ────────────────────────────────────────────────────────────

function OpsStatsTile({
  activeDrivers,
  inflightAlerts,
  delay,
}: {
  activeDrivers: { count: number; idle_over_2h: number } | undefined
  inflightAlerts: number
  delay: number
}) {
  return (
    <Tile delay={delay} className="p-5">
      <Label>Operations</Label>
      <div className="flex items-stretch divide-x divide-stone-100 dark:divide-white/[0.06]">
        <div className="flex-1 pr-4">
          <div className="flex items-center gap-2 mb-1">
            <Users className="w-3.5 h-3.5 text-indigo-500" />
            <span className="text-[10px] text-stone-400 dark:text-white/30 uppercase tracking-wide">Drivers</span>
          </div>
          <p className="text-2xl font-bold text-stone-900 dark:text-white tabular-nums">
            {activeDrivers?.count ?? 0}
          </p>
          {(activeDrivers?.idle_over_2h ?? 0) > 0 && (
            <p className="text-[10px] text-amber-500 mt-0.5">{activeDrivers!.idle_over_2h} idle &gt;2h</p>
          )}
        </div>
        <div className="flex-1 pl-4">
          <div className="flex items-center gap-2 mb-1">
            <Zap className={cn('w-3.5 h-3.5', inflightAlerts > 0 ? 'text-red-500' : 'text-emerald-500')} />
            <span className="text-[10px] text-stone-400 dark:text-white/30 uppercase tracking-wide">Escalations</span>
          </div>
          <p className={cn('text-2xl font-bold tabular-nums', inflightAlerts > 0 ? 'text-red-500' : 'text-stone-900 dark:text-white')}>
            {inflightAlerts}
          </p>
          <Link href="/dispatch/monitor" className="text-[10px] text-indigo-500 hover:text-indigo-700 flex items-center gap-0.5 mt-0.5 transition-colors">
            Monitor <ArrowRight className="w-2.5 h-2.5" />
          </Link>
        </div>
      </div>
    </Tile>
  )
}

// ── Partner health strip ──────────────────────────────────────────────────────

function PartnerHealthTile({ checks, delay }: { checks: HealthCheck[]; delay: number }) {
  const items = [
    { label: 'FirstAlt', check: checks.find((c) => c.name === 'firstalt_freshness') },
    { label: 'EverDriven', check: checks.find((c) => c.name === 'everdriven_freshness') },
    { label: 'Backend', check: checks.find((c) => c.name === 'backend_alive') },
    { label: 'Database', check: checks.find((c) => c.name === 'db_responsive') },
  ]

  return (
    <Tile delay={delay} className="p-5">
      <div className="flex items-center justify-between mb-3">
        <Label>System</Label>
        <Link href="/health" className="text-[10px] text-stone-400 hover:text-stone-600 dark:hover:text-white/50 flex items-center gap-0.5 transition-colors mb-2.5">
          <Activity className="w-3 h-3" />
          <span>Monitor</span>
        </Link>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {items.map(({ label, check }) => {
          const status = check?.status ?? 'unknown'
          const c = healthColor(status)
          return (
            <div key={label} className="flex items-center gap-2">
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ background: c, boxShadow: status === 'red' ? `0 0 5px ${c}` : undefined }}
              />
              <span className="text-xs text-stone-600 dark:text-white/60">{label}</span>
            </div>
          )
        })}
      </div>
    </Tile>
  )
}

// ── Quick links strip ─────────────────────────────────────────────────────────

function QuickLinks({ delay }: { delay: number }) {
  const links = [
    { label: 'Workflow', href: '/payroll/workflow', icon: <GitBranch className="w-4 h-4" />, sub: 'current week', color: '#667eea' },
    { label: 'Live Ops', href: '/ops/live', icon: <Radio className="w-4 h-4" />, sub: 'dispatch center', color: '#06b6d4' },
    { label: 'Dispatch', href: '/dispatch', icon: <Navigation2 className="w-4 h-4" />, sub: 'manage drivers', color: '#8b5cf6' },
    { label: 'Scorecard', href: '/dispatch/reliability', icon: <BarChart2 className="w-4 h-4" />, sub: 'driver rankings', color: '#f59e0b' },
    { label: 'More', href: '/menu', icon: <TrendingUp className="w-4 h-4" />, sub: 'all pages', color: '#9ca3af' },
  ]

  return (
    <motion.div {...fadeRise(delay)} className="grid grid-cols-2 sm:grid-cols-5 gap-3">
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className={cn(
            'group flex flex-col gap-2 p-4 rounded-2xl',
            'bg-white border border-stone-200/80 shadow-[0_1px_3px_rgba(0,0,0,0.05)]',
            'dark:bg-white/[0.04] dark:border-white/[0.08]',
            'hover:shadow-[0_3px_12px_rgba(0,0,0,0.09)] dark:hover:bg-white/[0.07]',
            'transition-all duration-150'
          )}
        >
          <div
            className="w-8 h-8 rounded-xl flex items-center justify-center"
            style={{ background: `${link.color}15`, color: link.color }}
          >
            {link.icon}
          </div>
          <div>
            <p className="text-xs font-semibold text-stone-800 dark:text-white/80 group-hover:text-stone-900 dark:group-hover:text-white transition-colors">
              {link.label}
            </p>
            <p className="text-[10px] text-stone-400 dark:text-white/30">{link.sub}</p>
          </div>
        </Link>
      ))}
    </motion.div>
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
  const pp = d?.pending_payroll
  const health = d?.health

  return (
    <div className="max-w-5xl mx-auto py-6 pb-14 space-y-7">

      {/* ── Header ── */}
      <motion.div {...fadeRise(0)} className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-stone-900 dark:text-white tracking-tight" style={{ letterSpacing: '-0.02em' }}>
            {getGreeting()}, Malik
          </h1>
          <p className="text-sm text-stone-400 dark:text-white/30 mt-0.5">
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
            {lastRefresh && (
              <span className="ml-2 text-stone-300 dark:text-white/20">
                &middot; {fmtRelTime(lastRefresh.toISOString())}
              </span>
            )}
          </p>
        </div>
        <button
          onClick={fetchData}
          aria-label="Refresh dashboard"
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm text-stone-500 dark:text-white/40 hover:bg-stone-100 dark:hover:bg-white/[0.08] border border-stone-200 dark:border-white/[0.08] transition-all cursor-pointer"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </motion.div>

      <AnimatePresence>
        {error && (
          <motion.div
            key="err"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="px-4 py-3 rounded-xl bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 text-red-600 dark:text-red-400 text-sm"
          >
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Quick links ── */}
      <section>
        <Label>Quick access</Label>
        <QuickLinks delay={0.04} />
      </section>

      {/* ── Today at a glance: partner heroes + money ── */}
      <section>
        <Label>Today at a glance</Label>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <PartnerTile
            label="FirstAlt"
            color="#667eea"
            data={d?.today_trips.fa ?? { total: 0, live: 0, completed: 0, canceled: 0, escalations: 0 }}
            delay={0.06}
          />
          <PartnerTile
            label="EverDriven"
            color="#06b6d4"
            data={d?.today_trips.ed ?? { total: 0, live: 0, completed: 0, canceled: 0, escalations: 0 }}
            delay={0.1}
          />
          <MoneyTile mf={mf} wp={wp} delay={0.14} />
        </div>
      </section>

      {/* ── Ops row: active drivers + pace + health ── */}
      <section>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <OpsStatsTile activeDrivers={ad} inflightAlerts={d?.inflight_alerts ?? 0} delay={0.18} />
          <WeekTile wp={wp} delay={0.22} />
          <PartnerHealthTile checks={health?.checks ?? []} delay={0.26} />
        </div>
      </section>

      {/* ── Payroll actions — full width ── */}
      <section>
        <PayrollActionsTile pp={pp} delay={0.3} />
      </section>

    </div>
  )
}
