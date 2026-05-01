'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronUp, ChevronDown, ChevronsUpDown,
  ChevronRight, TrendingUp, TrendingDown, Minus, Info,
} from 'lucide-react'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import TierBadge from './TierBadge'
import type { ScorecardRow, SortKey, SortDir, SortState } from './types'
import { TIER_ORDER } from './types'

interface ReliabilityTableProps {
  rows: ScorecardRow[]
  weekIso: string
}

// ─── Sort helpers ─────────────────────────────────────────────────────────────

function getAxisValue(row: ScorecardRow, axisKey: keyof ScorecardRow['axes']): number | null {
  const ax = row.axes[axisKey]
  if (!ax?.available) return null
  return ax.raw * 100
}

function getSortValue(row: ScorecardRow, key: SortKey): number | string | null {
  switch (key) {
    case 'driver_name':      return row.driver_name
    case 'tier':             return TIER_ORDER[row.tier] ?? 9
    case 'composite_score':  return row.composite_score
    case 'wow_delta':        return row.wow_delta
    case 'total_trips':      return row.total_trips
    case 'acceptance_rate':  return getAxisValue(row, 'acceptance_rate')
    case 'on_time_start':    return getAxisValue(row, 'on_time_start')
    case 'on_time_arrival':  return getAxisValue(row, 'on_time_arrival')
    case 'on_time_completion': return getAxisValue(row, 'on_time_completion')
    case 'responsiveness':   return getAxisValue(row, 'responsiveness')
    case 'reliability':      return getAxisValue(row, 'reliability')
    default:                 return null
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

// ─── Axis cell ────────────────────────────────────────────────────────────────

interface AxisCellProps {
  ax: ScorecardRow['axes'][keyof ScorecardRow['axes']]
}

function AxisCell({ ax }: AxisCellProps) {
  if (!ax.available) {
    return <span className="dark:text-white/25 text-gray-300 select-none">—</span>
  }
  const pct = (ax.raw * 100).toFixed(1)
  const isLow = ax.sample_size < 3
  return (
    <span
      className={cn(
        'tabular-nums',
        isLow ? 'dark:text-white/35 text-gray-400' : 'dark:text-white/75 text-gray-700'
      )}
      title={isLow ? `Low sample (${ax.sample_size} trips)` : undefined}
    >
      {pct}%
      {isLow && (
        <Info className="w-2.5 h-2.5 inline ml-0.5 -mt-0.5 dark:text-white/25 text-gray-300" />
      )}
    </span>
  )
}

// ─── WoW delta cell ───────────────────────────────────────────────────────────

function DeltaCell({ delta }: { delta: number | null }) {
  if (delta == null) {
    return <span className="dark:text-white/25 text-gray-300">—</span>
  }
  const sign = delta > 0 ? '+' : ''
  const color = delta > 0
    ? 'text-emerald-400'
    : delta < 0
      ? 'text-red-400'
      : 'dark:text-white/40 text-gray-400'
  const Icon = delta > 0 ? TrendingUp : delta < 0 ? TrendingDown : Minus
  return (
    <span className={cn('inline-flex items-center gap-0.5 tabular-nums text-xs font-medium', color)}>
      <Icon className="w-3 h-3 flex-shrink-0" />
      {sign}{delta.toFixed(1)}
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
}

function ColHeader({ label, sortKey, currentSort, onSort, className }: ColHeaderProps) {
  const isActive = currentSort.key === sortKey
  return (
    <th
      className={cn(
        'px-3 py-3 text-left font-medium dark:text-white/40 text-gray-400 text-xs whitespace-nowrap',
        'cursor-pointer select-none hover:dark:text-white/70 hover:text-gray-600 transition-colors',
        className
      )}
      onClick={() => onSort(sortKey)}
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

function ExpandedDetail({ row, colSpan }: { row: ScorecardRow; colSpan: number }) {
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
              {/* Headline metric */}
              {row.headline_metric && (
                <div className="flex-1 min-w-0">
                  <p className="text-xs dark:text-white/35 text-gray-400 uppercase tracking-wide font-medium mb-1">
                    Headline
                  </p>
                  <p className="text-sm dark:text-white/80 text-gray-700 font-medium leading-snug">
                    {row.headline_metric}
                  </p>
                </div>
              )}

              {/* Focus area / coaching */}
              {row.focus_area && (
                <div className="flex-1 min-w-0">
                  <p className="text-xs dark:text-white/35 text-gray-400 uppercase tracking-wide font-medium mb-1">
                    Focus area
                  </p>
                  <p className="text-sm dark:text-white/70 text-gray-600 leading-snug">
                    {row.focus_area}
                  </p>
                </div>
              )}

              {/* Link to Phase 8 drill-in */}
              <div className="flex-shrink-0 self-end">
                <Link
                  href={`/dispatch/reliability/${row.person_id}`}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white/60 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-50 hover:text-[#667eea] dark:hover:text-[#667eea] transition-all"
                >
                  View 12-week trend
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

const COL_COUNT = 12 // driver + tier + composite + 6 axes + delta + trips + expand

export default function ReliabilityTable({ rows, weekIso }: ReliabilityTableProps) {
  const [sort, setSort] = useState<SortState>({ key: 'composite_score', dir: 'desc' })
  const [expandedId, setExpandedId] = useState<number | null>(null)

  void weekIso // available for future use (e.g. prefetching trend data)

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
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead>
            <tr className="border-b dark:border-white/[0.08] border-gray-100">
              <ColHeader label="Driver"       sortKey="driver_name"       currentSort={sort} onSort={handleSort} className="pl-5 w-40" />
              <ColHeader label="Tier"         sortKey="tier"              currentSort={sort} onSort={handleSort} className="w-28" />
              <ColHeader label="Composite"    sortKey="composite_score"   currentSort={sort} onSort={handleSort} className="w-24" />
              <ColHeader label="Acceptance"   sortKey="acceptance_rate"   currentSort={sort} onSort={handleSort} className="w-24" />
              <ColHeader label="Start"        sortKey="on_time_start"     currentSort={sort} onSort={handleSort} className="w-20" />
              <ColHeader label="Arrival"      sortKey="on_time_arrival"   currentSort={sort} onSort={handleSort} className="w-20" />
              <ColHeader label="Completion"   sortKey="on_time_completion" currentSort={sort} onSort={handleSort} className="w-24" />
              <ColHeader label="Response"     sortKey="responsiveness"    currentSort={sort} onSort={handleSort} className="w-22" />
              <ColHeader label="Reliability"  sortKey="reliability"       currentSort={sort} onSort={handleSort} className="w-22" />
              <ColHeader label="Δ Week"       sortKey="wow_delta"         currentSort={sort} onSort={handleSort} className="w-20" />
              <ColHeader label="Trips"        sortKey="total_trips"       currentSort={sort} onSort={handleSort} className="w-16 text-right pr-5" />
              {/* Expand chevron — not sortable */}
              <th className="w-10" />
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
                          <span className="px-1.5 py-0.5 rounded text-xs bg-gray-500/10 text-gray-400 border border-gray-500/20 font-normal flex-shrink-0">
                            low sample
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Tier */}
                    <td className="px-3 py-3">
                      <TierBadge tier={row.tier} label={row.tier_label} />
                    </td>

                    {/* Composite */}
                    <td className="px-3 py-3 tabular-nums dark:text-white/80 text-gray-700 font-semibold">
                      {row.composite_score != null
                        ? (row.composite_score * 100).toFixed(1)
                        : '—'}
                    </td>

                    {/* 6 axis cells */}
                    <td className="px-3 py-3"><AxisCell ax={row.axes.acceptance_rate} /></td>
                    <td className="px-3 py-3"><AxisCell ax={row.axes.on_time_start} /></td>
                    <td className="px-3 py-3"><AxisCell ax={row.axes.on_time_arrival} /></td>
                    <td className="px-3 py-3"><AxisCell ax={row.axes.on_time_completion} /></td>
                    <td className="px-3 py-3"><AxisCell ax={row.axes.responsiveness} /></td>
                    <td className="px-3 py-3"><AxisCell ax={row.axes.reliability} /></td>

                    {/* WoW delta */}
                    <td className="px-3 py-3">
                      <DeltaCell delta={row.wow_delta} />
                    </td>

                    {/* Trip count */}
                    <td className="px-3 py-3 pr-3 tabular-nums dark:text-white/50 text-gray-500 text-right">
                      {row.total_trips}
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
