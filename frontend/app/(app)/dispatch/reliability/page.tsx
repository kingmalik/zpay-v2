'use client'

import { useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import { BarChart2, RefreshCw, AlertCircle, Calendar, TrendingUp } from 'lucide-react'
import PageHeader from '@/components/ui/PageHeader'
import EmptyState from '@/components/ui/EmptyState'
import WeekSelector, { currentIsoWeek } from './WeekSelector'
import ReliabilityFilters, { type TierFilter } from './ReliabilityFilters'
import ReliabilityTable from './ReliabilityTable'
import Rolling30dTable from './Rolling30dTable'
import ReliabilityMobileCard from './ReliabilityMobileCard'
import ReliabilitySkeleton from './ReliabilitySkeleton'
import { useReliabilityData, useRollingData } from './useReliabilityData'
import type { ScorecardRow, ViewWindow } from './types'
import { cn } from '@/lib/utils'

// ─── Filter logic ─────────────────────────────────────────────────────────────

function applyFilters(
  rows: ScorecardRow[],
  tierFilter: TierFilter,
  minTrips: number,
  search: string
): ScorecardRow[] {
  const needle = search.trim().toLowerCase()
  return rows.filter(row => {
    if (tierFilter !== 'all' && row.tier !== tierFilter) return false
    if (row.total_trips < minTrips) return false
    if (needle && !row.driver_name.toLowerCase().includes(needle)) return false
    return true
  })
}

// ─── Error card ───────────────────────────────────────────────────────────────

function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl dark:bg-red-500/[0.06] bg-red-50 border dark:border-red-500/25 border-red-200 p-6 flex flex-col items-center gap-3 text-center"
    >
      <div className="w-10 h-10 rounded-xl bg-red-500/10 flex items-center justify-center">
        <AlertCircle className="w-5 h-5 text-red-400" />
      </div>
      <div>
        <p className="text-sm font-medium dark:text-white/80 text-gray-700 mb-1">Failed to load reliability data</p>
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

// ─── Window toggle ────────────────────────────────────────────────────────────

interface WindowToggleProps {
  value: ViewWindow
  onChange: (w: ViewWindow) => void
}

function WindowToggle({ value, onChange }: WindowToggleProps) {
  return (
    <div className="flex items-center rounded-lg dark:bg-white/[0.05] bg-gray-100 p-0.5 gap-0.5">
      <button
        onClick={() => onChange('weekly')}
        className={cn(
          'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer',
          value === 'weekly'
            ? 'dark:bg-white/10 bg-white dark:text-white/80 text-gray-700 shadow-sm'
            : 'dark:text-white/35 text-gray-400 hover:dark:text-white/55 hover:text-gray-600'
        )}
        title="Current week scorecard"
      >
        <Calendar className="w-3 h-3 flex-shrink-0" />
        This week
      </button>
      <button
        onClick={() => onChange('30d')}
        className={cn(
          'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer',
          value === '30d'
            ? 'dark:bg-white/10 bg-white dark:text-white/80 text-gray-700 shadow-sm'
            : 'dark:text-white/35 text-gray-400 hover:dark:text-white/55 hover:text-gray-600'
        )}
        title="30-day rolling average from cache"
      >
        <TrendingUp className="w-3 h-3 flex-shrink-0" />
        Last 30 days
      </button>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ReliabilityPage() {
  const [weekIso, setWeekIso] = useState<string>(currentIsoWeek)
  const [viewWindow, setViewWindow] = useState<ViewWindow>('weekly')
  const [tierFilter, setTierFilter] = useState<TierFilter>('all')
  const [minTrips, setMinTrips] = useState<number>(0)
  const [search, setSearch] = useState<string>('')

  const weekly = useReliabilityData(weekIso)
  const rolling = useRollingData(weekIso)

  const activeData = viewWindow === 'weekly' ? weekly : rolling
  const loading = activeData.loading
  const error = activeData.error
  const refetch = activeData.refetch

  const filtered = useMemo(
    () => viewWindow === 'weekly'
      ? applyFilters(weekly.data, tierFilter, minTrips, search)
      : rolling.data.filter(r => !search || r.driver_name.toLowerCase().includes(search.toLowerCase())),
    [weekly.data, rolling.data, viewWindow, tierFilter, minTrips, search]
  )

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      {/* Page header */}
      <PageHeader
        title="Driver Reliability"
        subtitle="Self-serve = finished without a dispatch call. More escalations = coaching needed."
        icon={<BarChart2 className="w-4.5 h-4.5" />}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={refetch}
              disabled={loading}
              className="w-8 h-8 rounded-lg flex items-center justify-center dark:bg-white/5 bg-gray-100 dark:text-white/50 text-gray-500 dark:hover:bg-white/10 hover:bg-gray-200 transition-all disabled:opacity-40 cursor-pointer"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        }
      />

      {/* Sticky toolbar */}
      <div className="sticky top-14 z-30 -mx-4 px-4 py-3 dark:bg-[#0f1219]/90 bg-[#f0f2f8]/90 backdrop-blur-xl border-b dark:border-white/[0.08] border-gray-200">
        <div className="max-w-7xl mx-auto flex flex-wrap items-center gap-3">
          {/* Window toggle */}
          <WindowToggle value={viewWindow} onChange={setViewWindow} />

          {viewWindow === 'weekly' && (
            <>
              <div className="dark:bg-white/[0.06] bg-gray-300 w-px h-6 hidden sm:block" />
              <WeekSelector weekIso={weekIso} onWeekChange={setWeekIso} />
              <div className="dark:bg-white/[0.06] bg-gray-300 w-px h-6 hidden sm:block" />
              <ReliabilityFilters
                tierFilter={tierFilter}
                onTierChange={setTierFilter}
                minTrips={minTrips}
                onMinTripsChange={setMinTrips}
                search={search}
                onSearchChange={setSearch}
              />
            </>
          )}

          {viewWindow === '30d' && (
            <>
              <div className="dark:bg-white/[0.06] bg-gray-300 w-px h-6 hidden sm:block" />
              <p className="text-xs dark:text-white/35 text-gray-400">
                Last 4 complete weeks ending before {weekIso}
              </p>
              {/* Name search works in 30d view too */}
              <input
                type="text"
                placeholder="Search driver..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="px-2.5 py-1.5 text-xs rounded-lg dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white/70 text-gray-700 dark:placeholder-white/25 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-[#667eea]/40 w-36"
              />
            </>
          )}
        </div>
      </div>

      {/* Results count */}
      {!loading && !error && viewWindow === 'weekly' && weekly.data.length > 0 && (
        <p className="text-xs dark:text-white/35 text-gray-400">
          {filtered.length} of {weekly.data.length} drivers
          {weekIso && <span className="ml-1 font-medium dark:text-white/50 text-gray-500">{weekIso}</span>}
        </p>
      )}

      {!loading && !error && viewWindow === '30d' && rolling.data.length > 0 && (
        <p className="text-xs dark:text-white/35 text-gray-400">
          {filtered.length} driver{filtered.length !== 1 ? 's' : ''} with cache data
        </p>
      )}

      {/* Content */}
      {loading && <ReliabilitySkeleton />}

      {!loading && error && (
        <ErrorCard message={error} onRetry={refetch} />
      )}

      {!loading && !error && viewWindow === 'weekly' && weekly.data.length === 0 && (
        <EmptyState
          icon={<BarChart2 className="w-7 h-7" />}
          title="No driver activity this week"
          subtitle={`No rides found for ${weekIso}. Try a different week or check that ride data has been imported.`}
        />
      )}

      {!loading && !error && viewWindow === 'weekly' && weekly.data.length > 0 && filtered.length === 0 && (
        <EmptyState
          icon={<BarChart2 className="w-7 h-7" />}
          title="No drivers match your filters"
          subtitle="Try adjusting the tier, min trips, or name search."
          action={{ label: 'Clear filters', onClick: () => { setTierFilter('all'); setMinTrips(0); setSearch('') } }}
        />
      )}

      {/* Weekly view */}
      {!loading && !error && viewWindow === 'weekly' && filtered.length > 0 && (
        <>
          <div className="hidden md:block">
            <ReliabilityTable rows={filtered as ScorecardRow[]} weekIso={weekIso} />
          </div>
          <div className="md:hidden space-y-2">
            {(filtered as ScorecardRow[]).map(row => (
              <ReliabilityMobileCard key={row.person_id} row={row} />
            ))}
          </div>
        </>
      )}

      {/* 30-day rolling view */}
      {!loading && !error && viewWindow === '30d' && (
        <Rolling30dTable rows={filtered as import('./types').RollingRow[]} />
      )}
    </div>
  )
}
