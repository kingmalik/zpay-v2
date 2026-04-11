'use client'

import { useEffect, useState, useMemo } from 'react'
import { useTheme } from 'next-themes'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts'
import { ChevronUp, ChevronDown, ChevronsUpDown, TrendingUp, Wifi } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatPercent } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

/* ─── Types ─────────────────────────────────────────────────────────── */

interface AnalyticsData {
  summary?: { revenue?: number; driver_cost?: number; profit?: number; margin?: number; rides?: number; avg_profit_per_ride?: number }
  company_breakdown?: { company?: string; revenue?: number; cost?: number; profit?: number; rides?: number }[]
  route_profitability?: { service?: string; rides?: number; revenue?: number; profit?: number; margin?: number }[]
  top_rides?: { date?: string; driver?: string; service?: string; net_pay?: number; profit?: number }[]
  bottom_rides?: { date?: string; driver?: string; service?: string; net_pay?: number; profit?: number }[]
  driver_profitability?: { driver?: string; rides?: number; revenue?: number; cost?: number; profit?: number; margin?: number }[]
  profit_by_period?: { period?: string; fa_profit?: number; ed_profit?: number; total?: number }[]
}

interface Driver {
  id: string | number
  name?: string
  rides?: number
  on_time_rate?: number
  cancel_rate?: number
}

type SortDir = 'asc' | 'desc' | null

/* ─── Helpers ────────────────────────────────────────────────────────── */

function reliabilityScore(onTime = 95, cancel = 2): number {
  return Math.max(0, Math.min(100, Math.round(100 - cancel * 5)))
}

function scoreColor(score: number): string {
  if (score > 85) return 'text-emerald-400'
  if (score >= 70) return 'text-amber-400'
  return 'text-red-400'
}

function scoreBg(score: number): string {
  if (score > 85) return 'bg-emerald-500/10 border-emerald-500/20'
  if (score >= 70) return 'bg-amber-500/10 border-amber-500/20'
  return 'bg-red-500/10 border-red-500/20'
}

function profitStatusBadge(margin: number): React.ReactElement {
  if (margin > 5) return (
    <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Profitable</span>
  )
  if (margin >= -2) return (
    <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">Break-even</span>
  )
  return (
    <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-red-500/10 text-red-400 border border-red-500/20">Loss</span>
  )
}

/* ─── Sort Icon ──────────────────────────────────────────────────────── */
function SortIcon({ dir }: { dir: SortDir }) {
  if (dir === 'asc') return <ChevronUp className="w-3.5 h-3.5 inline ml-1 opacity-80" />
  if (dir === 'desc') return <ChevronDown className="w-3.5 h-3.5 inline ml-1 opacity-80" />
  return <ChevronsUpDown className="w-3.5 h-3.5 inline ml-1 opacity-30" />
}

/* ─── Tabs ───────────────────────────────────────────────────────────── */
const TABS = ['Overview', 'Driver Scorecard', 'Ride Profitability'] as const
type Tab = typeof TABS[number]

