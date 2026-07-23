'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Search, ChevronDown, ArrowRight, PhoneCall } from 'lucide-react'
import { api } from '@/lib/api'
import { todayStr } from '@/lib/utils'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import SuggestionList from './SuggestionList'
import { CoverageChain, CoverageResponse, RosterRow, RostersResponse } from './types'

function RosterSearchSelect({
  rosters,
  value,
  onChange,
}: {
  rosters: RosterRow[]
  value: RosterRow | null
  onChange: (r: RosterRow) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim()
    if (!q) return rosters
    return rosters.filter(r =>
      `${r.school} ${r.direction} ${r.number}`.toLowerCase().includes(q)
    )
  }, [rosters, query])

  return (
    <div ref={ref} className="relative w-full sm:w-80">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 cursor-pointer"
      >
        <span className="truncate">
          {value ? `${value.school} — ${value.direction} ${value.number}` : 'Choose a route…'}
        </span>
        <ChevronDown className="w-3.5 h-3.5 dark:text-white/30 text-gray-400 shrink-0" />
      </button>

      {open && (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="absolute z-20 mt-1.5 w-full max-h-72 overflow-y-auto rounded-xl border dark:border-white/10 border-gray-200 dark:bg-[#16161d] bg-white shadow-xl"
        >
          <div className="p-2 sticky top-0 dark:bg-[#16161d] bg-white border-b dark:border-white/8 border-gray-100">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 dark:text-white/25 text-gray-300" />
              <input
                autoFocus
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search school or route…"
                className="w-full pl-8 pr-2 py-1.5 rounded-lg text-xs dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 focus:outline-none"
              />
            </div>
          </div>
          {filtered.length === 0 && (
            <p className="px-3 py-4 text-xs dark:text-white/30 text-gray-400">No routes match</p>
          )}
          {filtered.map(r => (
            <button
              key={r.roster_id}
              onClick={() => { onChange(r); setOpen(false); setQuery('') }}
              className="w-full text-left px-3 py-2 text-sm dark:text-white/70 text-gray-700 dark:hover:bg-white/5 hover:bg-gray-50 cursor-pointer"
            >
              {r.school} <span className="dark:text-white/35 text-gray-400">— {r.direction} {r.number}</span>
            </button>
          ))}
        </motion.div>
      )}
    </div>
  )
}

function ChainCard({ chain, index }: { chain: CoverageChain; index: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      className="rounded-2xl border p-4 space-y-2.5 bg-amber-500/[0.06] border-amber-500/20"
    >
      <div className="flex items-center gap-2">
        <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white bg-amber-500">
          {index + 1}
        </span>
        <p className="text-sm font-medium dark:text-white/85 text-gray-800">{chain.description}</p>
      </div>
      <ol className="space-y-1.5 pl-1">
        {chain.moves.map((move, i) => (
          <li key={i} className="flex items-start gap-2 text-xs dark:text-white/60 text-gray-600">
            <ArrowRight className="w-3 h-3 mt-0.5 shrink-0 dark:text-white/25 text-gray-300" />
            <span>
              <span className="font-semibold dark:text-white/80 text-gray-800">{move.name}</span>{' '}
              {move.action}
            </span>
          </li>
        ))}
      </ol>
    </motion.div>
  )
}

export default function CoveragePanel() {
  const [rosters, setRosters] = useState<RosterRow[]>([])
  const [rostersLoading, setRostersLoading] = useState(true)
  const [selectedRoster, setSelectedRoster] = useState<RosterRow | null>(null)
  const [date, setDate] = useState(todayStr())
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<RostersResponse>('/api/data/assignment/rosters')
      .then(res => setRosters(res.rosters ?? []))
      .catch(() => setRosters([]))
      .finally(() => setRostersLoading(false))
  }, [])

  useEffect(() => {
    if (!selectedRoster || !date) {
      setCoverage(null)
      return
    }
    setLoading(true)
    setError(null)
    const qs = new URLSearchParams({ roster_id: String(selectedRoster.roster_id), date })
    api.get<CoverageResponse>(`/api/data/assignment/coverage?${qs.toString()}`)
      .then(res => setCoverage(res))
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load coverage options'))
      .finally(() => setLoading(false))
  }, [selectedRoster, date])

  return (
    <div className="space-y-5">
      <div className="flex items-end gap-3 flex-wrap">
        <div>
          <label className="block text-xs font-medium dark:text-white/40 text-gray-400 mb-1">Route</label>
          {rostersLoading ? (
            <div className="py-1"><LoadingSpinner size="sm" /></div>
          ) : (
            <RosterSearchSelect rosters={rosters} value={selectedRoster} onChange={setSelectedRoster} />
          )}
        </div>
        <div>
          <label className="block text-xs font-medium dark:text-white/40 text-gray-400 mb-1">Date</label>
          <input
            type="date"
            value={date}
            onChange={e => setDate(e.target.value)}
            className="px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 focus:outline-none focus:border-[#667eea]/60"
          />
        </div>
      </div>

      {!selectedRoster && (
        <div className="flex items-center justify-center py-14 rounded-2xl dark:bg-white/[0.02] bg-gray-50 border dark:border-white/8 border-gray-200">
          <p className="text-sm dark:text-white/35 text-gray-400">Pick a route and date to see who&apos;s free to cover</p>
        </div>
      )}

      {selectedRoster && loading && <div className="py-10"><LoadingSpinner /></div>}

      {selectedRoster && !loading && error && (
        <div className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/25 text-sm text-red-500">{error}</div>
      )}

      {selectedRoster && !loading && !error && coverage && (
        <div className="space-y-5">
          {coverage.direct.length === 0 && coverage.chains.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 rounded-2xl dark:bg-white/[0.02] bg-gray-50 border dark:border-white/8 border-gray-200">
              <PhoneCall className="w-5 h-5 dark:text-white/25 text-gray-300" />
              <p className="text-sm dark:text-white/40 text-gray-500">
                No clean options — start calling from the backup roster.
              </p>
            </div>
          ) : (
            <>
              {coverage.direct.length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-xs font-bold uppercase tracking-widest text-emerald-500">
                    Free drivers — direct cover
                  </h3>
                  <SuggestionList drivers={coverage.direct} />
                </section>
              )}

              {coverage.chains.length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-xs font-bold uppercase tracking-widest text-amber-500">
                    Swap chains (≤2 moves)
                  </h3>
                  <div className="space-y-2">
                    {coverage.chains.map((c, i) => <ChainCard key={i} chain={c} index={i} />)}
                  </div>
                </section>
              )}
            </>
          )}

          {coverage.notes.length > 0 && (
            <div className="rounded-xl px-4 py-3 dark:bg-white/[0.02] bg-gray-50 border dark:border-white/5 border-gray-100">
              {coverage.notes.map((n, i) => (
                <p key={i} className="text-xs dark:text-white/35 text-gray-400">{n}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
