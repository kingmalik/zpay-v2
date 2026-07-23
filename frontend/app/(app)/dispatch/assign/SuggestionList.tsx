'use client'

import { motion } from 'framer-motion'
import { MapPin, Repeat } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DriverSuggestion, CoverageDirectOption, TIER_STYLES, Tier } from './types'

// Accepts either the full suggestion shape (with score/familiar_rides/load_recent)
// or the lighter coverage "direct option" shape — score bar only renders when present.
type DriverCardData = DriverSuggestion | CoverageDirectOption

function hasScore(d: DriverCardData): d is DriverSuggestion {
  return typeof (d as DriverSuggestion).score === 'number'
}

export function TierChip({ tier }: { tier: Tier }) {
  const s = TIER_STYLES[tier] ?? TIER_STYLES.watch
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide', s.cls)}>
      <span className={cn('w-1.5 h-1.5 rounded-full', s.dot)} />
      {s.label}
    </span>
  )
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(score * 100)))
  return (
    <div className="flex items-center gap-2 w-full max-w-[140px]">
      <div className="flex-1 h-1.5 rounded-full dark:bg-white/8 bg-gray-100 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: 'linear-gradient(90deg, #667eea, #06b6d4)' }}
        />
      </div>
      <span className="text-[11px] tabular-nums dark:text-white/40 text-gray-400 w-8 text-right">{pct}%</span>
    </div>
  )
}

interface DriverCardProps {
  driver: DriverCardData
  index: number
  action?: React.ReactNode
  highlighted?: boolean
}

function DriverCard({ driver, index, action, highlighted }: DriverCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.03 }}
      className={cn(
        'rounded-2xl border p-3.5 space-y-2 transition-all',
        highlighted
          ? 'dark:bg-emerald-500/[0.06] bg-emerald-50 dark:border-emerald-500/20 border-emerald-200'
          : 'dark:bg-white/[0.02] bg-white dark:border-white/8 border-gray-200',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-semibold dark:text-white text-gray-900 truncate">{driver.name}</span>
          <TierChip tier={driver.tier} />
        </div>
        {action}
      </div>

      {hasScore(driver) && (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <ScoreBar score={driver.score} />
          <div className="flex items-center gap-3 text-[11px] dark:text-white/35 text-gray-400">
            {driver.familiar_rides > 0 && (
              <span className="flex items-center gap-1">
                <Repeat className="w-3 h-3" />
                driven this route {driver.familiar_rides}x
              </span>
            )}
            {driver.home_area && (
              <span className="flex items-center gap-1">
                <MapPin className="w-3 h-3" />
                {driver.home_area}
              </span>
            )}
          </div>
        </div>
      )}

      {driver.reasons.length > 0 && (
        <ul className="space-y-0.5">
          {driver.reasons.map((r, i) => (
            <li key={i} className="text-xs dark:text-white/55 text-gray-500 flex gap-1.5">
              <span className="dark:text-white/20 text-gray-300">·</span>
              {r}
            </li>
          ))}
        </ul>
      )}
    </motion.div>
  )
}

interface SuggestionListProps {
  drivers: DriverCardData[]
  emptyLabel?: string
  renderAction?: (driver: DriverCardData) => React.ReactNode
  highlightIds?: number[]
}

export default function SuggestionList({ drivers, emptyLabel, renderAction, highlightIds }: SuggestionListProps) {
  if (drivers.length === 0) {
    return (
      <div className="flex items-center justify-center py-6 rounded-xl dark:bg-white/[0.02] bg-gray-50 border dark:border-white/8 border-gray-200">
        <p className="text-xs dark:text-white/30 text-gray-400">{emptyLabel ?? 'No suggestions available'}</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {drivers.map((d, i) => (
        <DriverCard
          key={d.person_id}
          driver={d}
          index={i}
          action={renderAction?.(d)}
          highlighted={highlightIds?.includes(d.person_id)}
        />
      ))}
    </div>
  )
}