/* ─── TAB: Overview ─────────────────────────────────────────────────── */
function OverviewTab({ data }: { data: AnalyticsData | null }) {
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === 'dark'
  const axisColor = isDark ? 'rgba(255,255,255,0.3)' : '#9CA3AF'
  const gridColor = isDark ? 'rgba(255,255,255,0.06)' : '#F3F4F6'
  const tooltipBg = isDark ? '#18181b' : '#fff'
  const tooltipBorder = isDark ? 'rgba(255,255,255,0.08)' : '#e5e7eb'

  const revenueVsCostData = useMemo(() => {
    if (!data?.company_breakdown?.length) return []
    return data.company_breakdown.map(c => ({
      name: c.company || '',
      Revenue: c.revenue || 0,
      Cost: c.cost || 0,
      Profit: c.profit || 0,
    }))
  }, [data])

  const marginTrendData = useMemo(() => {
    if (!data?.profit_by_period?.length) return []
    return data.profit_by_period.map(p => {
      const rev = (p.fa_profit ?? 0) + (p.ed_profit ?? 0) + Math.abs(p.total ?? 0)
      const margin = rev > 0 ? Math.round(((p.total ?? 0) / rev) * 100) : 0
      return { name: p.period || '', margin }
    })
  }, [data])

  return (
    <div className="space-y-6">
      {/* Revenue vs Cost grouped bar */}
      <GlassCard>
        <h3 className="text-sm font-semibold dark:text-white/80 text-gray-700 mb-4">Revenue vs Cost — FA &amp; ED</h3>
        {revenueVsCostData.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={revenueVsCostData} barSize={28}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
              <XAxis dataKey="name" tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
              <Tooltip contentStyle={{ background: tooltipBg, border: `1px solid ${tooltipBorder}`, borderRadius: 10, fontSize: 12 }} formatter={(v) => formatCurrency(v as number)} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="Revenue" fill="#667eea" radius={[4, 4, 0, 0]} />
              <Bar dataKey="Cost" fill="#EF4444" radius={[4, 4, 0, 0]} fillOpacity={0.7} />
              <Bar dataKey="Profit" fill="#10B981" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[220px] flex items-center justify-center text-sm dark:text-white/30 text-gray-400">
            Upload ride data to see revenue vs cost breakdown
          </div>
        )}
      </GlassCard>

      {/* Margin % trend */}
      <GlassCard>
        <h3 className="text-sm font-semibold dark:text-white/80 text-gray-700 mb-4">Margin % Trend</h3>
        {marginTrendData.length > 0 ? (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={marginTrendData}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
              <XAxis dataKey="name" tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} />
              <Tooltip contentStyle={{ background: tooltipBg, border: `1px solid ${tooltipBorder}`, borderRadius: 10, fontSize: 12 }} formatter={(v) => `${v}%`} />
              <Line type="monotone" dataKey="margin" stroke="#667eea" strokeWidth={2} dot={{ r: 3, fill: '#667eea' }} name="Margin %" />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          /* Profit by period fallback */
          data?.profit_by_period && data.profit_by_period.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={data.profit_by_period} barSize={14}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                <XAxis dataKey="period" tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip contentStyle={{ background: tooltipBg, border: `1px solid ${tooltipBorder}`, borderRadius: 10, fontSize: 12 }} formatter={(v) => formatCurrency(v as number)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="fa_profit" name="FirstAlt" fill="#667eea" radius={[4, 4, 0, 0]} />
                <Bar dataKey="ed_profit" name="EverDriven" fill="#06b6d4" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[200px] flex items-center justify-center text-sm dark:text-white/30 text-gray-400">
              Upload ride data to see margin trends
            </div>
          )
        )}
      </GlassCard>
    </div>
  )
}

