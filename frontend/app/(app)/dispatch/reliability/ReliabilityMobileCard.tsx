'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronRight, AlertTriangle, CheckCircle2 } from 'lucide-react'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import type { ScorecardRow } from './types'

interface ReliabilityMobileCardProps {
  row: ScorecardRow
}

export default function ReliabilityMobileCard({ row }: ReliabilityMobileCardProps) {
  const [open, setOpen] = useState(false)

  const escalations = row.escalation_count ?? 0
  const selfServe = row.self_serve_pct
  const onTimeAx = row.axes?.on_time_pickup_arrival

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
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-500/10 text-gray-400 border border-gray-500/20">
                &lt;5 trips
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 text-xs">
            {/* Escalation count */}
            {escalations === 0 ? (
              <span className="inline-flex items-center gap-1 text-emerald-400">
                <CheckCircle2 className="w-3 h-3" />
                0 escalations
              </span>
            ) : (
              <span className={cn(
                'inline-flex items-center gap-1 font-medium',
                escalations >= 4 ? 'text-red-400' : escalations >= 2 ? 'text-orange-400' : 'text-amber-400'
              )}>
                <AlertTriangle className="w-3 h-3" />
                {escalations} escalation{escalations !== 1 ? 's' : ''}
              </span>
            )}
            {/* Self-serve % */}
            {selfServe != null && (
              <span className="dark:text-white/40 text-gray-400 tabular-nums">
                {selfServe.toFixed(0)}% self-serve
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

      {/* Expanded detail */}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 border-t dark:border-white/[0.06] border-gray-100 pt-3 space-y-2">
              {/* On-time arrival */}
              {onTimeAx?.available && (
                <div className="flex justify-between py-1">
                  <span className="text-xs dark:text-white/40 text-gray-400">On-time arrival</span>
                  <span className="text-xs dark:text-white/70 text-gray-600 tabular-nums">
                    {(onTimeAx.raw * 100).toFixed(0)}%
                  </span>
                </div>
              )}
              {/* Composite */}
              {row.composite_score != null && (
                <div className="flex justify-between py-1">
                  <span className="text-xs dark:text-white/40 text-gray-400">Score</span>
                  <span className="text-xs dark:text-white/70 text-gray-600 tabular-nums">
                    {row.composite_score.toFixed(0)}/100
                  </span>
                </div>
              )}

              {/* Coaching note / focus */}
              {row.focus_area && (
                <div className="pt-2 border-t dark:border-white/[0.05] border-gray-50">
                  <p className="text-xs dark:text-white/30 text-gray-400 uppercase tracking-wide mb-1">Tip</p>
                  <p className="text-xs dark:text-white/60 text-gray-500 leading-relaxed">{row.focus_area}</p>
                </div>
              )}

              <Link
                href={`/dispatch/reliability/${row.person_id}`}
                className="inline-flex items-center gap-1 text-xs text-[#667eea] hover:underline mt-1"
              >
                Full history <ChevronRight className="w-3 h-3" />
              </Link>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
