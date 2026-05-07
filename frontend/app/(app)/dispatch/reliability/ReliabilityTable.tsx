'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronUp, ChevronDown, ChevronsUpDown,
  ChevronRight, AlertTriangle, CheckCircle2,
} from 'lucide-react'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import type { ScorecardRow, SortKey, SortDir, SortState } from './types'

interface ReliabilityTableProps {
  rows: ScorecardRow[]
  weekIso: string
}

// ─── Sort helpers ─────────────────────────────────────────────────────────────

function getSortValue(row: ScorecardRow, key: SortKey): number | string | null {
  switch (key) {
    case 'driver_name':           return row.driver_name
    case 'escalation_count':      return row.escalation_count ?? 0
    case 'self_serve_pct':        return row.self_serve_pct ?? 100
    case 'on_time_pickup_arrival': {
      const ax = row.axes?.on_time_pickup_arrival
      return ax?.available ? ax.raw * 100 : null
    }
    case 'composite_score':       return row.composite_score
    case 'total_trips':           return row.total_trips
    case 'revenue_impact':        return row.revenue_impact ?? 0
    default:                      return null
  }
}

function sortRows(rows: ScorecardRow[], sort: SortState): ScorecardRow[] {
  return [...rows].sort((a, b) => {
    const av = getSortValue(a, sort.key)
    const bv = getSortValue(b, sort.key)
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    let cmp: number
    if (typeof av === 'string' && typeof bv === 'string') {
      cmp = av.localeCompare(bv)
    } else {
      cmp = (av as number) < (bv as number) ? -1 : (av as number) > (bv as number) ? 1 : 0
    }
    return sort.dir === 'asc' ? cmp : -cmp
  })
}

// ─── Escalation badge ─────────────────────────────────────────────────────────

function EscalationBadge({ count, totalTrips }: { count: number; totalTrips: number }) {
  if (count === 0) {
    return (
      <span className="inline-flex items-center gap-1 text-emerald-400 font-medium tabular-nums">
        <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" />
        0
      </span>
    )
  }
  const severity = totalTrips > 0 ? count / totalTrips : 0
  const color = severity >= 0.4
    ? 'text-red-400'
    : severity >= 0.2
      ? 'text-orange-400'
      : 'text-amber-400'
  return (
    <span className={cn('inline-flex items-center gap-1 font-semibold tabular-nums', color)}>
      <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
      {count}
    </span>
  )
}

// ─── Self-serve % cell ────────────────────────────────────────────────────────

