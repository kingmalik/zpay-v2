'use client'

import { useState, useEffect, useCallback } from 'react'
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
  }
  weekly_history: WeekHistoryEntry[]
  recent_events: RecentEvent[]
}

// ─── Page entry animation ─────────────────────────────────────────────────────

const staggerContainer: Variants = {
  initial: {},
  animate: { transition: { staggerChildren: 0.06 } },
}

const cardVariants: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.2 } },
}

// ─── Axis ordering for display ────────────────────────────────────────────────

const AXIS_DISPLAY_ORDER = [
  'acceptance',
  'on_time_start',
  'on_time_pickup_arrival',
  'on_time_completion',
  'responsiveness',
  'reliability',
]

// ─── Sparkline ────────────────────────────────────────────────────────────────

function Sparkline({ history }: { history: WeekHistoryEntry[] }) {
  const points = history.map(h => h.composite_score)
  const valid = points.filter((v): v is number => v !== null)
  if (valid.length === 0) {
    return (
      <div className="flex items-center justify-center h-12 dark:text-white/25 text-gray-400 text-xs">
        No data
      </div>
    )
  }

  const min = Math.min(...valid, 50)
  const max = Math.max(...valid, 100)
  const range = max - min || 1
  const W = 180
  const H = 44
  const pad = 8

  const coords = history.map((h, i) => {
    const x = pad + (i / (history.length - 1)) * (W - pad * 2)
    const y = h.composite_score !== null
      ? H - pad - ((h.composite_score - min) / range) * (H - pad * 2)
      : null
    return { x, y, entry: h }
  })

  const pathParts: string[] = []
  let lastValid: { x: number; y: number } | null = null
  for (const c of coords) {
    if (c.y === null) continue
    if (!lastValid) pathParts.push(`M${c.x.toFixed(1)},${c.y.toFixed(1)}`)
    else pathParts.push(`L${c.x.toFixed(1)},${c.y.toFixed(1)}`)
    lastValid = { x: c.x, y: c.y }
  }

  const currentEntry = history[history.length - 1]
  const currentCoord = coords[coords.length - 1]

  return (
    <div className="flex flex-col gap-1">
      <svg width={W} height={H} className="overflow-visible">
        {pathParts.length > 0 && (
          <path
            d={pathParts.join(' ')}
            fill="none"
            stroke="rgb(102 126 234 / 0.7)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
        {coords.map((c, i) => c.y !== null && (
          <circle
            key={i}
            cx={c.x}
            cy={c.y}
            r={i === coords.length - 1 ? 4 : 2.5}
            fill={i === coords.length - 1 ? 'rgb(102 126 234)' : 'rgb(102 126 234 / 0.5)'}
            stroke={i === coords.length - 1 ? 'rgb(102 126 234 / 0.3)' : 'none'}
            strokeWidth={i === coords.length - 1 ? 3 : 0}
          />
        ))}
      </svg>
      <div className="flex justify-between text-[10px] dark:text-white/30 text-gray-400 tabular-nums">
        {history.map((h, i) => (
          <span key={i} className={cn(i === history.length - 1 && 'dark:text-white/60 text-gray-600 font-medium')}>
            W{h.week_iso.split('-W')[1]}
          </span>
        ))}
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
      {sign}{delta.toFixed(1)} pts vs last week
    </span>
  )
}

// ─── Axis bar row ─────────────────────────────────────────────────────────────

function AxisRow({ axisKey, ax }: { axisKey: string; ax: AxisData }) {
  if (!ax.available) {
    return (
      <div className="flex items-center gap-3 py-2 opacity-40">
        <span className="w-40 text-xs dark:text-white/60 text-gray-600 truncate flex-shrink-0">{ax.label}</span>
        <div className="flex-1 h-1.5 rounded-full dark:bg-white/5 bg-gray-100" />
        <span className="w-16 text-right text-xs dark:text-white/30 text-gray-400">N/A</span>
        <span className="w-12 text-right text-xs dark:text-white/20 text-gray-300 tabular-nums">
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
        'w-16 text-right text-xs tabular-nums font-medium',
        isLow ? 'dark:text-white/35 text-gray-400' : 'dark:text-white/80 text-gray-700'
      )}>
        {rawPct.toFixed(1)}%
        {isLow && (
          <span title={`Low sample (${ax.sample_size} trips)`} className="inline-block">
            <Info className="inline w-2.5 h-2.5 ml-0.5 -mt-0.5 dark:text-white/25 text-gray-300" />
          </span>
        )}
      </span>
      <span className="w-12 text-right text-xs dark:text-white/30 text-gray-400 tabular-nums">
        {Math.round(ax.nominal_weight * 100)}%
      </span>
    </div>
  )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function DrilldownSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-20 rounded-xl dark:bg-white/5 bg-gray-100" />
      <div className="h-40 rounded-xl dark:bg-white/5 bg-gray-100" />
      <div className="h-56 rounded-xl dark:bg-white/5 bg-gray-100" />
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
      <div>
        <p className="text-sm font-medium dark:text-white/80 text-gray-700 mb-1">Failed to load driver data</p>
        <p className="text-xs dark:text-white/40 text-gray-500 max-w-sm">{message}</p>
      </div>
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
      const qs = weekParam ? `?week=${encodeURIComponent(weekParam)}` : ''
      const result = await api.get<DrilldownData>(
        `/api/data/reliability/driver/${personId}${qs}`
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

  // ── Loading ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <button
          onClick={handleBack}
          className="mb-5 inline-flex items-center gap-1.5 text-sm dark:text-white/50 text-gray-500 hover:dark:text-white/80 hover:text-gray-700 transition-colors cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to reliability
        </button>
        <DrilldownSkeleton />
      </div>
    )
  }

  // ── Error ──────────────────────────────────────────────────────────────────

  if (error || !data) {
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <button
          onClick={handleBack}
          className="mb-5 inline-flex items-center gap-1.5 text-sm dark:text-white/50 text-gray-500 hover:dark:text-white/80 hover:text-gray-700 transition-colors cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to reliability
        </button>
        <ErrorCard message={error ?? 'No data returned'} onRetry={fetchData} />
      </div>
    )
  }

  const { driver, current_week, weekly_history, recent_events } = data
  const axes = AXIS_DISPLAY_ORDER
    .filter(k => current_week.axes[k])
    .map(k => ({ key: k, ax: current_week.axes[k] }))

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="p-6 max-w-3xl mx-auto">
      {/* Back */}
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
        {/* ── Hero card: name + tier + sparkline ─────────────────────────── */}
        <motion.div
          variants={cardVariants}
          className="rounded-xl dark:bg-white/[0.03] bg-white border dark:border-white/8 border-gray-200 p-5"
        >
          <div className="flex flex-col sm:flex-row sm:items-start gap-4">
            {/* Avatar + name */}
            <div className="flex items-center gap-3 flex-1 min-w-0">
              <div className="w-10 h-10 rounded-xl dark:bg-white/8 bg-gray-100 flex items-center justify-center flex-shrink-0">
                <User className="w-5 h-5 dark:text-white/40 text-gray-400" />
              </div>
              <div className="min-w-0">
                <h1 className="text-base font-semibold dark:text-white text-gray-900 truncate">
                  {driver.name}
                </h1>
                <div className="flex flex-wrap items-center gap-2 mt-0.5">
                  <TierBadge tier={current_week.tier} label={current_week.tier_label} />
                  {current_week.composite_score !== null && (
                    <span className="text-sm font-medium tabular-nums dark:text-white/60 text-gray-600">
                      {current_week.composite_score.toFixed(1)} pts
                    </span>
                  )}
                  <DeltaBadge delta={current_week.wow_delta} />
                </div>
              </div>
            </div>

            {/* Sparkline */}
            <div className="flex-shrink-0">
              <p className="text-[10px] uppercase tracking-wider dark:text-white/30 text-gray-400 mb-2 font-medium">
                4-week trend
              </p>
              <Sparkline history={weekly_history} />
            </div>
          </div>

          {/* Paycheck codes */}
          {(driver.paycheck_code || driver.paycheck_code_maz) && (
            <div className="mt-4 pt-4 border-t dark:border-white/6 border-gray-100 flex flex-wrap gap-4">
              {driver.paycheck_code && (
                <div>
                  <span className="text-[10px] uppercase tracking-wider dark:text-white/30 text-gray-400 font-medium">FA code</span>
                  <p className="text-xs font-mono dark:text-white/60 text-gray-600 mt-0.5">{driver.paycheck_code}</p>
                </div>
              )}
              {driver.paycheck_code_maz && (
                <div>
                  <span className="text-[10px] uppercase tracking-wider dark:text-white/30 text-gray-400 font-medium">Maz code</span>
                  <p className="text-xs font-mono dark:text-white/60 text-gray-600 mt-0.5">{driver.paycheck_code_maz}</p>
                </div>
              )}
            </div>
          )}
        </motion.div>

        {/* ── Score breakdown ─────────────────────────────────────────────── */}
        <motion.div
          variants={cardVariants}
          className="rounded-xl dark:bg-white/[0.03] bg-white border dark:border-white/8 border-gray-200 p-5"
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold dark:text-white/80 text-gray-800">
              Score breakdown
            </h2>
            <div className="flex items-center gap-2 text-[10px] dark:text-white/30 text-gray-400">
              <span className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-[#667eea]/60" />
                raw score
              </span>
              <span className="ml-2">weight →</span>
            </div>
          </div>

          {current_week.low_sample && (
            <div className="mb-4 flex items-start gap-2 text-xs dark:text-amber-400/80 text-amber-600 dark:bg-amber-500/8 bg-amber-50 rounded-lg px-3 py-2 border dark:border-amber-500/15 border-amber-200">
              <Info className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
              <span>Low sample week — fewer than 3 trips, scores may not be representative.</span>
            </div>
          )}

          {/* Column headers */}
          <div className="flex items-center gap-3 pb-1 mb-1 border-b dark:border-white/6 border-gray-100">
            <span className="w-40 text-[10px] uppercase tracking-wider dark:text-white/25 text-gray-400 flex-shrink-0">Axis</span>
            <div className="flex-1" />
            <span className="w-16 text-right text-[10px] uppercase tracking-wider dark:text-white/25 text-gray-400">Score</span>
            <span className="w-12 text-right text-[10px] uppercase tracking-wider dark:text-white/25 text-gray-400">Weight</span>
          </div>

          <div className="divide-y dark:divide-white/[0.04] divide-gray-50">
            {axes.map(({ key, ax }) => (
              <AxisRow key={key} axisKey={key} ax={ax} />
            ))}
          </div>

          {/* Headline / focus */}
          {current_week.headline_metric && (
            <div className="mt-4 pt-4 border-t dark:border-white/6 border-gray-100 space-y-2">
              <p className="text-xs dark:text-white/60 text-gray-600">
                <span className="font-medium dark:text-white/80 text-gray-800">This week: </span>
                {current_week.headline_metric}
              </p>
              {current_week.focus_area && (
                <p className="text-xs dark:text-white/45 text-gray-500 italic">
                  {current_week.focus_area}
                </p>
              )}
            </div>
          )}
        </motion.div>

        {/* ── Recent events ───────────────────────────────────────────────── */}
        <motion.div
          variants={cardVariants}
          className="rounded-xl dark:bg-white/[0.03] bg-white border dark:border-white/8 border-gray-200 p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <Calendar className="w-4 h-4 dark:text-white/30 text-gray-400" />
            <h2 className="text-sm font-semibold dark:text-white/80 text-gray-800">
              Recent events
            </h2>
          </div>

          {recent_events.length === 0 ? (
            <p className="text-xs dark:text-white/30 text-gray-400 text-center py-4">
              No events recorded yet.
              {/* TODO: events when override table lands */}
            </p>
          ) : (
            <ul className="space-y-2">
              {recent_events.slice(0, 20).map((ev, i) => (
                <li key={i} className="flex items-start gap-2 text-xs">
                  <span className="dark:text-white/30 text-gray-400 tabular-nums flex-shrink-0">
                    {new Date(ev.ts).toLocaleDateString()}
                  </span>
                  <span className="dark:text-white/60 text-gray-600">{ev.description}</span>
                </li>
              ))}
            </ul>
          )}
        </motion.div>
      </motion.div>
    </div>
  )
}
