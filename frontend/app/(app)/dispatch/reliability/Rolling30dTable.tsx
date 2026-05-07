'use client'

import { motion } from 'framer-motion'
import { CheckCircle2, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { RollingRow } from './types'

interface Rolling30dTableProps {
  rows: RollingRow[]
}

function EscAvgCell({ avg }: { avg: number | null }) {
  if (avg == null) return <span className="dark:text-white/25 text-gray-300 select-none">—</span>
  const rounded = Math.round(avg * 10) / 10
  if (rounded < 0.5) {
    return (
      <span className="inline-flex items-center gap-1 text-emerald-400 font-medium tabular-nums">
        <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" />
        {rounded.toFixed(1)}
      </span>
    )
  }
  const severity = rounded >= 3 ? 'text-red-400' : rounded >= 1.5 ? 'text-orange-400' : 'text-amber-400'
  return (
    <span className={cn('inline-flex items-center gap-1 font-semibold tabular-nums', severity)}>
      <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
      {rounded.toFixed(1)}
    </span>
  )
}

function SelfServeAvgCell({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="dark:text-white/25 text-gray-300 select-none">—</span>
  const color =
    pct >= 95 ? 'text-emerald-400' :
    pct >= 80 ? 'dark:text-white/75 text-gray-600' :
    pct >= 60 ? 'text-amber-400' :
    'text-red-400'
  return (
    <span className={cn('tabular-nums font-medium', color)}>
      {pct.toFixed(0)}%
    </span>
  )
}

export default function Rolling30dTable({ rows }: Rolling30dTableProps) {
  if (rows.length === 0) {
    return (
      <div className="rounded-xl dark:bg-white/[0.03] bg-white border dark:border-white/[0.08] border-gray-200 p-8 text-center">
        <p className="text-sm dark:text-white/40 text-gray-400">
          No 30-day cache data yet. The Sunday cron needs to run at least once to populate this view.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-xl dark:bg-white/[0.03] bg-white border dark:border-white/[0.08] border-gray-200 overflow-hidden">
      <div className="px-5 py-3 border-b dark:border-white/[0.06] border-gray-100">
        <p className="text-xs dark:text-white/35 text-gray-400 leading-relaxed">
          30-day rolling average — last 4 ISO weeks from scorecard cache. Trips = total across all 4 weeks.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[560px]">
          <thead>
            <tr className="border-b dark:border-white/[0.08] border-gray-100">
              <th className="px-3 py-3 pl-5 text-left font-medium dark:text-white/40 text-gray-400 text-xs w-48">
                Driver
              </th>
              <th className="px-3 py-3 text-left font-medium dark:text-white/40 text-gray-400 text-xs w-16">
                Trips
              </th>
              <th
                className="px-3 py-3 text-left font-medium dark:text-white/40 text-gray-400 text-xs w-32"
                title="Avg escalations per week over last 4 weeks"
              >
                Avg Escalations
              </th>
              <th
                className="px-3 py-3 text-left font-medium dark:text-white/40 text-gray-400 text-xs w-28"
                title="Avg self-serve % over last 4 weeks"
              >
                Avg Self-serve
              </th>
              <th
                className="px-3 py-3 text-left font-medium dark:text-white/40 text-gray-400 text-xs w-20"
                title="Avg composite score over last 4 weeks"
              >
                Avg Score
              </th>
              <th className="px-3 py-3 text-left font-medium dark:text-white/40 text-gray-400 text-xs w-16">
                Weeks
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <motion.tr
                key={row.person_id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: Math.min(i * 0.02, 0.3) }}
                className="border-b last:border-0 dark:border-white/[0.05] border-gray-50"
              >
                <td className="px-3 py-3 pl-5 dark:text-white/80 text-gray-700 font-medium whitespace-nowrap">
                  {row.driver_name}
                </td>
                <td className="px-3 py-3 tabular-nums dark:text-white/50 text-gray-500">
                  {row.total_trips}
                </td>
                <td className="px-3 py-3">
                  <EscAvgCell avg={row.escalation_count} />
                </td>
                <td className="px-3 py-3">
                  <SelfServeAvgCell pct={row.self_serve_pct} />
                </td>
                <td className="px-3 py-3 tabular-nums dark:text-white/50 text-gray-500">
                  {row.composite_score != null ? row.composite_score.toFixed(0) : '—'}
                </td>
                <td className="px-3 py-3 tabular-nums dark:text-white/30 text-gray-400 text-xs">
                  {row.weeks_found}/4
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
