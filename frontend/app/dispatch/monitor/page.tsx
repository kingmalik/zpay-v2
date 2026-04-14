'use client'

import { useEffect, useState, useRef } from 'react'
import { motion } from 'framer-motion'
import { Play, Pause, Zap, RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import { formatTime } from '@/lib/utils'
import StatCard from '@/components/ui/StatCard'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface MonitorData {
  active?: boolean
  paused?: boolean
  interval?: number
  last_run?: string
  stats?: {
    trips_today?: number
    unaccepted?: number
    not_started?: number
    started?: number
    sms_sent?: number
    calls_made?: number
    escalations?: number
  }
  trips?: {
    id?: string | number
    driver?: string
    source?: string
    pickup_time?: string
    status?: string
    accept_sms?: string
    accept_call?: string
    accepted_at?: string
    start_sms?: string
    start_call?: string
    started_at?: string
    escalated_at?: string
  }[]
}

function tripRowColor(status?: string): string {
  const s = (status || '').toLowerCase()
  if (s.includes('escalat')) return 'border-l-2 border-red-500/60 dark:bg-red-500/5'
  if (s.includes('start')) return 'border-l-2 border-emerald-500/60 dark:bg-emerald-500/5'
  if (s.includes('accept')) return 'border-l-2 border-blue-500/60 dark:bg-blue-500/5'
  if (s.includes('unaccept')) return 'border-l-2 border-red-500/60 dark:bg-red-500/5'
  return ''
}

export default function MonitorPage() {
  const [data, setData] = useState<MonitorData | null>(null)
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [running, setRunning] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function fetchData() {
    try {
      const d = await api.get<MonitorData>('/dispatch/monitor/data')
      setData(d)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  useEffect(() => {
    fetchData()
    intervalRef.current = setInterval(fetchData, 30000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [])

  async function toggleMonitor() {
    setToggling(true)
    try {
      await api.post('/dispatch/monitor/toggle')
      await fetchData()
    } finally { setToggling(false) }
  }

  async function runNow() {
    setRunning(true)
    try {
      await api.post('/dispatch/monitor/run-now')
      await fetchData()
    } finally { setRunning(false) }
  }

  if (loading) return <LoadingSpinner fullPage />

  const stats = data?.stats || {}
  // API returns { status: { enabled, last_run, ... }, rows, stats }
  // Fall back to legacy fields if any older response shape comes back.
  const apiStatus = (data as { status?: { enabled?: boolean } } | undefined)?.status
  const isActive = apiStatus?.enabled ?? (data?.active && !data?.paused)

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      {/* Page header */}
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">Trip Monitor</h1>
          <p className="text-sm dark:text-white/40 text-gray-500 mt-0.5">Twilio SMS/call automation for driver acceptance</p>
        </div>
        {/* Monitor status badge */}
        <div className="flex items-center gap-2">
          {isActive && <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />}
          <span className={`px-3 py-1.5 rounded-lg text-xs font-semibold border ${
            isActive
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : 'dark:bg-white/[0.04] dark:border-white/[0.08] border-gray-200 dark:text-white/40 text-gray-400'
          }`}>
            {isActive ? 'Monitor Active' : 'Monitor Inactive'}
          </span>
        </div>
      </div>

      {/* Sticky bar */}
      <div className="sticky top-14 z-30 -mx-4 px-4 py-3 dark:bg-[#0f1219]/90 bg-[#f0f2f8]/90 backdrop-blur-xl border-b dark:border-white/[0.08] border-gray-200">
        <div className="flex flex-wrap items-center gap-3 max-w-7xl mx-auto">
          <div className="flex items-center gap-2">
            {isActive && <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />}
            <span className={`px-3 py-1 rounded-full text-xs font-bold ${isActive ? 'bg-red-500/15 text-red-400 border border-red-500/30' : 'bg-gray-500/15 text-gray-400 border border-gray-500/30'}`}>
              {isActive ? 'ACTIVE' : 'PAUSED'}
            </span>
          </div>
          {data?.interval && (
            <span className="text-xs dark:text-white/40 text-gray-400">Every {data.interval}m</span>
          )}
          {data?.last_run && (
            <span className="text-xs dark:text-white/40 text-gray-400">Last run: {formatTime(data.last_run)}</span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={fetchData}
              className="p-1.5 rounded-lg dark:hover:bg-white/8 hover:bg-gray-100 transition-all cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5 dark:text-white/40 text-gray-500" />
            </button>
            <button
              onClick={runNow}
              disabled={running}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm font-medium dark:bg-white/8 bg-gray-100 dark:text-white text-gray-700 hover:dark:bg-white/12 hover:bg-gray-200 transition-all cursor-pointer disabled:opacity-60"
            >
              <Zap className="w-3.5 h-3.5" />
              Run Now
            </button>
            <button
              onClick={toggleMonitor}
              disabled={toggling}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm font-medium text-white transition-all cursor-pointer disabled:opacity-60"
              style={{ background: isActive ? '#EF4444' : 'linear-gradient(135deg, #667eea, #06b6d4)' }}
            >
              {isActive ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
              {isActive ? 'Pause' : 'Resume'}
            </button>
          </div>
        </div>
      </div>

      {(stats.unaccepted || 0) > 0 && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-sm text-red-400">
          <span className="font-medium">{stats.unaccepted} unaccepted trips</span> — monitor will attempt contact
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
        <StatCard label="Trips Today" value={stats.trips_today || 0} index={0} />
        <StatCard label="Unaccepted" value={stats.unaccepted || 0} color={(stats.unaccepted || 0) > 0 ? 'danger' : 'success'} index={1} />
        <StatCard label="Not Started" value={stats.not_started || 0} color="warning" index={2} />
        <StatCard label="Started" value={stats.started || 0} color="success" index={3} />
        <StatCard label="SMS Sent" value={stats.sms_sent || 0} color="info" index={4} />
        <StatCard label="Calls Made" value={stats.calls_made || 0} color="info" index={5} />
        <StatCard label="Escalations" value={stats.escalations || 0} color={(stats.escalations || 0) > 0 ? 'danger' : 'default'} index={6} />
      </div>

      {/* Trips table */}
      <div className="rounded-xl overflow-hidden dark:bg-white/[0.04] dark:border dark:border-white/[0.08] bg-white border border-gray-200">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b dark:border-white/[0.08] border-gray-100">
                {['Driver', 'Source', 'Pickup', 'Status', 'Accept SMS', 'Accept Call', 'Accepted', 'Start SMS', 'Start Call', 'Started', 'Escalated'].map(h => (
                  <th key={h} className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider dark:text-white/40 text-gray-400 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data?.trips || []).map((trip, i) => {
                const src = (trip.source || '').toLowerCase()
                const isFa = src.includes('first') || src.includes('fa')
                return (
                  <motion.tr
                    key={trip.id || i}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.02 }}
                    className={`border-b last:border-0 dark:border-white/[0.06] border-gray-100 dark:hover:bg-white/[0.04] hover:bg-gray-50 transition-colors ${tripRowColor(trip.status)}`}
                  >
                    <td className="px-3 py-2.5 font-medium dark:text-white/80 text-gray-700 whitespace-nowrap">{trip.driver || '—'}</td>
                    <td className="px-3 py-2.5"><Badge variant={isFa ? 'fa' : 'ed'}>{trip.source || '—'}</Badge></td>
                    <td className="px-3 py-2.5 dark:text-white/60 text-gray-600">{formatTime(trip.pickup_time)}</td>
                    <td className="px-3 py-2.5"><span className="text-xs dark:text-white/60 text-gray-600">{trip.status || '—'}</span></td>
                    <td className="px-3 py-2.5 text-emerald-400">{trip.accept_sms ? '✓' : '—'}</td>
                    <td className="px-3 py-2.5 text-emerald-400">{trip.accept_call ? '✓' : '—'}</td>
                    <td className="px-3 py-2.5 dark:text-white/50 text-gray-500">{formatTime(trip.accepted_at)}</td>
                    <td className="px-3 py-2.5 text-blue-400">{trip.start_sms ? '✓' : '—'}</td>
                    <td className="px-3 py-2.5 text-blue-400">{trip.start_call ? '✓' : '—'}</td>
                    <td className="px-3 py-2.5 dark:text-white/50 text-gray-500">{formatTime(trip.started_at)}</td>
                    <td className="px-3 py-2.5 text-red-400">{trip.escalated_at ? formatTime(trip.escalated_at) : '—'}</td>
                  </motion.tr>
                )
              })}
              {(data?.trips || []).length === 0 && (
                <tr><td colSpan={11} className="px-4 py-8 text-center text-sm dark:text-white/30 text-gray-400">No trips to monitor</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
