'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { motion, type Variants } from 'framer-motion'
import {
  ArrowLeft,
  User,
  AlertCircle,
  TrendingUp,
  TrendingDown,
  Minus,
  Info,
  Calendar,
  DollarSign,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  CheckCircle2,
  XCircle,
} from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import TierBadge from '../TierBadge'

// ─── Types ────────────────────────────────────────────────────────────────────

interface AxisData {
  raw: number
  normalized: number
  weighted: number
  sample_size: number
  available: boolean
  label: string
  nominal_weight: number
}

interface WeekHistoryEntry {
  week_iso: string
  week_start: string
  composite_score: number | null
  tier: string
  total_trips: number
}

interface TripRow {
  id: number
  trip_date: string | null
  source: string
  trip_ref: string
  status: string | null
  pickup_time: string | null
  accepted_at: string | null
  started_at: string | null
  arrived_at_pickup: string | null
  completed_at: string | null
  accept_sms_at: string | null
  escalated: boolean
}

interface RecentEvent {
  ts: string
  description: string
  kind: string
}

interface DrilldownData {
  driver: {
    person_id: number
    name: string
    paycheck_code: string | null
    paycheck_code_maz: string | null
    active: boolean
  }
  current_week: {
    week_iso: string
    total_trips: number
    composite_score: number | null
    tier: string
    tier_label: string
    headline_metric: string | null
    focus_area: string | null
    low_sample: boolean
    wow_delta: number | null
    axes: Record<string, AxisData>
    revenue_impact: number
    revenue_impact_per_trip: number
    revenue_rank: number | null
  }
  weekly_history: WeekHistoryEntry[]
  trips_this_week: TripRow[]
  recent_events: RecentEvent[]
}

type TripSortKey = 'trip_date' | 'source' | 'status' | 'pickup_time' | 'escalated'
type SortDir = 'asc' | 'desc'

// ─── Animation variants ───────────────────────────────────────────────────────

const staggerContainer: Variants = {
  initial: {},
  animate: { transition: { staggerChildren: 0.06 } },
}

const cardVariants: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.2 } },
}

// ─── Axis display order ───────────────────────────────────────────────────────

const AXIS_DISPLAY_ORDER = [
  'acceptance',
  'on_time_start',
  'on_time_pickup_arrival',
  'on_time_completion',
  'responsiveness',
  'reliability',
]

// ─── 12-week trend chart ──────────────────────────────────────────────────────