/* ─── TAB: Driver Scorecard ─────────────────────────────────────────── */
function DriverScorecardTab() {
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [loading, setLoading] = useState(true)
  const [hasRealData, setHasRealData] = useState(false)
  const [sortKey, setSortKey] = useState<keyof Driver | 'score'>('score')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  useEffect(() => {
    api.get<Driver[]>('/api/data/people')
      .then(data => {
        if (data && data.length > 0) {
          setDrivers(data)
          setHasRealData(true)
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  type Row = {
    id: string | number
    name: string
    rides: number
    on_time_rate: number
    cancel_rate: number
    score: number
  }

  const rows: Row[] = useMemo(() => {
    if (!hasRealData) return []
    return drivers.map(d => {
      const onTime = d.on_time_rate ?? 95
      const cancel = d.cancel_rate ?? 2
      return {
        id: d.id,
        name: d.name || `Driver #${d.id}`,
        rides: d.rides ?? 0,
        on_time_rate: onTime,
        cancel_rate: cancel,
        score: reliabilityScore(onTime, cancel),
      }
    })
  }, [drivers, hasRealData])

  const sorted = useMemo(() => {
    const dir = sortDir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = a[sortKey as keyof Row]
      const bv = b[sortKey as keyof Row]
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
      return String(av).localeCompare(String(bv)) * dir
    })
  }, [rows, sortKey, sortDir])

  function toggleSort(key: typeof sortKey) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  function getSortDir(key: typeof sortKey): SortDir {
    if (sortKey !== key) return null
    return sortDir
  }

  const thClass = 'px-4 py-3 text-left text-xs font-semibold dark:text-white/40 text-gray-400 uppercase tracking-wide cursor-pointer select-none hover:dark:text-white/70 hover:text-gray-600 transition-colors'

  if (loading) return <div className="flex justify-center py-16"><LoadingSpinner /></div>

  return (
    <div className="space-y-4">
      {!hasRealData && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl dark:bg-white/[0.04] bg-blue-50 border dark:border-white/[0.08] border-blue-200 w-fit">
          <Wifi className="w-3.5 h-3.5 text-blue-400" />
          <span className="text-xs text-blue-400 font-medium">Live data syncing</span>
          <span className="text-xs dark:text-white/40 text-blue-300">— scores use defaults until ride data is uploaded</span>
        </div>
      )}

      <GlassCard padding={false}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px]">
            <thead>
              <tr className="border-b dark:border-white/[0.08] border-gray-100">
                <th className={thClass} onClick={() => toggleSort('name')}>
                  Driver <SortIcon dir={getSortDir('name')} />
                </th>
                <th className={thClass} onClick={() => toggleSort('rides')}>
                  Total Rides <SortIcon dir={getSortDir('rides')} />
                </th>
                <th className={thClass} onClick={() => toggleSort('on_time_rate')}>
                  On-Time Rate <SortIcon dir={getSortDir('on_time_rate')} />
                </th>
                <th className={thClass} onClick={() => toggleSort('cancel_rate')}>
                  Cancel Rate <SortIcon dir={getSortDir('cancel_rate')} />
                </th>
                <th className={thClass} onClick={() => toggleSort('score')}>
                  Reliability Score <SortIcon dir={getSortDir('score')} />
                </th>
              </tr>
            </thead>
            <tbody>
              {hasRealData ? sorted.map((row, i) => (
                <tr key={row.id} className={`border-b dark:border-white/[0.05] border-gray-50 dark:hover:bg-white/[0.03] hover:bg-gray-50 transition-colors ${i % 2 === 0 ? '' : 'dark:bg-white/[0.01]'}`}>
                  <td className="px-4 py-3 text-sm font-medium dark:text-white text-gray-800">{row.name}</td>
                  <td className="px-4 py-3 text-sm dark:text-white/70 text-gray-600">{row.rides || '—'}</td>
                  <td className="px-4 py-3 text-sm dark:text-white/70 text-gray-600">{row.on_time_rate ? `${row.on_time_rate}%` : '—'}</td>
                  <td className="px-4 py-3 text-sm dark:text-white/70 text-gray-600">{row.cancel_rate !== undefined ? `${row.cancel_rate}%` : '—'}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${scoreBg(row.score)} ${scoreColor(row.score)}`}>
                      {row.score}
                    </span>
                  </td>
                </tr>
              )) : (
                /* Placeholder rows */
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="border-b dark:border-white/[0.05] border-gray-50">
                    <td className="px-4 py-3 text-sm dark:text-white/30 text-gray-300">—</td>
                    <td className="px-4 py-3 text-sm dark:text-white/30 text-gray-300">—</td>
                    <td className="px-4 py-3 text-sm dark:text-white/30 text-gray-300">—</td>
                    <td className="px-4 py-3 text-sm dark:text-white/30 text-gray-300">—</td>
                    <td className="px-4 py-3 text-sm dark:text-white/30 text-gray-300">—</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {hasRealData && sorted.length === 0 && (
          <div className="py-10 text-center text-sm dark:text-white/30 text-gray-400">No driver data available</div>
        )}
      </GlassCard>
    </div>
  )
}

/* ─── TAB: Ride Profitability ───────────────────────────────────────── */
function RideProfitabilityTab({ data }: { data: AnalyticsData | null }) {
  const [sortKey, setSortKey] = useState<'margin' | 'revenue' | 'profit' | 'service'>('margin')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  type RouteRow = NonNullable<AnalyticsData['route_profitability']>[0]

  const rows = data?.route_profitability || []

  const sorted = useMemo(() => {
    const dir = sortDir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      if (sortKey === 'service') return String(a.service).localeCompare(String(b.service)) * dir
      return ((a[sortKey] ?? 0) - (b[sortKey] ?? 0)) * dir
    })
  }, [rows, sortKey, sortDir])

  function toggleSort(key: typeof sortKey) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  function getSortDir(key: typeof sortKey): SortDir {
    return sortKey === key ? sortDir : null
  }

  const thClass = 'px-4 py-3 text-left text-xs font-semibold dark:text-white/40 text-gray-400 uppercase tracking-wide cursor-pointer select-none hover:dark:text-white/70 hover:text-gray-600 transition-colors'

  if (rows.length === 0) {
    return (
      <div className="rounded-2xl dark:bg-white/[0.04] bg-white border dark:border-white/[0.08] border-gray-200 p-16 text-center space-y-2">
        <TrendingUp className="w-8 h-8 dark:text-white/15 text-gray-300 mx-auto" />
        <p className="text-sm font-medium dark:text-white/40 text-gray-500">Upload ride data to see profitability analysis</p>
        <p className="text-xs dark:text-white/25 text-gray-400">Route-level margins will appear here after uploading FA or ED files</p>
      </div>
    )
  }

  return (
    <GlassCard padding={false}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px]">
          <thead>
            <tr className="border-b dark:border-white/[0.08] border-gray-100">
              <th className={thClass} onClick={() => toggleSort('service')}>
                Route <SortIcon dir={getSortDir('service')} />
              </th>
              <th className={thClass} onClick={() => toggleSort('revenue')}>
                Revenue <SortIcon dir={getSortDir('revenue')} />
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold dark:text-white/40 text-gray-400 uppercase tracking-wide">
                Driver Cost
              </th>
              <th className={thClass} onClick={() => toggleSort('margin')}>
                Margin % <SortIcon dir={getSortDir('margin')} />
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold dark:text-white/40 text-gray-400 uppercase tracking-wide">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => {
              const margin = row.margin ?? 0
              const cost = (row.revenue ?? 0) - (row.profit ?? 0)
              return (
                <tr
                  key={row.service || i}
                  className={`border-b dark:border-white/[0.05] border-gray-50 dark:hover:bg-white/[0.03] hover:bg-gray-50 transition-colors ${i % 2 === 0 ? '' : 'dark:bg-white/[0.01]'}`}
                >
                  <td className="px-4 py-3 text-sm font-medium dark:text-white text-gray-800">{row.service || '—'}</td>
                  <td className="px-4 py-3 text-sm dark:text-white/70 text-gray-600">{formatCurrency(row.revenue)}</td>
                  <td className="px-4 py-3 text-sm dark:text-white/70 text-gray-600">{formatCurrency(cost)}</td>
                  <td className="px-4 py-3 text-sm font-medium">
                    <span className={margin > 5 ? 'text-emerald-400' : margin >= -2 ? 'text-amber-400' : 'text-red-400'}>
                      {formatPercent(margin)}
                    </span>
                  </td>
                  <td className="px-4 py-3">{profitStatusBadge(margin)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </GlassCard>
  )
}

/* ─── Main Page ──────────────────────────────────────────────────────── */

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<Tab>('Overview')

  useEffect(() => {
    api.get<AnalyticsData>('/api/data/analytics')
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-7xl mx-auto space-y-6 py-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Analytics</h1>
        <p className="text-sm dark:text-white/50 text-gray-400 mt-0.5">Revenue, driver performance, and profitability insights</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 p-1 rounded-xl dark:bg-white/[0.05] bg-gray-100 w-fit">
        {TABS.map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150 cursor-pointer ${
              activeTab === tab
                ? 'bg-[#667eea] text-white shadow-sm'
                : 'dark:text-white/50 text-gray-500 dark:hover:text-white/80 hover:text-gray-700'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.15, ease: 'easeOut' }}
        >
          {activeTab === 'Overview' && <OverviewTab data={data} />}
          {activeTab === 'Driver Scorecard' && <DriverScorecardTab />}
          {activeTab === 'Ride Profitability' && <RideProfitabilityTab data={data} />}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
