'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { motion, type Variants } from 'framer-motion'

// ─── Types ────────────────────────────────────────────────────────────────────

interface DriverInfo {
  name: string
  tier: 'gold' | 'silver' | 'bronze' | 'probation' | 'no_activity' | string
  composite_score: number | null
}

interface CurrentWeek {
  week_label: string
  trips_completed: number
  driver_pay: number
  withheld: boolean
  withheld_amount: number
  carried_over: number
  paid_this_period: number
}

interface RecentWeek {
  week_label: string
  trips: number
  pay: number
  paid: boolean
}

interface PortalData {
  driver: DriverInfo
  current_week: CurrentWeek
  held_balance: number
  recent_weeks: RecentWeek[]
  scorecard_url: string
}

// ─── Tier config ──────────────────────────────────────────────────────────────

const TIER_CONFIG: Record<string, {
  label: string
  bg: string
  ring: string
  text: string
  dot: string
  badge: string
}> = {
  gold:        { label: 'Gold Driver',      bg: 'bg-amber-500/15',  ring: 'ring-amber-400/30',  text: 'text-amber-300',  dot: 'bg-amber-400',  badge: 'bg-amber-500/20 text-amber-300 ring-amber-400/30'  },
  silver:      { label: 'Silver Driver',    bg: 'bg-slate-500/15',  ring: 'ring-slate-400/30',  text: 'text-slate-300',  dot: 'bg-slate-400',  badge: 'bg-slate-500/20 text-slate-300 ring-slate-400/30'  },
  bronze:      { label: 'Bronze Driver',    bg: 'bg-orange-500/15', ring: 'ring-orange-400/30', text: 'text-orange-300', dot: 'bg-orange-400', badge: 'bg-orange-500/20 text-orange-300 ring-orange-400/30' },
  probation:   { label: 'Needs Improvement',bg: 'bg-red-500/15',    ring: 'ring-red-400/30',    text: 'text-red-300',    dot: 'bg-red-400',    badge: 'bg-red-500/20 text-red-300 ring-red-400/30'    },
  no_activity: { label: 'No activity',      bg: 'bg-white/5',       ring: 'ring-white/10',      text: 'text-white/40',   dot: 'bg-white/20',   badge: 'bg-white/5 text-white/40 ring-white/10'   },
}

const DEFAULT_TIER = TIER_CONFIG.no_activity

// ─── Animation variants ───────────────────────────────────────────────────────

const fadeUp: Variants = {
  initial: { opacity: 0, y: 18 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.38, ease: [0.16, 1, 0.3, 1] } },
}

const stagger: Variants = {
  initial: {},
  animate: { transition: { staggerChildren: 0.08 } },
}

// ─── Dollar formatter ─────────────────────────────────────────────────────────

function fmt(n: number): string {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })
}

// ─── Loading skeleton ─────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="min-h-screen bg-[#0d0f14] flex items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-4 animate-pulse">
        <div className="h-44 rounded-2xl bg-white/5" />
        <div className="h-28 rounded-2xl bg-white/5" />
        <div className="h-36 rounded-2xl bg-white/5" />
        <div className="h-40 rounded-2xl bg-white/5" />
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
          This link may have expired or the driver ID is incorrect.
        </p>
      </motion.div>
    </div>
  )
}

// ─── Pay card (hero) ──────────────────────────────────────────────────────────

function PayCard({ week, name }: { week: CurrentWeek; name: string }) {
  const hasData = week.trips_completed > 0 || week.driver_pay > 0

  return (
    <motion.div
      variants={fadeUp}
      className="rounded-2xl bg-[#111318] ring-1 ring-white/10 p-6 space-y-4"
    >
      {/* Week label */}
      <p className="text-xs font-semibold uppercase tracking-widest text-white/30">
        {week.week_label || 'Current Period'}
      </p>

      {/* Big pay number */}
      <div>
        <p className="text-5xl font-black tabular-nums text-white leading-none">
          {hasData ? fmt(week.paid_this_period) : '—'}
        </p>
        <p className="text-sm text-white/40 mt-2">
          {hasData
            ? `${week.trips_completed} trip${week.trips_completed === 1 ? '' : 's'} completed`
            : `No trips recorded yet, ${name}`}
        </p>
      </div>

      {/* Withheld banner */}
      {week.withheld && week.withheld_amount > 0 && (
        <div className="rounded-xl bg-amber-500/10 border border-amber-500/25 px-4 py-3 space-y-0.5">
          <p className="text-sm font-semibold text-amber-300">
            {fmt(week.withheld_amount)} is being held
          </p>
          <p className="text-xs text-amber-300/60 leading-relaxed">
            Your balance will be paid out once it reaches $100. Keep driving — it carries forward automatically.
          </p>
        </div>
      )}
    </motion.div>
  )
}

// ─── Held balance card ────────────────────────────────────────────────────────

