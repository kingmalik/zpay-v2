'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import { motion, type Variants } from 'framer-motion'
import Head from 'next/head'

// ─── Types ────────────────────────────────────────────────────────────────────

interface PublicAxis {
  label: string
  value_pct: number | null
  available: boolean
  sample_size: number
}

interface TrendEntry {
  week_iso: string
  composite_score: number | null
  tier: string
}

interface PublicScorecardData {
  first_name: string
  tier: string
  tier_label: string
  composite_score: number | null
  low_sample: boolean
  axes: Record<string, PublicAxis>
  trend: TrendEntry[]
}

// ─── Tier config ──────────────────────────────────────────────────────────────

const TIER_CONFIG: Record<string, { label: string; bg: string; ring: string; text: string; dot: string }> = {
  gold:        { label: 'Tier 1', bg: 'bg-amber-500/20',  ring: 'ring-amber-400/40',  text: 'text-amber-300',  dot: 'bg-amber-400'  },
  silver:      { label: 'Tier 2', bg: 'bg-slate-500/20',  ring: 'ring-slate-400/40',  text: 'text-slate-300',  dot: 'bg-slate-400'  },
  bronze:      { label: 'Tier 3', bg: 'bg-orange-500/20', ring: 'ring-orange-400/40', text: 'text-orange-300', dot: 'bg-orange-400' },
  probation:   { label: 'Tier 4', bg: 'bg-red-500/20',    ring: 'ring-red-400/40',    text: 'text-red-300',    dot: 'bg-red-400'    },
  no_activity: { label: 'No activity', bg: 'bg-white/5',  ring: 'ring-white/10',      text: 'text-white/40',   dot: 'bg-white/20'   },
}

const DEFAULT_TIER = { label: '—', bg: 'bg-white/5', ring: 'ring-white/10', text: 'text-white/40', dot: 'bg-white/20' }

// Axis display order
const AXIS_ORDER = [
  'acceptance',
  'on_time_start',
  'on_time_pickup_arrival',
  'on_time_completion',
  'responsiveness',
  'reliability',
]

// ─── Animation variants ───────────────────────────────────────────────────────

const fadeUp: Variants = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] } },
}

const stagger: Variants = {
  initial: {},
  animate: { transition: { staggerChildren: 0.07 } },
}

// ─── Sparkline ────────────────────────────────────────────────────────────────

