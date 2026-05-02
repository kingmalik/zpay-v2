'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import { motion, type Variants } from 'framer-motion'

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

interface TokenScorecardData {
  first_name: string
  week_iso: string
  tier: string
  tier_label: string
  composite_score: number | null
  low_sample: boolean
  axes: Record<string, PublicAxis>
  trend: TrendEntry[]
  focus_area: string | null
}

type PageState =
  | { status: 'loading' }
  | { status: 'ok'; data: TokenScorecardData }
  | { status: 'expired' }
  | { status: 'invalid' }
  | { status: 'not_found' }
  | { status: 'error' }

// ─── Tier config ──────────────────────────────────────────────────────────────

const TIER_CONFIG: Record<string, {
  label: string
  bg: string
  ring: string
  text: string
  dot: string
  glow: string
}> = {
  gold:        { label: 'Tier 1', bg: 'bg-amber-500/15',  ring: 'ring-amber-400/30',  text: 'text-amber-300',  dot: 'bg-amber-400',  glow: 'shadow-amber-500/20'  },
  silver:      { label: 'Tier 2', bg: 'bg-slate-500/15',  ring: 'ring-slate-400/30',  text: 'text-slate-300',  dot: 'bg-slate-400',  glow: 'shadow-slate-500/20'  },
  bronze:      { label: 'Tier 3', bg: 'bg-orange-500/15', ring: 'ring-orange-400/30', text: 'text-orange-300', dot: 'bg-orange-400', glow: 'shadow-orange-500/20' },
  probation:   { label: 'Tier 4', bg: 'bg-red-500/15',    ring: 'ring-red-400/30',    text: 'text-red-300',    dot: 'bg-red-400',    glow: 'shadow-red-500/20'    },
  no_activity: { label: 'No activity', bg: 'bg-white/5', ring: 'ring-white/10', text: 'text-white/35', dot: 'bg-white/20', glow: '' },
}

const DEFAULT_TIER = {
  label: '—',
  bg: 'bg-white/5',
  ring: 'ring-white/10',
  text: 'text-white/35',
  dot: 'bg-white/20',
  glow: '',
}

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
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] } },
}

const stagger: Variants = {
  initial: {},
  animate: { transition: { staggerChildren: 0.08 } },
}

const scaleIn: Variants = {
  initial: { opacity: 0, scale: 0.92 },
  animate: { opacity: 1, scale: 1, transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] } },
}

// ─── Sparkline ────────────────────────────────────────────────────────────────