function HeldBalanceCard({ amount }: { amount: number }) {
  if (amount <= 0) return null

  return (
    <motion.div
      variants={fadeUp}
      className="rounded-2xl bg-amber-500/8 ring-1 ring-amber-400/20 px-5 py-4 flex items-center gap-3"
    >
      <div className="w-9 h-9 rounded-xl bg-amber-500/20 flex items-center justify-center flex-shrink-0">
        <span className="text-amber-300 text-base">$</span>
      </div>
      <div>
        <p className="text-sm font-semibold text-amber-200">
          {fmt(amount)} waiting from prior weeks
        </p>
        <p className="text-xs text-amber-300/50 mt-0.5">
          Releases when your next paycheck clears $100.
        </p>
      </div>
    </motion.div>
  )
}

// ─── Tier badge card ──────────────────────────────────────────────────────────

function TierCard({
  tier,
  score,
  scorecardUrl,
}: {
  tier: string
  score: number | null
  scorecardUrl: string
}) {
  const router = useRouter()
  const cfg = TIER_CONFIG[tier] ?? DEFAULT_TIER

  return (
    <motion.div
      variants={fadeUp}
      onClick={() => router.push(scorecardUrl)}
      className={`rounded-2xl p-5 ring-1 cursor-pointer transition-opacity active:opacity-70 ${cfg.bg} ${cfg.ring} flex items-center justify-between gap-3`}
    >
      <div className="flex items-center gap-3">
        <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${cfg.dot}`} />
        <div>
          <p className={`text-sm font-semibold ${cfg.text}`}>{cfg.label}</p>
          {score !== null && (
            <p className="text-xs text-white/30 mt-0.5">Score {score.toFixed(0)} · Tap to see breakdown</p>
          )}
          {score === null && (
            <p className="text-xs text-white/30 mt-0.5">Tap to see scorecard</p>
          )}
        </div>
      </div>
      <svg
        className="w-4 h-4 text-white/20 flex-shrink-0"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        viewBox="0 0 24 24"
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
      </svg>
    </motion.div>
  )
}

// ─── Pay history table ────────────────────────────────────────────────────────

function PayHistory({ weeks }: { weeks: RecentWeek[] }) {
  if (weeks.length === 0) return null

  return (
    <motion.div
      variants={fadeUp}
      className="rounded-2xl bg-[#111318] ring-1 ring-white/8 p-5 space-y-3"
    >
      <h2 className="text-sm font-semibold text-white/50">Pay history</h2>

      <div className="divide-y divide-white/[0.05]">
        {/* Header row */}
        <div className="grid grid-cols-4 pb-2.5 gap-2">
          <span className="text-[11px] uppercase tracking-wide text-white/25">Week</span>
          <span className="text-[11px] uppercase tracking-wide text-white/25 text-center">Trips</span>
          <span className="text-[11px] uppercase tracking-wide text-white/25 text-right">Pay</span>
          <span className="text-[11px] uppercase tracking-wide text-white/25 text-right">Status</span>
        </div>

        {weeks.map((w, i) => (
          <div key={i} className="grid grid-cols-4 py-3 gap-2 items-center">
            <span className="text-sm text-white/70 truncate">{w.week_label}</span>
            <span className="text-sm text-white/50 text-center tabular-nums">{w.trips}</span>
            <span className="text-sm text-white/80 text-right tabular-nums font-medium">
              {fmt(w.pay)}
            </span>
            <div className="flex justify-end">
              {w.paid ? (
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-400">
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                    <path
                      fillRule="evenodd"
                      d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                      clipRule="evenodd"
                    />
                  </svg>
                  Paid
                </span>
              ) : (
                <span className="text-[11px] font-semibold text-amber-400">Held</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </motion.div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function DriverPortalPage() {
  const params = useParams()
  const personId = params.personId as string

  const [data, setData] = useState<PortalData | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setNotFound(false)
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/public/driver/${personId}/portal`,
        { cache: 'no-store' }
      )
      if (res.status === 404) {
        setNotFound(true)
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json: PortalData = await res.json()
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

  const { driver, current_week, held_balance, recent_weeks, scorecard_url } = data

  return (
    <>
      <title>{`${driver.name}'s Pay`}</title>
      <meta name="robots" content="noindex, nofollow" />
      <meta name="description" content={`${driver.name}'s pay summary`} />

      <div className="min-h-screen bg-[#0d0f14] text-white px-4 py-10 flex flex-col items-center">
        <motion.div
          variants={stagger}
          initial="initial"
          animate="animate"
          className="w-full max-w-sm space-y-3"
        >
          {/* Greeting */}
          <motion.p
            variants={fadeUp}
            className="text-xs font-semibold uppercase tracking-widest text-white/25 pb-1"
          >
            Hi, {driver.name}
          </motion.p>

          {/* Pay card (hero) */}
          <PayCard week={current_week} name={driver.name} />

          {/* Held balance (conditional) */}
          <HeldBalanceCard amount={held_balance} />

          {/* Tier badge — tappable to scorecard */}
          <TierCard
            tier={driver.tier}
            score={driver.composite_score}
            scorecardUrl={scorecard_url}
          />

          {/* Pay history */}
          <PayHistory weeks={recent_weeks} />

          {/* Footer */}
          <motion.p
            variants={fadeUp}
            className="text-center text-xs text-white/15 pt-2 pb-6"
          >
            Questions? Contact your dispatcher.
          </motion.p>
        </motion.div>
      </div>
    </>
  )
}