function Sparkline({ trend }: { trend: TrendEntry[] }) {
  const scores = trend.map(t => t.composite_score)
  const valid = scores.filter((v): v is number => v !== null)
  if (valid.length < 2) {
    return <div className="text-xs text-white/25 text-center py-3">Not enough data yet</div>
  }

  const min = Math.min(...valid, 50)
  const max = Math.max(...valid, 100)
  const range = max - min || 1
  const W = 260
  const H = 52
  const pad = 10

  const coords = trend.map((t, i) => ({
    x: pad + (i / (trend.length - 1)) * (W - pad * 2),
    y: t.composite_score !== null
      ? H - pad - ((t.composite_score - min) / range) * (H - pad * 2)
      : null,
    entry: t,
  }))

  const pathParts: string[] = []
  for (const c of coords) {
    if (c.y === null) continue
    pathParts.push(pathParts.length === 0 ? `M${c.x.toFixed(1)},${c.y.toFixed(1)}` : `L${c.x.toFixed(1)},${c.y.toFixed(1)}`)
  }

  // Trend direction: compare last 2 valid points
  const lastTwo = valid.slice(-2)
  const trendUp = lastTwo.length === 2 && lastTwo[1] >= lastTwo[0]
  const lineColor = trendUp ? 'rgb(52 211 153 / 0.8)' : 'rgb(148 163 184 / 0.5)'
  const dotColor  = trendUp ? 'rgb(52 211 153)'        : 'rgb(148 163 184 / 0.7)'

  return (
    <div className="flex flex-col gap-2">
      <svg width={W} height={H} className="overflow-visible w-full" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
        {pathParts.length > 0 && (
          <path
            d={pathParts.join(' ')}
            fill="none"
            stroke={lineColor}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
        {coords.map((c, i) =>
          c.y !== null ? (
            <circle
              key={i}
              cx={c.x}
              cy={c.y}
              r={i === coords.length - 1 ? 4.5 : 2.5}
              fill={i === coords.length - 1 ? dotColor : `${dotColor.replace(')', ' / 0.5)').replace('rgb(', 'rgb(')}`}
              stroke={i === coords.length - 1 ? dotColor.replace('0.8)', '0.3)') : 'none'}
              strokeWidth={i === coords.length - 1 ? 3 : 0}
            />
          ) : null
        )}
      </svg>
      {/* Week labels */}
      <div className="flex justify-between px-1">
        {trend.map((t, i) => {
          const wNum = t.week_iso.split('-W')[1] || t.week_iso.split('-')[1]?.replace('W', '')
          return (
            <span
              key={i}
              className={`text-[10px] tabular-nums ${i === trend.length - 1 ? 'text-white/50 font-medium' : 'text-white/20'}`}
            >
              W{wNum}
            </span>
          )
        })}
      </div>
    </div>
  )
}

// ─── Axis bar ─────────────────────────────────────────────────────────────────

function AxisBar({ ax, index }: { ax: PublicAxis; index: number }) {
  const pct = ax.value_pct ?? 0

  const barColor =
    pct >= 90 ? 'bg-emerald-400' :
    pct >= 80 ? 'bg-sky-400' :
    pct >= 70 ? 'bg-amber-400' :
    pct >= 60 ? 'bg-orange-400' :
    'bg-red-400'

  if (!ax.available) {
    return (
      <div className="flex items-center gap-3 py-2.5 opacity-30">
        <span className="flex-1 text-sm text-white/50 truncate">{ax.label}</span>
        <span className="text-xs text-white/20 w-10 text-right">N/A</span>
      </div>
    )
  }

  return (
    <motion.div
      variants={fadeUp}
      className="flex items-center gap-3 py-2.5"
    >
      <span className="w-36 text-sm text-white/70 truncate flex-shrink-0">{ax.label}</span>
      <div className="flex-1 h-2 rounded-full bg-white/8 overflow-hidden">
        <motion.div
          className={`h-full rounded-full ${barColor}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1], delay: 0.1 + index * 0.05 }}
        />
      </div>
      <span className="w-12 text-right text-sm font-medium tabular-nums text-white/80">
        {pct.toFixed(0)}%
      </span>
    </motion.div>
  )
}

// ─── Loading skeleton ─────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="min-h-screen bg-[#0d0f14] flex items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-4 animate-pulse">
        <div className="h-40 rounded-2xl bg-white/5" />
        <div className="h-56 rounded-2xl bg-white/5" />
        <div className="h-24 rounded-2xl bg-white/5" />
      </div>
    </div>
  )
}

// ─── Not found ────────────────────────────────────────────────────────────────

function NotFound() {
  return (
    <div className="min-h-screen bg-[#0d0f14] flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="text-center space-y-3"
      >
        <div className="w-14 h-14 rounded-2xl bg-white/5 flex items-center justify-center mx-auto text-2xl">
          ?
        </div>
        <p className="text-white/70 font-medium">Link not found</p>
        <p className="text-white/30 text-sm max-w-xs">
          This scorecard link may have expired or the driver ID is incorrect.
        </p>
      </motion.div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function PublicScorecardPage() {
  const params = useParams()
  const personId = params.personId as string

  const [data, setData] = useState<PublicScorecardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setNotFound(false)
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/public/driver/${personId}/scorecard`,
        { cache: 'no-store' }
      )
      if (res.status === 404) {
        setNotFound(true)
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json: PublicScorecardData = await res.json()
      setData(json)
    } catch {
      setNotFound(true)
    } finally {
      setLoading(false)
    }
  }, [personId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  if (loading) return <Skeleton />
  if (notFound || !data) return <NotFound />

  const tierCfg = TIER_CONFIG[data.tier] ?? DEFAULT_TIER
  const orderedAxes = AXIS_ORDER
    .filter(k => data.axes[k]?.available)
    .map(k => ({ key: k, ax: data.axes[k] }))

  const hasScore = data.composite_score !== null

  return (
    <>
      {/* SEO — noindex, personal links */}
      <title>{`${data.first_name}'s Scorecard`}</title>
      <meta name="robots" content="noindex, nofollow" />
      <meta name="description" content={`${data.first_name}'s driver reliability scorecard`} />

      <div className="min-h-screen bg-[#0d0f14] text-white px-4 py-10 flex flex-col items-center">
        <motion.div
          variants={stagger}
          initial="initial"
          animate="animate"
          className="w-full max-w-sm space-y-4"
        >
          {/* ── Hero card ──────────────────────────────────────────────────── */}
          <motion.div
            variants={fadeUp}
            className={`rounded-2xl p-6 ring-1 ${tierCfg.bg} ${tierCfg.ring} space-y-4`}
          >
            {/* Name + greeting */}
            <div>
              <p className="text-sm text-white/40 font-medium tracking-wide uppercase">Your scorecard</p>
              <h1 className="text-3xl font-bold text-white mt-1">{data.first_name}</h1>
            </div>

            {/* Score + tier */}
            <div className="flex items-end gap-4">
              <div>
                <p className="text-[11px] uppercase tracking-widest text-white/30 mb-1">Score</p>
                <p className={`text-5xl font-black tabular-nums leading-none ${tierCfg.text}`}>
                  {hasScore ? data.composite_score!.toFixed(0) : '—'}
                </p>
              </div>
              <div className="mb-1.5">
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${tierCfg.bg} ${tierCfg.ring} ${tierCfg.text}`}>
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${tierCfg.dot}`} />
                  {tierCfg.label}
                </span>
              </div>
            </div>

            {data.low_sample && (
              <p className="text-xs text-amber-300/70 bg-amber-500/10 rounded-lg px-3 py-2 border border-amber-500/20">
                Fewer than 3 trips this week — score updates as you complete more rides.
              </p>
            )}

            {!hasScore && (
              <p className="text-sm text-white/40 italic">No rides recorded this week yet.</p>
            )}
          </motion.div>

          {/* ── Score breakdown ────────────────────────────────────────────── */}
          {orderedAxes.length > 0 && (
            <motion.div
              variants={fadeUp}
              className="rounded-2xl bg-white/[0.04] ring-1 ring-white/8 p-5 space-y-1"
            >
              <h2 className="text-sm font-semibold text-white/60 mb-3">How you scored</h2>

              <motion.div variants={stagger} initial="initial" animate="animate" className="divide-y divide-white/[0.05]">
                {orderedAxes.map(({ key, ax }, i) => (
                  <AxisBar key={key} ax={ax} index={i} />
                ))}
              </motion.div>

              <p className="text-[11px] text-white/20 pt-3 leading-relaxed">
                Scores update weekly. Keep accepting rides on time to move up.
              </p>
            </motion.div>
          )}

          {/* ── 4-week trend ───────────────────────────────────────────────── */}
          <motion.div
            variants={fadeUp}
            className="rounded-2xl bg-white/[0.04] ring-1 ring-white/8 p-5"
          >
            <h2 className="text-sm font-semibold text-white/60 mb-4">Last 4 weeks</h2>
            <Sparkline trend={data.trend} />
          </motion.div>

          {/* ── Footer ────────────────────────────────────────────────────── */}
          <motion.p variants={fadeUp} className="text-center text-xs text-white/15 pb-6">
            Powered by Z-Pay
          </motion.p>
        </motion.div>
      </div>
    </>
  )
}