function TrendChart({ history }: { history: WeekHistoryEntry[] }) {
  const valid = history.map(h => h.composite_score).filter((v): v is number => v !== null)

  if (valid.length === 0) {
    return (
      <div className="flex items-center justify-center h-16 dark:text-white/25 text-gray-400 text-xs">
        No data yet
      </div>
    )
  }

  const W = 320
  const H = 56
  const padX = 4
  const padY = 8
  const n = history.length

  const minY = Math.min(...valid, 50)
  const maxY = Math.max(...valid, 100)
  const rangeY = maxY - minY || 1

  const toX = (i: number) => padX + (i / Math.max(n - 1, 1)) * (W - padX * 2)
  const toY = (v: number) => H - padY - ((v - minY) / rangeY) * (H - padY * 2)

  const coords = history.map((h, i) => ({
    x: toX(i),
    y: h.composite_score !== null ? toY(h.composite_score) : null,
    entry: h,
  }))

  // Build SVG path — break on null gaps
  const segments: string[][] = []
  let current: string[] = []
  for (const c of coords) {
    if (c.y === null) {
      if (current.length > 0) { segments.push(current); current = [] }
      continue
    }
    current.push(
      current.length === 0
        ? `M${c.x.toFixed(1)},${c.y.toFixed(1)}`
        : `L${c.x.toFixed(1)},${c.y.toFixed(1)}`
    )
  }
  if (current.length > 0) segments.push(current)

  // Color the last dot by tier
  const lastWithScore = [...history].reverse().find(h => h.composite_score !== null)
  const lastDotColor =
    lastWithScore?.tier === 'gold' ? 'rgb(251 191 36)' :
    lastWithScore?.tier === 'silver' ? 'rgb(148 163 184)' :
    lastWithScore?.tier === 'bronze' ? 'rgb(234 179 8 / 0.8)' :
    'rgb(248 113 113)'

  return (
    <div className="flex flex-col gap-2">
      <svg
        width={W}
        height={H}
        className="overflow-visible w-full"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Dashed tier reference lines */}
        {[70, 80, 90].map(ref => {
          const ry = toY(ref)
          if (ry < 0 || ry > H) return null
          return (
            <line
              key={ref}
              x1={padX} y1={ry} x2={W - padX} y2={ry}
              stroke="currentColor"
              strokeWidth={0.5}
              strokeDasharray="3 3"
              className="dark:text-white/8 text-gray-200"
            />
          )
        })}

        {/* Path */}
        {segments.map((seg, si) => (
          <path
            key={si}
            d={seg.join(' ')}
            fill="none"
            stroke="rgb(102 126 234 / 0.6)"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}

        {/* Dots */}
        {coords.map((c, i) => {
          if (c.y === null) return null
          const isLast = !coords.slice(i + 1).some(cc => cc.y !== null)
          return (
            <circle
              key={i}
              cx={c.x}
              cy={c.y}
              r={isLast ? 4 : 2}
              fill={isLast ? lastDotColor : 'rgb(102 126 234 / 0.4)'}
              stroke={isLast ? lastDotColor.replace(')', ' / 0.25)').replace('rgb(', 'rgb(') : 'none'}
              strokeWidth={isLast ? 4 : 0}
            />
          )
        })}
      </svg>

      {/* Week labels — skip alternating on wide sets to avoid crowding */}
      <div className="flex justify-between text-[9px] dark:text-white/20 text-gray-400 tabular-nums px-1">
        {history.map((h, i) => {
          const wn = h.week_iso.split('-W')[1]
          const isLast = i === history.length - 1
          const show = history.length <= 8 || i % 2 === 0 || isLast
          return (
            <span
              key={i}
              className={cn(
                isLast && 'dark:text-white/50 text-gray-500 font-medium',
                !show && 'invisible'
              )}
            >
              W{wn}
            </span>
          )
        })}
      </div>
    </div>
  )
}

// ─── WoW delta badge ──────────────────────────────────────────────────────────

function DeltaBadge({ delta }: { delta: number | null }) {
  if (delta == null) return null
  const sign = delta > 0 ? '+' : ''
  const color = delta > 0 ? 'text-emerald-400' : delta < 0 ? 'text-red-400' : 'dark:text-white/40 text-gray-400'
  const Icon = delta > 0 ? TrendingUp : delta < 0 ? TrendingDown : Minus
  return (
    <span className={cn('inline-flex items-center gap-1 text-sm font-medium tabular-nums', color)}>
      <Icon className="w-3.5 h-3.5" />
      {sign}{delta.toFixed(1)} pts
    </span>
  )
}

// ─── Axis bar row ─────────────────────────────────────────────────────────────

function AxisRow({ ax }: { ax: AxisData }) {
  if (!ax.available) {
    return (
      <div className="flex items-center gap-3 py-2 opacity-40">
        <span className="w-40 text-xs dark:text-white/60 text-gray-600 truncate flex-shrink-0">{ax.label}</span>
        <div className="flex-1 h-1.5 rounded-full dark:bg-white/5 bg-gray-100" />
        <span className="w-14 text-right text-xs dark:text-white/30 text-gray-400">N/A</span>
        <span className="w-10 text-right text-[10px] dark:text-white/20 text-gray-300 tabular-nums">
          {Math.round(ax.nominal_weight * 100)}%
        </span>
      </div>
    )
  }

  const rawPct = ax.raw * 100
  const barColor =
    rawPct >= 90 ? 'bg-amber-400' :
    rawPct >= 80 ? 'bg-emerald-400' :
    rawPct >= 70 ? 'bg-blue-400' :
    rawPct >= 60 ? 'bg-orange-400' :
    'bg-red-400'
  const isLow = ax.sample_size < 3

  return (
    <div className="flex items-center gap-3 py-2">
      <span className="w-40 text-xs dark:text-white/70 text-gray-700 truncate flex-shrink-0">
        {ax.label}
      </span>
      <div className="flex-1 h-1.5 rounded-full dark:bg-white/8 bg-gray-100 overflow-hidden">
        <motion.div
          className={cn('h-full rounded-full', barColor)}
          initial={{ width: 0 }}
          animate={{ width: `${rawPct.toFixed(1)}%` }}
          transition={{ duration: 0.5, ease: 'easeOut', delay: 0.1 }}
        />
      </div>
      <span className={cn(
        'w-14 text-right text-xs tabular-nums font-medium',
        isLow ? 'dark:text-white/35 text-gray-400' : 'dark:text-white/80 text-gray-700'
      )}>
        {rawPct.toFixed(1)}%
        {isLow && (
          <span title={`Low sample (${ax.sample_size} trips)`}>
            <Info className="inline w-2.5 h-2.5 ml-0.5 -mt-0.5 dark:text-white/25 text-gray-300" />
          </span>
        )}
      </span>
      <span className="w-10 text-right text-[10px] dark:text-white/30 text-gray-400 tabular-nums">
        {Math.round(ax.nominal_weight * 100)}%
      </span>
    </div>
  )
}

// ─── Per-trip table ───────────────────────────────────────────────────────────

const PAGE_SIZE = 10

function SortTH({
  col, label, sortKey, sortDir, onSort,
}: {
  col: TripSortKey
  label: string
  sortKey: TripSortKey
  sortDir: SortDir
  onSort: (c: TripSortKey) => void
}) {
  const Icon = col !== sortKey ? ChevronsUpDown : sortDir === 'asc' ? ChevronUp : ChevronDown
  return (
    <th
      className="text-left py-2 px-2 text-[10px] uppercase tracking-wider dark:text-white/25 text-gray-400 font-medium cursor-pointer select-none hover:dark:text-white/50 hover:text-gray-600 transition-colors"
      onClick={() => onSort(col)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <Icon className="w-3 h-3" />
      </span>
    </th>
  )
}

function statusPill(status: string | null) {
  if (!status) return <span className="text-[10px] dark:text-white/20 text-gray-300">—</span>
  const s = status.toLowerCase()
  if (s.includes('complet'))
    return <span className="inline-flex items-center gap-1 text-emerald-500 text-[10px] font-medium"><CheckCircle2 className="w-3 h-3" />done</span>
  if (s.includes('cancel') || s.includes('declin'))
    return <span className="inline-flex items-center gap-1 text-red-400 text-[10px] font-medium"><XCircle className="w-3 h-3" />{s.slice(0, 10)}</span>
  return <span className="text-[10px] dark:text-white/45 text-gray-500">{s.slice(0, 12)}</span>
}

function TripTable({ trips }: { trips: TripRow[] }) {
  const [sortKey, setSortKey] = useState<TripSortKey>('trip_date')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [page, setPage] = useState(0)

  const handleSort = (col: TripSortKey) => {
    if (col === sortKey) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(col); setSortDir('asc') }
    setPage(0)
  }

  const sorted = useMemo(() => {
    return [...trips].sort((a, b) => {
      const va = (a[sortKey] ?? '') as string | boolean
      const vb = (b[sortKey] ?? '') as string | boolean
      const sa = typeof va === 'string' ? va.toLowerCase() : String(va)
      const sb = typeof vb === 'string' ? vb.toLowerCase() : String(vb)
      if (sa < sb) return sortDir === 'asc' ? -1 : 1
      if (sa > sb) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [trips, sortKey, sortDir])

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE)
  const pageSlice = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  if (trips.length === 0) {
    return (
      <p className="text-xs dark:text-white/30 text-gray-400 text-center py-4">
        No trips recorded for this week.
      </p>
    )
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px]">
          <thead>
            <tr className="border-b dark:border-white/6 border-gray-100">
              <SortTH col="trip_date" label="Date" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortTH col="source" label="Source" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <th className="text-left py-2 px-2 text-[10px] uppercase tracking-wider dark:text-white/25 text-gray-400 font-medium">Ref</th>
              <SortTH col="pickup_time" label="Pickup" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortTH col="status" label="Status" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortTH col="escalated" label="Esc" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
            </tr>
          </thead>
          <tbody className="divide-y dark:divide-white/[0.03] divide-gray-50">
            {pageSlice.map(trip => (
              <tr key={trip.id} className="hover:dark:bg-white/[0.015] hover:bg-gray-50 transition-colors">
                <td className="py-2 px-2 text-xs tabular-nums dark:text-white/55 text-gray-600 whitespace-nowrap">
                  {trip.trip_date
                    ? new Date(trip.trip_date + 'T00:00:00').toLocaleDateString([], { month: 'short', day: 'numeric' })
                    : '—'}
                </td>
                <td className="py-2 px-2">
                  <span className={cn(
                    'text-[10px] font-medium px-1.5 py-0.5 rounded',
                    trip.source === 'firstalt'
                      ? 'dark:bg-violet-500/15 bg-violet-50 dark:text-violet-300 text-violet-700'
                      : 'dark:bg-sky-500/15 bg-sky-50 dark:text-sky-300 text-sky-700'
                  )}>
                    {trip.source === 'firstalt' ? 'FA' : 'ED'}
                  </span>
                </td>
                <td className="py-2 px-2 text-[10px] font-mono dark:text-white/35 text-gray-400 max-w-[120px] truncate">
                  {trip.trip_ref}
                </td>
                <td className="py-2 px-2 text-xs tabular-nums dark:text-white/50 text-gray-600 whitespace-nowrap">
                  {trip.pickup_time ?? '—'}
                </td>
                <td className="py-2 px-2">
                  {statusPill(trip.status)}
                </td>
                <td className="py-2 px-2">
                  {trip.escalated
                    ? <span className="inline-flex items-center gap-1 text-[10px] text-amber-500 font-medium"><AlertCircle className="w-3 h-3" />yes</span>
                    : <span className="text-[10px] dark:text-white/15 text-gray-300">—</span>
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3 pt-3 border-t dark:border-white/6 border-gray-100">
          <span className="text-[10px] dark:text-white/25 text-gray-400">
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sorted.length)} of {sorted.length}
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-2 py-1 text-xs rounded dark:bg-white/5 bg-gray-100 dark:text-white/45 text-gray-500 disabled:opacity-30 hover:dark:bg-white/10 hover:bg-gray-200 transition-colors cursor-pointer disabled:cursor-default"
            >
              Prev
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page === totalPages - 1}
              className="px-2 py-1 text-xs rounded dark:bg-white/5 bg-gray-100 dark:text-white/45 text-gray-500 disabled:opacity-30 hover:dark:bg-white/10 hover:bg-gray-200 transition-colors cursor-pointer disabled:cursor-default"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function DrilldownSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-24 rounded-xl dark:bg-white/5 bg-gray-100" />
      <div className="h-36 rounded-xl dark:bg-white/5 bg-gray-100" />
      <div className="h-52 rounded-xl dark:bg-white/5 bg-gray-100" />
      <div className="h-44 rounded-xl dark:bg-white/5 bg-gray-100" />
    </div>
  )
}

// ─── Error state ──────────────────────────────────────────────────────────────

function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="rounded-xl dark:bg-red-500/[0.06] bg-red-50 border dark:border-red-500/25 border-red-200 p-6 flex flex-col items-center gap-3 text-center"
    >
      <div className="w-10 h-10 rounded-xl bg-red-500/10 flex items-center justify-center">
        <AlertCircle className="w-5 h-5 text-red-400" />
      </div>
      <p className="text-sm font-medium dark:text-white/80 text-gray-700">Failed to load driver data</p>
      <p className="text-xs dark:text-white/40 text-gray-500 max-w-sm">{message}</p>
      <button
        onClick={onRetry}
        className="px-4 py-2 rounded-lg text-sm font-medium bg-red-500/15 text-red-400 border border-red-500/25 hover:bg-red-500/25 transition-all cursor-pointer"
      >
        Retry
      </button>
    </motion.div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function DriverDrilldownPage() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const personId = params.personId as string
  const weekParam = searchParams.get('week')

  const [data, setData] = useState<DrilldownData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const qs = new URLSearchParams({ windows: '12' })
      if (weekParam) qs.set('week', weekParam)
      const result = await api.get<DrilldownData>(
        `/api/data/reliability/driver/${personId}?${qs.toString()}`
      )
      setData(result)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load driver data')
    } finally {
      setLoading(false)
    }
  }, [personId, weekParam])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleBack = () => router.push('/dispatch/reliability')

  if (loading) {
    return (
      <div className="p-4 sm:p-6 max-w-3xl mx-auto">
        <button onClick={handleBack} className="mb-5 inline-flex items-center gap-1.5 text-sm dark:text-white/50 text-gray-500 hover:dark:text-white/80 hover:text-gray-700 transition-colors cursor-pointer">
          <ArrowLeft className="w-4 h-4" />Back to reliability
        </button>
        <DrilldownSkeleton />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="p-4 sm:p-6 max-w-3xl mx-auto">
        <button onClick={handleBack} className="mb-5 inline-flex items-center gap-1.5 text-sm dark:text-white/50 text-gray-500 hover:dark:text-white/80 hover:text-gray-700 transition-colors cursor-pointer">
          <ArrowLeft className="w-4 h-4" />Back to reliability
        </button>
        <ErrorCard message={error ?? 'No data returned'} onRetry={fetchData} />
      </div>
    )
  }

  const { driver, current_week, weekly_history, trips_this_week } = data
  const axes = AXIS_DISPLAY_ORDER
    .filter(k => current_week.axes[k])
    .map(k => current_week.axes[k])

  return (
    <div className="p-4 sm:p-6 max-w-3xl mx-auto">
      {/* Back button */}
      <button
        onClick={handleBack}
        className="mb-5 inline-flex items-center gap-1.5 text-sm dark:text-white/50 text-gray-500 hover:dark:text-white/80 hover:text-gray-700 transition-colors cursor-pointer"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to reliability
      </button>

      <motion.div
        variants={staggerContainer}
        initial="initial"
        animate="animate"
        className="space-y-4"
      >
        {/* ── Hero: name + tier + revenue ────────────────────────────────── */}
        <motion.div variants={cardVariants} className="rounded-xl dark:bg-white/[0.03] bg-white border dark:border-white/8 border-gray-200 p-5">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl dark:bg-white/8 bg-gray-100 flex items-center justify-center flex-shrink-0">
              <User className="w-5 h-5 dark:text-white/40 text-gray-400" />
            </div>
            <div className="flex-1 min-w-0">
              <h1 className="text-base font-semibold dark:text-white text-gray-900 truncate">
                {driver.name}
              </h1>
              <div className="flex flex-wrap items-center gap-2 mt-1">
                <TierBadge tier={current_week.tier} label={current_week.tier_label} />
                {current_week.composite_score !== null && (
                  <span className="text-sm font-semibold tabular-nums dark:text-white/70 text-gray-700">
                    {current_week.composite_score.toFixed(1)} pts
                  </span>
                )}
                <DeltaBadge delta={current_week.wow_delta} />
              </div>
            </div>
          </div>

          {(driver.paycheck_code || driver.paycheck_code_maz) && (
            <div className="mt-4 pt-4 border-t dark:border-white/6 border-gray-100 flex flex-wrap gap-5">
              {driver.paycheck_code && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider dark:text-white/25 text-gray-400 font-medium">FA code</p>
                  <p className="text-xs font-mono dark:text-white/55 text-gray-600 mt-0.5">{driver.paycheck_code}</p>
                </div>
              )}
              {driver.paycheck_code_maz && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider dark:text-white/25 text-gray-400 font-medium">Maz code</p>
                  <p className="text-xs font-mono dark:text-white/55 text-gray-600 mt-0.5">{driver.paycheck_code_maz}</p>
                </div>
              )}
            </div>
          )}

          {current_week.total_trips > 0 && (
            <div className="mt-4 pt-4 border-t dark:border-white/6 border-gray-100">
              <div className="flex items-center gap-1.5 mb-1.5">
                <DollarSign className="w-3.5 h-3.5 dark:text-emerald-400/60 text-emerald-600/60" />
                <span className="text-[10px] uppercase tracking-wider dark:text-white/25 text-gray-400 font-medium">Margin contribution this week</span>
              </div>
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="text-xl font-bold tabular-nums dark:text-emerald-400 text-emerald-600">
                  ${current_week.revenue_impact.toFixed(2)}
                </span>
                <span className="text-xs dark:text-white/35 text-gray-500 tabular-nums">
                  ${current_week.revenue_impact_per_trip.toFixed(2)}/trip
                </span>
                {current_week.revenue_rank != null && (
                  <span className="text-xs dark:text-white/25 text-gray-400">Rank #{current_week.revenue_rank}</span>
                )}
              </div>
            </div>
          )}
        </motion.div>

        {/* ── 12-week trend chart ─────────────────────────────────────────── */}
        <motion.div variants={cardVariants} className="rounded-xl dark:bg-white/[0.03] bg-white border dark:border-white/8 border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold dark:text-white/80 text-gray-800">12-week trend</h2>
            <div className="hidden sm:flex items-center gap-3 text-[10px] dark:text-white/20 text-gray-400">
              <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-amber-400 inline-block" />≥90 gold</span>
              <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />≥80</span>
              <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-red-400 inline-block" />&lt;70</span>
            </div>
          </div>
          <TrendChart history={weekly_history} />

          {current_week.headline_metric && (
            <div className="mt-4 pt-4 border-t dark:border-white/6 border-gray-100 space-y-1.5">
              <p className="text-xs dark:text-white/60 text-gray-600">
                <span className="font-medium dark:text-white/80 text-gray-800">This week: </span>
                {current_week.headline_metric}
              </p>
              {current_week.focus_area && (
                <p className="text-xs dark:text-white/40 text-gray-500 italic leading-relaxed">{current_week.focus_area}</p>
              )}
            </div>
          )}
        </motion.div>

        {/* ── Score breakdown ─────────────────────────────────────────────── */}
        <motion.div variants={cardVariants} className="rounded-xl dark:bg-white/[0.03] bg-white border dark:border-white/8 border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold dark:text-white/80 text-gray-800">Score breakdown</h2>
            <span className="text-[10px] dark:text-white/20 text-gray-400">weight →</span>
          </div>

          {current_week.low_sample && (
            <div className="mb-3 flex items-start gap-2 text-xs dark:text-amber-400/80 text-amber-600 dark:bg-amber-500/8 bg-amber-50 rounded-lg px-3 py-2 border dark:border-amber-500/15 border-amber-200">
              <Info className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
              Low sample week — fewer than 3 trips, scores may not be representative.
            </div>
          )}

          <div className="flex items-center gap-3 pb-1 mb-1 border-b dark:border-white/6 border-gray-100">
            <span className="w-40 text-[10px] uppercase tracking-wider dark:text-white/20 text-gray-400 flex-shrink-0">Axis</span>
            <div className="flex-1" />
            <span className="w-14 text-right text-[10px] uppercase tracking-wider dark:text-white/20 text-gray-400">Score</span>
            <span className="w-10 text-right text-[10px] uppercase tracking-wider dark:text-white/20 text-gray-400">Wt</span>
          </div>

          <div className="divide-y dark:divide-white/[0.04] divide-gray-50">
            {axes.map((ax, i) => <AxisRow key={i} ax={ax} />)}
          </div>
        </motion.div>

        {/* ── Trips this week ─────────────────────────────────────────────── */}
        <motion.div variants={cardVariants} className="rounded-xl dark:bg-white/[0.03] bg-white border dark:border-white/8 border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Calendar className="w-4 h-4 dark:text-white/25 text-gray-400" />
              <h2 className="text-sm font-semibold dark:text-white/80 text-gray-800">Trips this week</h2>
            </div>
            {(trips_this_week?.length ?? 0) > 0 && (
              <span className="text-[10px] tabular-nums dark:text-white/25 text-gray-400">
                {trips_this_week.length} trip{trips_this_week.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <TripTable trips={trips_this_week ?? []} />
        </motion.div>
      </motion.div>
    </div>
  )
}