function SelfServeCell({ pct }: { pct: number | null }) {
  if (pct == null) {
    return <span className="dark:text-white/25 text-gray-300 select-none">—</span>
  }
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

// ─── On-time % cell ───────────────────────────────────────────────────────────

function OnTimeCell({ ax }: { ax: ScorecardRow['axes']['on_time_pickup_arrival'] | undefined }) {
  if (!ax?.available) {
    return <span className="dark:text-white/20 text-gray-300 select-none text-xs">N/A</span>
  }
  const pct = ax.raw * 100
  const color =
    pct >= 90 ? 'dark:text-white/70 text-gray-600' :
    pct >= 75 ? 'text-amber-400' :
    'text-red-400'
  return (
    <span className={cn('tabular-nums', color)}>
      {pct.toFixed(0)}%
    </span>
  )
}

// ─── Column header ────────────────────────────────────────────────────────────

interface ColHeaderProps {
  label: string
  sortKey: SortKey
  currentSort: SortState
  onSort: (k: SortKey) => void
  className?: string
  title?: string
}

function ColHeader({ label, sortKey, currentSort, onSort, className, title }: ColHeaderProps) {
  const isActive = currentSort.key === sortKey
  return (
    <th
      className={cn(
        'px-3 py-3 text-left font-medium dark:text-white/40 text-gray-400 text-xs whitespace-nowrap',
        'cursor-pointer select-none hover:dark:text-white/70 hover:text-gray-600 transition-colors',
        className
      )}
      onClick={() => onSort(sortKey)}
      title={title}
    >
      <div className="flex items-center gap-1">
        {label}
        {isActive
          ? currentSort.dir === 'asc'
            ? <ChevronUp className="w-3 h-3 text-[#667eea]" />
            : <ChevronDown className="w-3 h-3 text-[#667eea]" />
          : <ChevronsUpDown className="w-3 h-3 opacity-30" />
        }
      </div>
    </th>
  )
}

// ─── Expanded row detail ──────────────────────────────────────────────────────

function ExpandedDetail({ row, colSpan, weekIso }: { row: ScorecardRow; colSpan: number; weekIso: string }) {
  const escalations = row.escalation_count ?? 0
  const trips = row.total_trips

  // Plain-English coaching note matching the plan's copy examples
  let coachNote: string
  if (trips === 0) {
    coachNote = 'No rides this week.'
  } else if (escalations === 0) {
    const pct = row.self_serve_pct?.toFixed(0) ?? '100'
    coachNote = `${trips} trips this week. Zero calls from dispatch. Self-serve ${pct}% — top of the fleet.`
  } else {
    coachNote = `${trips} trips this week. Dispatch had to call ${escalations} time${escalations !== 1 ? 's' : ''}. `
    if (escalations >= 6) {
      coachNote += `When this keeps up we need a conversation.`
    } else if (escalations >= 4) {
      coachNote += `Let's get on a call this week.`
    } else {
      coachNote += `Fewer calls keeps you in the top assignments.`
    }
  }

  return (
    <motion.tr
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
    >
      <td colSpan={colSpan} className="px-0 pb-0">
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          className="overflow-hidden"
        >
          <div className="px-5 py-4 dark:bg-[#667eea]/[0.04] bg-indigo-50/60 border-t dark:border-[#667eea]/20 border-indigo-100 mx-0">
            <div className="flex flex-col sm:flex-row sm:items-start gap-4">
              {/* Coaching note */}
              <div className="flex-1 min-w-0">
                <p className="text-xs dark:text-white/35 text-gray-400 uppercase tracking-wide font-medium mb-1">
                  This week
                </p>
                <p className="text-sm dark:text-white/80 text-gray-700 leading-snug">
                  {coachNote}
                </p>
              </div>

              {/* Focus area / coaching tip */}
              {row.focus_area && (
                <div className="flex-1 min-w-0">
                  <p className="text-xs dark:text-white/35 text-gray-400 uppercase tracking-wide font-medium mb-1">
                    Tip
                  </p>
                  <p className="text-sm dark:text-white/60 text-gray-500 leading-snug">
                    {row.focus_area}
                  </p>
                </div>
              )}

              {/* Drill-in link */}
              <div className="flex-shrink-0 self-end">
                <Link
                  href={`/dispatch/reliability/${row.person_id}?week=${encodeURIComponent(weekIso)}`}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white/60 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-50 hover:text-[#667eea] dark:hover:text-[#667eea] transition-all"
                >
                  Full history
                  <ChevronRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            </div>
          </div>
        </motion.div>
      </td>
    </motion.tr>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

// Header note — no tier labels on the table per product principle.
// Columns: Driver | Trips | Escalations | Self-serve % | On-time % | Notes (expand)
const COL_COUNT = 7

export default function ReliabilityTable({ rows, weekIso }: ReliabilityTableProps) {
  // Default: escalations DESC — most escalations first (who needs coaching)
  const [sort, setSort] = useState<SortState>({ key: 'escalation_count', dir: 'desc' })
  const [expandedId, setExpandedId] = useState<number | null>(null)

  function handleSort(key: SortKey) {
    setSort(prev =>
      prev.key === key
        ? { ...prev, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: key === 'driver_name' ? 'asc' : 'desc' }
    )
  }

  function toggleExpand(personId: number) {
    setExpandedId(prev => (prev === personId ? null : personId))
  }

  const sorted = sortRows(rows, sort)

  return (
    <div className="rounded-xl dark:bg-white/[0.03] bg-white border dark:border-white/[0.08] border-gray-200 overflow-hidden">
      {/* Table header note */}
      <div className="px-5 py-3 border-b dark:border-white/[0.06] border-gray-100">
        <p className="text-xs dark:text-white/35 text-gray-400 leading-relaxed">
          Self-serve = trips that finished without a call from dispatch.{' '}
          Escalations = trips where dispatch had to step in.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead>
            <tr className="border-b dark:border-white/[0.08] border-gray-100">
              <ColHeader
                label="Driver"
                sortKey="driver_name"
                currentSort={sort}
                onSort={handleSort}
                className="pl-5 w-48"
              />
              <ColHeader
                label="Trips"
                sortKey="total_trips"
                currentSort={sort}
                onSort={handleSort}
                className="w-16"
              />
              <ColHeader
                label="Escalations"
                sortKey="escalation_count"
                currentSort={sort}
                onSort={handleSort}
                className="w-28"
                title="Trips where dispatch had to call — lower is better"
              />
              <ColHeader
                label="Self-serve %"
                sortKey="self_serve_pct"
                currentSort={sort}
                onSort={handleSort}
                className="w-28"
                title="Trips completed without dispatch intervention"
              />
              <ColHeader
                label="On-time arrival"
                sortKey="on_time_pickup_arrival"
                currentSort={sort}
                onSort={handleSort}
                className="w-28"
                title="Arrived at pickup within 5 min of scheduled time"
              />
              <ColHeader
                label="Score"
                sortKey="composite_score"
                currentSort={sort}
                onSort={handleSort}
                className="w-20"
                title="60% self-serve + 40% on-time arrival"
              />
              {/* Expand indicator — not sortable */}
              <th className="w-10 pr-3" />
            </tr>
          </thead>
          <tbody>
            <AnimatePresence initial={false}>
              {sorted.map((row, i) => {
                const isExpanded = expandedId === row.person_id
                const isLowSample = row.low_sample
                return [
                  <motion.tr
                    key={`row-${row.person_id}`}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: Math.min(i * 0.02, 0.3) }}
                    className={cn(
                      'border-b last:border-0 dark:border-white/[0.05] border-gray-50 transition-colors cursor-pointer',
                      isExpanded
                        ? 'dark:bg-[#667eea]/[0.05] bg-indigo-50/40'
                        : 'dark:hover:bg-white/[0.03] hover:bg-gray-50',
                      isLowSample && !isExpanded && 'opacity-60'
                    )}
                    onClick={() => toggleExpand(row.person_id)}
                  >
                    {/* Driver name */}
                    <td className="px-3 py-3 pl-5 dark:text-white/80 text-gray-700 font-medium whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        {row.driver_name}
                        {isLowSample && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] bg-gray-500/10 text-gray-400 border border-gray-500/20 font-normal flex-shrink-0">
                            &lt;5 trips
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Trip count */}
                    <td className="px-3 py-3 tabular-nums dark:text-white/50 text-gray-500">
                      {row.total_trips}
                    </td>

                    {/* Escalation count */}
                    <td className="px-3 py-3">
                      <EscalationBadge count={row.escalation_count ?? 0} totalTrips={row.total_trips} />
                    </td>

                    {/* Self-serve % */}
                    <td className="px-3 py-3">
                      <SelfServeCell pct={row.self_serve_pct ?? null} />
                    </td>

                    {/* On-time arrival */}
                    <td className="px-3 py-3">
                      <OnTimeCell ax={row.axes?.on_time_pickup_arrival} />
                    </td>

                    {/* Composite score */}
                    <td className="px-3 py-3 tabular-nums dark:text-white/50 text-gray-500 text-sm">
                      {row.composite_score != null
                        ? row.composite_score.toFixed(0)
                        : '—'}
                    </td>

                    {/* Expand indicator */}
                    <td className="px-3 py-3 pr-4">
                      <motion.div
                        animate={{ rotate: isExpanded ? 90 : 0 }}
                        transition={{ duration: 0.15 }}
                        className="dark:text-white/30 text-gray-300"
                      >
                        <ChevronRight className="w-4 h-4" />
                      </motion.div>
                    </td>
                  </motion.tr>,

                  // Expanded detail row
                  isExpanded && (
                    <ExpandedDetail
                      key={`expand-${row.person_id}`}
                      row={row}
                      colSpan={COL_COUNT}
                      weekIso={weekIso}
                    />
                  ),
                ]
              })}
            </AnimatePresence>
          </tbody>
        </table>
      </div>
    </div>
  )
}
