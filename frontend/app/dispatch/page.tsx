'use client'

import { useEffect, useState, useRef } from 'react'
import { motion } from 'framer-motion'
import { RefreshCw, CheckCircle2, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { formatTime, todayStr } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface Trip {
  id?: string | number
  // FA and ED raw fields
  firstPickUp?: string
  tripStatus?: string
  status?: string
  name?: string
  serviceName?: string
  service_name?: string
  service_code?: string
  _source?: string
  origin?: string
  destination?: string
}

interface DriverDispatch {
  person_id?: number
  name?: string
  phone?: string
  sources?: string[]
  trips?: Trip[]
}

interface DispatchData {
  date?: string
  drivers?: DriverDispatch[]
  unassigned?: Trip[]
  dashboard?: { total?: number; completed?: number; active?: number; scheduled?: number; cancelled?: number }
  fa_ok?: boolean
  fa_error?: string | null
  ed_ok?: boolean
  ed_error?: string | null
}

function statusColor(status?: string): string {
  const s = (status || '').toLowerCase()
  if (s.includes('complete') || s.includes('done') || s.includes('finish')) return 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20'
  if (s.includes('active') || s.includes('start') || s.includes('progress')) return 'bg-blue-500/15 text-blue-400 border-blue-500/20'
  if (s.includes('cancel')) return 'bg-red-500/15 text-red-400 border-red-500/20'
  return 'bg-amber-500/15 text-amber-400 border-amber-500/20'
}

export default function DispatchPage() {
  const [data, setData] = useState<DispatchData | null>(null)
  const [loading, setLoading] = useState(true)
  const [accepting, setAccepting] = useState(false)
  const [source, setSource] = useState('all')
  const [date, setDate] = useState(todayStr())
  const [lastRefresh, setLastRefresh] = useState(new Date())
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function fetchData() {
    try {
      const d = await api.get<DispatchData>(`/dispatch/data?date=${date}`)
      setData(d)
      setLastRefresh(new Date())
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  useEffect(() => {
    fetchData()
    intervalRef.current = setInterval(fetchData, 30000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [date])

  async function acceptAll() {
    setAccepting(true)
    try {
      await api.post('/dispatch/firstalt/accept-today')
      await fetchData()
    } catch (e) { console.error(e) }
    finally { setAccepting(false) }
  }

  const allDrivers = data?.drivers || []
  const unassigned = data?.unassigned || []

  // Filter drivers AND their trips by selected source tab
  const filtered = source === 'all' ? allDrivers : allDrivers.map(d => {
    const filteredTrips = (d.trips || []).filter(t => {
      const src = (t._source || '').toLowerCase()
      return source === 'fa' ? (src.includes('first') || src.includes('acumen') || src === 'firstalt') : (src.includes('ever') || src === 'everdriven')
    })
    return filteredTrips.length > 0 ? { ...d, trips: filteredTrips } : null
  }).filter(Boolean) as DriverDispatch[]

  // Compute stats from filtered trips
  const allTrips = filtered.flatMap(d => d.trips || [])
  const stats = source === 'all' ? (data?.dashboard || {}) : {
    total: allTrips.length,
    completed: allTrips.filter(t => { const s = (t.tripStatus || t.status || '').toLowerCase(); return s.includes('complete') }).length,
    active: allTrips.filter(t => { const s = (t.tripStatus || t.status || '').toLowerCase(); return s.includes('active') || s.includes('start') }).length,
    scheduled: allTrips.filter(t => { const s = (t.tripStatus || t.status || '').toLowerCase(); return s.includes('scheduled') || s.includes('accepted') }).length,
    cancelled: allTrips.filter(t => { const s = (t.tripStatus || t.status || '').toLowerCase(); return s.includes('cancel') }).length,
  }

  if (loading) return <LoadingSpinner fullPage />

  const faError = data?.fa_error
  const edError = data?.ed_error

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      {/* API status banners */}
      {(faError || edError) && (
        <div className="flex flex-col gap-2">
          {faError && (
            <div className="px-4 py-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-sm text-red-400">
              <span className="font-medium">FirstAlt API error:</span> {faError}
            </div>
          )}
          {edError && (
            <div className="px-4 py-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-sm text-red-400">
              <span className="font-medium">EverDriven API error:</span> {edError}
            </div>
          )}
        </div>
      )}
      {/* Sticky header */}
      <div className="sticky top-14 z-30 -mx-4 px-4 py-3 dark:bg-[#0f1219]/90 bg-[#f0f2f8]/90 backdrop-blur-xl border-b dark:border-white/8 border-gray-200">
        <div className="flex flex-wrap items-center gap-3 max-w-7xl mx-auto">
          <input
            type="date"
            value={date}
            onChange={e => setDate(e.target.value)}
            className="px-3 py-1.5 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
          />
          {/* Source tabs */}
          <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
            {[['all', 'All'], ['fa', 'FirstAlt'], ['ed', 'EverDriven']].map(([v, l]) => (
              <button key={v} onClick={() => setSource(v)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-all cursor-pointer ${source === v ? 'bg-[#667eea] text-white' : 'dark:text-white/50 text-gray-500'}`}>
                {l}
              </button>
            ))}
          </div>
          {/* Stat badges */}
          <div className="flex gap-2 flex-wrap">
            {[
              { l: 'Total', v: stats.total || 0, c: 'dark:bg-white/10 bg-gray-200 dark:text-white/60 text-gray-600' },
              { l: 'Done', v: stats.completed || 0, c: 'bg-emerald-500/15 text-emerald-400' },
              { l: 'Active', v: stats.active || 0, c: 'bg-blue-500/15 text-blue-400' },
              { l: 'Scheduled', v: stats.scheduled || 0, c: 'bg-amber-500/15 text-amber-400' },
              { l: 'Cancelled', v: stats.cancelled || 0, c: 'bg-red-500/15 text-red-400' },
            ].map(s => (
              <span key={s.l} className={`px-2 py-1 rounded-lg text-xs font-medium ${s.c}`}>{s.l}: {s.v}</span>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-3">
            <span className="text-xs dark:text-white/30 text-gray-400">
              Refreshed {lastRefresh.toLocaleTimeString()}
            </span>
            <button onClick={fetchData} className="p-1.5 rounded-lg dark:hover:bg-white/8 hover:bg-gray-100 transition-all cursor-pointer">
              <RefreshCw className="w-3.5 h-3.5 dark:text-white/40 text-gray-500" />
            </button>
          </div>
        </div>
      </div>

      {/* Driver grid */}
      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
        {filtered.map((driver, i) => {
          // Badge: on a specific tab, use that tab's badge. On "all", determine from trip sources
          const tripSources = (driver.trips || []).map(t => (t._source || '').toLowerCase())
          const hasFa = tripSources.some(s => s.includes('first') || s.includes('acumen') || s === 'firstalt')
          const hasEd = tripSources.some(s => s.includes('ever') || s === 'everdriven')
          const isFa = source === 'fa' ? true : source === 'ed' ? false : (hasFa && !hasEd) || (!hasEd)
          const isBoth = source === 'all' && hasFa && hasEd
          return (
            <motion.div
              key={driver.person_id || i}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
              className="rounded-2xl dark:bg-white/5 dark:border dark:border-white/10 bg-white border border-gray-200 overflow-hidden"
            >
              <div className="p-4 border-b dark:border-white/8 border-gray-100 flex items-center justify-between">
                <div>
                  <p className="font-semibold dark:text-white text-gray-800 text-sm">{driver.name || '—'}</p>
                  <p className="text-xs dark:text-white/40 text-gray-400">{driver.phone || '—'}</p>
                </div>
                {isBoth ? (
                  <div className="flex gap-1">
                    <Badge variant="fa">FA</Badge>
                    <Badge variant="ed">ED</Badge>
                  </div>
                ) : (
                  <Badge variant={isFa ? 'fa' : 'ed'}>{isFa ? 'FA' : 'ED'}</Badge>
                )}
              </div>
              <div className="divide-y dark:divide-white/5 divide-gray-50">
                {(driver.trips || []).length === 0 ? (
                  <p className="px-4 py-3 text-xs dark:text-white/30 text-gray-400 italic">No trips today</p>
                ) : (
                  (driver.trips || []).map((trip, j) => {
                    const tripStatus = trip.tripStatus || trip.status || 'Scheduled'
                    const pickupTime = trip.firstPickUp
                    const svcName = trip.serviceName || trip.service_name || trip.name || trip.service_code || '—'
                    return (
                      <div key={trip.id || j} className={`px-4 py-2.5 flex items-center justify-between border-l-2 ${statusColor(tripStatus)}`}>
                        <div>
                          <p className="text-xs font-medium dark:text-white/80 text-gray-700">{formatTime(pickupTime)}</p>
                          <p className="text-xs dark:text-white/40 text-gray-400 mt-0.5 truncate max-w-[180px]">{svcName}</p>
                        </div>
                        <span className={`text-xs px-2 py-0.5 rounded-full border ${statusColor(tripStatus)}`}>{tripStatus}</span>
                      </div>
                    )
                  })
                )}
              </div>
            </motion.div>
          )
        })}
      </div>

      {/* Unassigned */}
      {unassigned.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-amber-400 uppercase tracking-wide mb-3 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            Unassigned Trips ({unassigned.length})
          </h2>
          <div className="rounded-2xl border-2 border-amber-500/30 bg-amber-500/5 divide-y dark:divide-amber-500/10 divide-amber-100">
            {unassigned.map((trip, i) => (
              <div key={trip.id || i} className="px-4 py-3 flex items-center justify-between">
                <div>
                  <p className="text-sm dark:text-white/80 text-gray-700">{formatTime(trip.firstPickUp)}</p>
                  <p className="text-xs text-amber-400/70">{trip.serviceName || trip.service_name || trip.name || trip.service_code || '—'}</p>
                </div>
                <span className="text-xs text-amber-400">{trip.tripStatus || trip.status || 'Unassigned'}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {filtered.length === 0 && unassigned.length === 0 && (
        <div className="text-center py-16 dark:text-white/30 text-gray-400">
          <p>No dispatch data for {date}</p>
        </div>
      )}
    </div>
  )
}
