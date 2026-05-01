'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, TrendingUp, TrendingDown, Minus, ChevronRight } from 'lucide-react'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import TierBadge from './TierBadge'
import type { ScorecardRow } from './types'

interface ReliabilityMobileCardProps {
  row: ScorecardRow
}

function AxisRow({ label, ax }: { label: string; ax: ScorecardRow['axes'][keyof ScorecardRow['axes']] }) {
  const isLow = ax.sample_size < 3
  return (
    <div className="flex justify-between py-1.5 border-b last:border-0 dark:border-white/[0.05] border-gray-50">
      <span className="text-xs dark:text-white/40 text-gray-400">{label}</span>
      <span className={cn('text-xs tabular-nums', isLow ? 'dark:text-white/35 text-gray-400' : 'dark:text-white/75 text-gray-700')}>
        {ax.available ? `${(ax.raw * 100).toFixed(1)}%${isLow ? ' *' : ''}` : '—'}
      </span>
    </div>
  )
}

export default function ReliabilityMobileCard({ row }: ReliabilityMobileCardProps) {
  const [open, setOpen] = useState(false)

  const delta = row.wow_delta
  const deltaColor = delta == null ? '' : delta > 0 ? 'text-emerald-400' : delta < 0 ? 'text-red-400' : 'dark:text-white/40 text-gray-400'
  const DeltaIcon = delta == null ? null : delta > 0 ? TrendingUp : delta < 0 ? TrendingDown : Minus

  return (
    <div className={cn(
      'rounded-xl border transition-colors',
      'dark:bg-white/[0.03] bg-white dark:border-white/[0.08] border-gray-200',
      row.low_sample && 'opacity-70'
    )}>
      {/* Card header — always visible */}
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between p-4 text-left cursor-pointer"
      >
        <div className="flex flex-col gap-1.5 min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium dark:text-white/90 text-gray-800 text-sm truncate">
              {row.driver_name}
            </span>
            {row.low_sample && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-gray-500/10 text-gray-400 border border-gray-500/20">
                low sample
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <TierBadge tier={row.tier} label={row.tier_label} />
            {row.composite_score != null && (
              <span className="text-xs dark:text-white/50 text-gray-500 tabular-nums">
                {(row.composite_score * 100).toFixed(1)} composite
              </span>
            )}
            {delta != null && DeltaIcon && (
              <span className={cn('inline-flex items-center gap-0.5 text-xs tabular-nums', deltaColor)}>
                <DeltaIcon className="w-3 h-3" />
                {delta > 0 ? '+' : ''}{delta.toFixed(1)}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0 ml-3">
          <span className="text-xs dark:text-white/40 text-gray-400 tabular-nums">
            {row.total_trips} trips
          </span>
          <motion.div
            animate={{ rotate: open ? 180 : 0 }}
            transition={{ duration: 0.15 }}
            className="dark:text-white/30 text-gray-300"
          >
            <ChevronDown className="w-4 h-4" />
          </motion.div>
        </div>
      </button>

      {/* Expanded axes */}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-0 border-t dark:border-white/[0.06] border-gray-100 pt-3">
              <AxisRow label="Acceptance"  ax={row.axes.acceptance_rate} />
              <AxisRow label="On-time start"    ax={row.axes.on_time_start} />
              <AxisRow label="Arrival"     ax={row.axes.on_time_arrival} />
              <AxisRow label="Completion"  ax={row.axes.on_time_completion} />
              <AxisRow label="Responsiveness" ax={row.axes.responsiveness} />
              <AxisRow label="Reliability" ax={row.axes.reliability} />

              {(row.headline_metric || row.focus_area) && (
                <div className="pt-3 mt-2 border-t dark:border-white/[0.05] border-gray-50 space-y-2">
                  {row.headline_metric && (
                    <div>
                      <p className="text-xs dark:text-white/30 text-gray-400 uppercase tracking-wide mb-0.5">Headline</p>
                      <p className="text-xs dark:text-white/70 text-gray-600">{row.headline_metric}</p>
                    </div>
                  )}
                  {row.focus_area && (
                    <div>
                      <p className="text-xs dark:text-white/30 text-gray-400 uppercase tracking-wide mb-0.5">Focus</p>
                      <p className="text-xs dark:text-white/70 text-gray-600">{row.focus_area}</p>
                    </div>
                  )}
                  <Link
                    href={`/dispatch/reliability/${row.person_id}`}
                    className="inline-flex items-center gap-1 text-xs text-[#667eea] hover:underline mt-1"
                  >
                    View 12-week trend <ChevronRight className="w-3 h-3" />
                  </Link>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