function Sparkline({ trend }: { trend: TrendEntry[] }) {
  const scores = trend.map(t => t.composite_score)
  const valid = scores.filter((v): v is number => v !== null)

  if (valid.length < 2) {
    return (
      <p className="text-xs text-white/25 text-center py-4 italic">
        Not enough history yet — check back after a few weeks of rides.
      </p>
    )
  }

  const min = Math.min(...valid, 50)
  const max = Math.max(...valid, 100)
  const range = max - min || 1
  const W = 280
  const H = 56
  const pad = 12

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
    pathParts.push(
      pathParts.length === 0
        ? `M${c.x.toFixed(1)},${c.y.toFixed(1)}`
        : `L${c.x.toFixed(1)},${c.y.toFixed(1)}`
    )
  }

  const lastTwo = valid.slice(-2)
  const trendUp = lastTwo.length === 2 && lastTwo[1] >= lastTwo[0]
  const lineColor = trendUp ? 'rgb(52 211 153 / 0.75)' : 'rgb(148 163 184 / 0.45)'
  const dotColor  = trendUp ? 'rgb(52 211 153)'        : 'rgb(148 163 184 / 0.65)'

  return (
    <div className="space-y-2">
      <svg
        width={W}
        height={H}
        className="w-full overflow-visible"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        aria-hidden="true"
      >
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
              r={i === coords.length - 1 ? 5 : 2.5}
              fill={i === coords.length - 1 ? dotColor : `${dotColor.replace(')', ' / 0.45)').replace('rgb(', 'rgb(')}`}
              stroke={i === coords.length - 1 ? 'rgb(255 255 255 / 0.15)' : 'none'}
              strokeWidth={i === coords.length - 1 ? 3 : 0}
            />
          ) : null
        )}
      </svg>
      <div className="flex justify-between px-1">
        {trend.map((t, i) => {
          const wNum = t.week_iso.split('-W')[1] ?? ''
          return (
            <span
              key={i}
              className={`text-[10px] tabular-nums ${
                i === trend.length - 1 ? 'text-white/45 font-medium' : 'text-white/18'
              }`}
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
      <div className="flex items-center gap-3 py-2.5 opacity-25">
        <span className="flex-1 text-sm text-white/40 truncate">{ax.label}</span>
        <span className="text-xs text-white/20 w-10 text-right">N/A</span>
      </div>
    )
  }

  return (
    <motion.div variants={fadeUp} className="flex items-center gap-3 py-2.5">
      <span className="w-[140px] text-sm text-white/65 truncate flex-shrink-0">
        {ax.label}
      </span>
      <div className="flex-1 h-1.5 rounded-full bg-white/[0.07] overflow-hidden">
        <motion.div
          className={`h-full rounded-full ${barColor}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{
            duration: 0.6,
            ease: [0.16, 1, 0.3, 1],
            delay: 0.15 + index * 0.06,
          }}
        />
      </div>
      <span className="w-11 text-right text-sm font-semibold tabular-nums text-white/75">
        {pct.toFixed(0)}%
      </span>
    </motion.div>
  )
}

// ─── Score ring ───────────────────────────────────────────────────────────────

function ScoreRing({
  score,
  tierText,
}: {
  score: number | null
  tierText: string
}) {
  const pct = score ?? 0
  const radius = 42
  const circ = 2 * Math.PI * radius
  const dashOffset = circ - (pct / 100) * circ

  const ringColor =
    pct >= 90 ? '#fbbf24' :  // amber
    pct >= 80 ? '#94a3b8' :  // slate
    pct >= 70 ? '#fb923c' :  // orange
    pct >= 60 ? '#f87171' :  // red-400
    '#6b7280'                // gray

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width="100" height="100" className="-rotate-90" aria-hidden="true">
        <circle
          cx="50" cy="50" r={radius}
          fill="none"
          stroke="rgb(255 255 255 / 0.06)"
          strokeWidth="7"
        />
        <motion.circle
          cx="50" cy="50" r={radius}
          fill="none"
          stroke={ringColor}
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={circ}
          initial={{ strokeDashoffset: circ }}
          animate={{ strokeDashoffset: dashOffset }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1], delay: 0.2 }}
        />
      </svg>
      <div className="absolute flex flex-col items-center leading-none">
        <span
          className="text-2xl font-black tabular-nums"
          style={{ color: ringColor }}
        >
          {score !== null ? score.toFixed(0) : '—'}
        </span>
        <span className="text-[10px] text-white/35 mt-0.5 font-medium">{tierText}</span>
      </div>
    </div>
  )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="min-h-screen bg-[#0d0f14] flex items-center justify-center p-5">
      <div className="w-full max-w-sm space-y-3 animate-pulse">
        <div className="h-44 rounded-2xl bg-white/[0.04]" />
        <div className="h-64 rounded-2xl bg-white/[0.04]" />
        <div className="h-28 rounded-2xl bg-white/[0.04]" />
      </div>
    </div>
  )
}

// ─── Error states ─────────────────────────────────────────────────────────────

function ErrorState({ state }: { state: PageState }) {
  const configs = {
    expired: {
      icon: '🔒',
      title: 'Link expired',
      body: 'Scorecard links are valid for 14 days. Your next weekly link will arrive Sunday evening.',
    },
    invalid: {
      icon: '?',
      title: 'Link not recognized',
      body: 'This scorecard link may be incomplete or corrupted. Try opening it again from your text message.',
    },
    not_found: {
      icon: '?',
      title: 'Driver not found',
      body: 'This link may be from a previous account. Contact dispatch if you think this is an error.',
    },
    error: {
      icon: '!',
      title: 'Something went wrong',
      body: 'Unable to load your scorecard right now. Try again in a few minutes.',
    },
  } as const

  if (state.status === 'loading' || state.status === 'ok') return null
  const cfg = configs[state.status] ?? configs.error

  return (
    <div className="min-h-screen bg-[#0d0f14] flex items-center justify-center p-5">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        className="text-center space-y-4 max-w-xs"
      >
        <div className="w-16 h-16 rounded-2xl bg-white/[0.05] ring-1 ring-white/10 flex items-center justify-center mx-auto text-2xl select-none">
          {cfg.icon}
        </div>
        <div className="space-y-1.5">
          <p className="text-white/80 font-semibold">{cfg.title}</p>
          <p className="text-white/35 text-sm leading-relaxed">{cfg.body}</p>
        </div>
      </motion.div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function TokenScorecardPage() {
  const params = useParams()
  const token = params.token as string

  const [state, setState] = useState<PageState>({ status: 'loading' })

  const fetchScorecard = useCallback(async () => {
    setState({ status: 'loading' })
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/public/scorecard/${token}`,
        { cache: 'no-store' }
      )

      if (res.status === 404) {
        setState({ status: 'not_found' })
        return
      }
      if (res.status === 422) {
        const body = await res.json().catch(() => ({}))
        const msg = (body?.error ?? '').toLowerCase()
        setState({ status: msg.includes('expired') ? 'expired' : 'invalid' })
        return
      }
      if (!res.ok) {
        setState({ status: 'error' })
        return
      }

      const data: TokenScorecardData = await res.json()
      setState({ status: 'ok', data })
    } catch {
      setState({ status: 'error' })
    }
  }, [token])

  useEffect(() => {
    if (token) fetchScorecard()
  }, [fetchScorecard, token])

  if (state.status === 'loading') return <Skeleton />
  if (state.status !== 'ok') return <ErrorState state={state} />

  const { data } = state
  const tierCfg = TIER_CONFIG[data.tier] ?? DEFAULT_TIER

  const orderedAxes = AXIS_ORDER
    .filter(k => data.axes[k]?.available)
    .map(k => ({ key: k, ax: data.axes[k] }))

  const hasScore = data.composite_score !== null
  const weekNum = data.week_iso.split('-W')[1] ?? ''

  return (
    <>
      <title>{`${data.first_name}'s Scorecard — Week ${weekNum}`}</title>
      <meta name="robots" content="noindex, nofollow" />
      <meta
        name="description"
        content={`${data.first_name}'s driver reliability scorecard for Week ${weekNum}`}
      />

      <div className="min-h-screen bg-[#0d0f14] text-white px-4 py-10 flex flex-col items-center">
        <motion.div
          variants={stagger}
          initial="initial"
          animate="animate"
          className="w-full max-w-sm space-y-3"
        >
          {/* ── Hero card ──────────────────────────────────────────────────── */}
          <motion.div
            variants={scaleIn}
            className={`rounded-2xl p-6 ring-1 shadow-xl ${tierCfg.bg} ${tierCfg.ring} ${tierCfg.glow}`}
          >
            {/* Header row */}
            <div className="flex items-start justify-between mb-5">
              <div>
                <p className="text-[11px] font-semibold tracking-widest uppercase text-white/30 mb-0.5">
                  Your scorecard
                </p>
                <h1 className="text-2xl font-bold text-white leading-tight">
                  {data.first_name}
                </h1>
                <p className="text-xs text-white/25 mt-0.5">Week {weekNum}</p>
              </div>
              <ScoreRing score={data.composite_score} tierText={tierCfg.label} />
            </div>

            {/* Tier badge */}
            <div className="flex items-center gap-2">
              <span
                className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold ring-1 ${tierCfg.bg} ${tierCfg.ring} ${tierCfg.text}`}
              >
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${tierCfg.dot}`} />
                {tierCfg.label}
              </span>
              {data.low_sample && (
                <span className="text-[11px] text-amber-300/60">
                  Low sample
                </span>
              )}
            </div>

            {/* Low sample note */}
            {data.low_sample && (
              <p className="mt-3 text-xs text-amber-300/65 bg-amber-500/8 rounded-xl px-3 py-2 ring-1 ring-amber-500/15 leading-relaxed">
                Fewer than 3 trips this week — your score updates as you complete more rides.
              </p>
            )}

            {!hasScore && (
              <p className="mt-3 text-sm text-white/35 italic">
                No rides recorded for this week yet.
              </p>
            )}
          </motion.div>

          {/* ── Score breakdown ────────────────────────────────────────────── */}
          {orderedAxes.length > 0 && (
            <motion.div
              variants={fadeUp}
              className="rounded-2xl bg-white/[0.035] ring-1 ring-white/[0.07] p-5"
            >
              <h2 className="text-xs font-semibold uppercase tracking-widest text-white/40 mb-4">
                How you scored
              </h2>
              <motion.div
                variants={stagger}
                initial="initial"
                animate="animate"
                className="divide-y divide-white/[0.045]"
              >
                {orderedAxes.map(({ key, ax }, i) => (
                  <AxisBar key={key} ax={ax} index={i} />
                ))}
              </motion.div>
              <p className="text-[10px] text-white/20 pt-3 leading-relaxed">
                Scores update weekly. Accepting rides on time and staying responsive moves you up.
              </p>
            </motion.div>
          )}

          {/* ── Coaching message ───────────────────────────────────────────── */}
          {data.focus_area && (
            <motion.div
              variants={fadeUp}
              className="rounded-2xl bg-sky-500/8 ring-1 ring-sky-500/15 p-5 space-y-1"
            >
              <p className="text-[11px] font-semibold uppercase tracking-widest text-sky-400/60">
                Focus area
              </p>
              <p className="text-sm text-white/65 leading-relaxed">{data.focus_area}</p>
            </motion.div>
          )}

          {/* ── 4-week trend ───────────────────────────────────────────────── */}
          <motion.div
            variants={fadeUp}
            className="rounded-2xl bg-white/[0.035] ring-1 ring-white/[0.07] p-5"
          >
            <h2 className="text-xs font-semibold uppercase tracking-widest text-white/40 mb-4">
              Last 5 weeks
            </h2>
            <Sparkline trend={data.trend} />
          </motion.div>

          {/* ── Footer ────────────────────────────────────────────────────── */}
          <motion.p
            variants={fadeUp}
            className="text-center text-[11px] text-white/12 pb-6 tracking-wide"
          >
            Powered by Z-Pay
          </motion.p>
        </motion.div>
      </div>
    </>
  )
}
