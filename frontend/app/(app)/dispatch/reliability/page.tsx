'use client'

import { useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import { BarChart2, RefreshCw, Send, AlertCircle } from 'lucide-react'
import { toast } from 'sonner'
import PageHeader from '@/components/ui/PageHeader'
import EmptyState from '@/components/ui/EmptyState'
import WeekSelector, { currentIsoWeek } from './WeekSelector'
import ReliabilityFilters, { type TierFilter } from './ReliabilityFilters'
import ReliabilityTable from './ReliabilityTable'
import ReliabilityMobileCard from './ReliabilityMobileCard'
import ReliabilitySkeleton from './ReliabilitySkeleton'
import { useReliabilityData } from './useReliabilityData'
import type { ScorecardRow } from './types'

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

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ReliabilityPage() {
  const [weekIso, setWeekIso] = useState<string>(currentIsoWeek)
  const [tierFilter, setTierFilter] = useState<TierFilter>('all')
  const [minTrips, setMinTrips] = useState<number>(0)
  const [search, setSearch] = useState<string>('')
  const [sendingCards, setSendingCards] = useState(false)

  const { data, loading, error, refetch } = useReliabilityData(weekIso)

  const filtered = useMemo(
    () => applyFilters(data, tierFilter, minTrips, search),
    [data, tierFilter, minTrips, search]
  )

  async function handleSendCards() {
    setSendingCards(true)
    // Phase 10 endpoint not yet wired — stub
    await new Promise(r => setTimeout(r, 400))
    setSendingCards(false)
    toast.info('Sunday cron not yet wired — Phase 10 pending', {
      description: 'Weekly cards will send automatically once Phase 10 is shipped.',
    })
  }

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      {/* Page header */}
      <PageHeader
        title="Driver Reliability"
        subtitle="Gold drivers get priority dispatch. Probation = active coaching needed."
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
            <button
              onClick={handleSendCards}
              disabled={sendingCards}
              className="flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium border dark:bg-white/[0.04] dark:border-white/[0.10] bg-white border-gray-200 dark:text-white/70 text-gray-600 dark:hover:bg-white/[0.08] hover:bg-gray-50 transition-all disabled:opacity-50 cursor-pointer"
            >
              <Send className="w-3.5 h-3.5 flex-shrink-0" />
              {sendingCards ? 'Sending…' : 'Send weekly cards'}
            </button>
          </div>
        }
      />

      {/* Sticky toolbar — week selector + filters */}
      <div className="sticky top-14 z-30 -mx-4 px-4 py-3 dark:bg-[#0f1219]/90 bg-[#f0f2f8]/90 backdrop-blur-xl border-b dark:border-white/[0.08] border-gray-200">
        <div className="max-w-7xl mx-auto flex flex-wrap items-center gap-3">
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
        </div>
      </div>

      {/* Results count */}
      {!loading && !error && data.length > 0 && (
        <p className="text-xs dark:text-white/35 text-gray-400">
          {filtered.length} of {data.length} drivers
          {weekIso && <span className="ml-1 font-medium dark:text-white/50 text-gray-500">{weekIso}</span>}
        </p>
      )}

      {/* Content area */}
      {loading && <ReliabilitySkeleton />}

      {!loading && error && (
        <ErrorCard message={error} onRetry={refetch} />
      )}

      {!loading && !error && data.length === 0 && (
        <EmptyState
          icon={<BarChart2 className="w-7 h-7" />}
          title="No driver activity this week"
          subtitle={`No rides found for ${weekIso}. Try a different week or check that ride data has been imported.`}
        />
      )}

      {!loading && !error && data.length > 0 && filtered.length === 0 && (
        <EmptyState
          icon={<BarChart2 className="w-7 h-7" />}
          title="No drivers match your filters"
          subtitle="Try adjusting the tier, min trips, or name search."
          action={{ label: 'Clear filters', onClick: () => { setTierFilter('all'); setMinTrips(0); setSearch('') } }}
        />
      )}

      {!loading && !error && filtered.length > 0 && (
        <>
          {/* Desktop table */}
          <div className="hidden md:block">
            <ReliabilityTable rows={filtered} weekIso={weekIso} />
          </div>

          {/* Mobile cards */}
          <div className="md:hidden space-y-2">
            {filtered.map(row => (
              <ReliabilityMobileCard key={row.person_id} row={row} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
