'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { motion } from 'framer-motion'
import {
  DollarSign, TrendingUp, Car, Users,
  Upload, FileText, ArrowRight, RefreshCw
} from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts'
import { useTheme } from 'next-themes'
import { api } from '@/lib/api'
import { formatCurrency, formatPercent, formatNumber } from '@/lib/utils'
import StatCard from '@/components/ui/StatCard'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface DashboardData {
  revenue?: number
  cost?: number
  profit?: number
  rides?: number
  margin?: number
  fa?: { revenue?: number; profit?: number; rides?: number; cost?: number }
  ed?: { revenue?: number; profit?: number; rides?: number; cost?: number }
  weekly_data?: { week?: string; label?: string; fa_revenue?: number; ed_revenue?: number; fa_rides?: number; ed_rides?: number; profit?: number }[]
}

const QUICK_ACTIONS = [
  { label: 'Run Payroll', desc: 'Generate payroll summary', href: '/payroll', icon: <FileText className="w-5 h-5" />, color: '#667eea' },
  { label: 'Upload Files', desc: 'Import FA or ED data', href: '/upload', icon: <Upload className="w-5 h-5" />, color: '#06b6d4' },
  { label: 'Driver Directory', desc: 'View & edit all drivers', href: '/people', icon: <Users className="w-5 h-5" />, color: '#10B981' },
]

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [chartLoading, setChartLoading] = useState(false)
  const [error, setError] = useState('')
  const [chartView, setChartView] = useState<'weekly' | 'monthly'>('weekly')
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === 'dark'

  function fetchData(view = chartView) {
    return api.get<DashboardData>(`/api/data/dashboard?view=${view}`)
      .then(setData)
      .catch(e => setError(e.message))
  }

  useEffect(() => {
    fetchData('weekly').finally(() => setLoading(false))
  }, [])

  async function switchView(v: 'weekly' | 'monthly') {
    if (v === chartView) return
    setChartView(v)
    setChartLoading(true)
    await fetchData(v)
    setChartLoading(false)
  }

  if (loading) return <LoadingSpinner fullPage />
  if (error) return (
    <div className="flex items-center justify-center min-h-[400px]">
      <p className="text-red-400 text-sm">{error}</p>
    </div>
  )

  const d = data || {}
  const chartData = (d.weekly_data || []).map(w => ({
    name: w.label || w.week || '',
    'FA Revenue': w.fa_revenue || 0,
    'ED Revenue': w.ed_revenue || 0,
    'FA Rides': w.fa_rides || 0,
    'ED Rides': w.ed_rides || 0,
    profit: w.profit || 0,
  }))

  const axisColor = isDark ? 'rgba(255,255,255,0.3)' : '#9CA3AF'
  const gridColor = isDark ? 'rgba(255,255,255,0.06)' : '#F3F4F6'
  const tooltipBg = isDark ? '#1a2030' : '#fff'

  return (
    <div className="max-w-7xl mx-auto space-y-6 py-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold dark:text-white text-gray-900">Dashboard</h1>
          <p className="text-sm dark:text-white/50 text-gray-400 mt-0.5">
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}
          </p>
        </div>
        <button
          onClick={() => { setLoading(true); fetchData().finally(() => setLoading(false)) }}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm dark:text-white/50 text-gray-500 dark:hover:bg-white/8 hover:bg-gray-100 transition-all cursor-pointer"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Revenue" value={formatCurrency(d.revenue)} icon={<DollarSign className="w-4 h-4" />} color="default" index={0} />
        <StatCard label="Driver Cost" value={formatCurrency(d.cost)} icon={<TrendingUp className="w-4 h-4" />} color="warning" index={1} />
        <StatCard
          label="Net Profit"
          value={formatCurrency(d.profit)}
          icon={<TrendingUp className="w-4 h-4" />}
          color={(d.profit ?? 0) >= 0 ? 'success' : 'danger'}
          index={2}
        />
        <StatCard label="Total Rides" value={`${formatNumber(d.rides)} rides`} icon={<Car className="w-4 h-4" />} color="info" index={3} />
      </div>

      {/* Margin badge + FA/ED comparison */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <GlassCard className="flex flex-col justify-center items-center py-8">
          <p className="text-sm dark:text-white/50 text-gray-500 mb-2">Overall Margin</p>
          <p className="text-4xl font-bold gradient-text">{formatPercent(d.margin)}</p>
          <p className="text-xs dark:text-white/30 text-gray-400 mt-2">Revenue − Cost / Revenue</p>
        </GlassCard>

        <GlassCard>
          <div className="flex items-center gap-2 mb-4">
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-500/15 text-indigo-400 border border-indigo-500/30">FirstAlt</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { l: 'Revenue', v: formatCurrency(d.fa?.revenue) },
              { l: 'Profit', v: formatCurrency(d.fa?.profit) },
              { l: 'Rides', v: formatNumber(d.fa?.rides) },
              { l: 'Driver Cost', v: formatCurrency(d.fa?.cost) },
            ].map(item => (
              <div key={item.l}>
                <p className="text-xs dark:text-white/40 text-gray-400">{item.l}</p>
                <p className="text-sm font-semibold dark:text-white text-gray-800 mt-0.5">{item.v}</p>
              </div>
            ))}
          </div>
        </GlassCard>

        <GlassCard>
          <div className="flex items-center gap-2 mb-4">
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-cyan-500/15 text-cyan-400 border border-cyan-500/30">EverDriven</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { l: 'Revenue', v: formatCurrency(d.ed?.revenue) },
              { l: 'Profit', v: formatCurrency(d.ed?.profit) },
              { l: 'Rides', v: formatNumber(d.ed?.rides) },
              { l: 'Driver Cost', v: formatCurrency(d.ed?.cost) },
            ].map(item => (
              <div key={item.l}>
                <p className="text-xs dark:text-white/40 text-gray-400">{item.l}</p>
                <p className="text-sm font-semibold dark:text-white text-gray-800 mt-0.5">{item.v}</p>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>

      {/* Charts */}
      <div>
        {/* Chart header with toggle */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold dark:text-white/60 text-gray-500 uppercase tracking-wide">
            Revenue & Rides
          </h2>
          <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
            {(['weekly', 'monthly'] as const).map(v => (
              <button
                key={v}
                onClick={() => switchView(v)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-all cursor-pointer capitalize ${
                  chartView === v
                    ? 'bg-[#667eea] text-white'
                    : 'dark:text-white/50 text-gray-500 dark:hover:text-white/80 hover:text-gray-700'
                }`}
              >
                {v}
              </button>
            ))}
          </div>
        </div>

        {chartLoading ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {[0, 1].map(i => (
              <div key={i} className="rounded-2xl dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 p-5 h-[268px] flex items-center justify-center">
                <RefreshCw className="w-5 h-5 dark:text-white/20 text-gray-300 animate-spin" />
              </div>
            ))}
          </div>
        ) : chartData.length > 0 ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <GlassCard>
              <h3 className="text-sm font-semibold dark:text-white/80 text-gray-700 mb-4">
                {chartView === 'weekly' ? 'Weekly' : 'Monthly'} Revenue
              </h3>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                  <XAxis dataKey="name" tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                  <Tooltip contentStyle={{ background: tooltipBg, border: 'none', borderRadius: 12, fontSize: 12 }} formatter={(v) => formatCurrency(v as number)} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line type="monotone" dataKey="FA Revenue" stroke="#667eea" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="ED Revenue" stroke="#06b6d4" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </GlassCard>

            <GlassCard>
              <h3 className="text-sm font-semibold dark:text-white/80 text-gray-700 mb-4">
                {chartView === 'weekly' ? 'Weekly' : 'Monthly'} Rides
              </h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={chartData} barSize={chartView === 'monthly' ? 20 : 12}>
                  <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                  <XAxis dataKey="name" tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: tooltipBg, border: 'none', borderRadius: 12, fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="FA Rides" fill="#667eea" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="ED Rides" fill="#06b6d4" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </GlassCard>
          </div>
        ) : (
          <div className="rounded-2xl dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 p-10 text-center dark:text-white/30 text-gray-400 text-sm">
            No chart data available
          </div>
        )}
      </div>

      {/* Quick actions */}
      <div>
        <h2 className="text-sm font-semibold dark:text-white/60 text-gray-500 uppercase tracking-wide mb-3">Quick Actions</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {QUICK_ACTIONS.map((action, i) => (
            <motion.div key={action.href} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + i * 0.07 }}>
              <Link href={action.href}>
                <GlassCard hover className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 text-white" style={{ background: action.color }}>
                    {action.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold dark:text-white text-gray-800">{action.label}</p>
                    <p className="text-xs dark:text-white/40 text-gray-400">{action.desc}</p>
                  </div>
                  <ArrowRight className="w-4 h-4 dark:text-white/30 text-gray-300 flex-shrink-0" />
                </GlassCard>
              </Link>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  )
}
