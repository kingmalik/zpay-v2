'use client'

import { useEffect, useState } from 'react'
import { useTheme } from 'next-themes'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { DollarSign, TrendingUp, Car, Percent } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatPercent } from '@/lib/utils'
import StatCard from '@/components/ui/StatCard'
import GlassCard from '@/components/ui/GlassCard'
import FilterBar from '@/components/ui/FilterBar'
import DataTable, { Column } from '@/components/ui/DataTable'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface AnalyticsData {
  summary?: { revenue?: number; driver_cost?: number; profit?: number; margin?: number; rides?: number; avg_profit_per_ride?: number }
  company_breakdown?: { company?: string; revenue?: number; cost?: number; profit?: number; rides?: number }[]
  route_profitability?: { service?: string; rides?: number; revenue?: number; profit?: number; margin?: number }[]
  top_rides?: { date?: string; driver?: string; service?: string; net_pay?: number; profit?: number }[]
  bottom_rides?: { date?: string; driver?: string; service?: string; net_pay?: number; profit?: number }[]
  driver_profitability?: { driver?: string; rides?: number; revenue?: number; cost?: number; profit?: number; margin?: number }[]
  profit_by_period?: { period?: string; fa_profit?: number; ed_profit?: number; total?: number }[]
}

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [company, setCompany] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === 'dark'

  useEffect(() => {
    api.get<AnalyticsData>('/api/data/analytics').then(setData).catch(console.error).finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  const s = data?.summary || {}
  const axisColor = isDark ? 'rgba(255,255,255,0.3)' : '#9CA3AF'
  const gridColor = isDark ? 'rgba(255,255,255,0.06)' : '#F3F4F6'
  const tooltipBg = isDark ? '#1a2030' : '#fff'

  const routeCols: Column<NonNullable<AnalyticsData['route_profitability']>[0]> = {
    key: 'service', label: 'Route',
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Analytics</h1>
        <FilterBar company={company} onCompanyChange={setCompany} showDates dateFrom={dateFrom} dateTo={dateTo} onDateFromChange={setDateFrom} onDateToChange={setDateTo} />
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        <StatCard label="Revenue" value={formatCurrency(s.revenue)} icon={<DollarSign className="w-4 h-4" />} index={0} />
        <StatCard label="Driver Cost" value={formatCurrency(s.driver_cost)} color="warning" index={1} />
        <StatCard label="Profit" value={formatCurrency(s.profit)} color={(s.profit || 0) >= 0 ? 'success' : 'danger'} index={2} />
        <StatCard label="Margin" value={formatPercent(s.margin)} color="info" icon={<Percent className="w-4 h-4" />} index={3} />
        <StatCard label="Rides" value={s.rides || 0} icon={<Car className="w-4 h-4" />} index={4} />
        <StatCard label="Avg Profit/Ride" value={formatCurrency(s.avg_profit_per_ride)} color="success" index={5} />
      </div>

      {/* Company breakdown */}
      {(data?.company_breakdown || []).length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {(data?.company_breakdown || []).map((c, i) => {
            const isFa = (c.company || '').toLowerCase().includes('first')
            return (
              <GlassCard key={i}>
                <div className="flex items-center gap-2 mb-4">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${isFa ? 'bg-indigo-500/15 text-indigo-400' : 'bg-cyan-500/15 text-cyan-400'}`}>{c.company}</span>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  {[['Revenue', formatCurrency(c.revenue)], ['Driver Cost', formatCurrency(c.cost)], ['Profit', formatCurrency(c.profit)], ['Rides', String(c.rides || 0)]].map(([l, v]) => (
                    <div key={l}><p className="text-xs dark:text-white/40 text-gray-400">{l}</p><p className="font-semibold text-sm dark:text-white text-gray-800">{v}</p></div>
                  ))}
                </div>
              </GlassCard>
            )
          })}
        </div>
      )}

      {/* Profit by period chart */}
      {(data?.profit_by_period || []).length > 0 && (
        <GlassCard>
          <h3 className="text-sm font-semibold dark:text-white/80 text-gray-700 mb-4">Profit by Period</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data?.profit_by_period} barSize={14}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
              <XAxis dataKey="period" tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: axisColor, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
              <Tooltip contentStyle={{ background: tooltipBg, border: 'none', borderRadius: 12, fontSize: 12 }} formatter={(v) => formatCurrency(v as number)} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="fa_profit" name="FirstAlt" fill="#667eea" radius={[4, 4, 0, 0]} />
              <Bar dataKey="ed_profit" name="EverDriven" fill="#06b6d4" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </GlassCard>
      )}

      {/* Route profitability */}
      <GlassCard padding={false}>
        <div className="p-4 border-b dark:border-white/8 border-gray-100">
          <h3 className="font-semibold dark:text-white text-gray-800">Route Profitability</h3>
        </div>
        <DataTable
          columns={[
            { key: 'service', label: 'Route', sortable: true },
            { key: 'rides', label: 'Rides', sortable: true },
            { key: 'revenue', label: 'Revenue', sortable: true, render: r => formatCurrency(r.revenue) },
            { key: 'profit', label: 'Profit', sortable: true, render: r => <span className={r.profit && r.profit >= 0 ? 'text-emerald-500' : 'text-red-400'}>{formatCurrency(r.profit)}</span> },
            { key: 'margin', label: 'Margin', render: r => formatPercent(r.margin) },
          ]}
          data={data?.route_profitability || []}
          keyField="service"
          emptyTitle="No route data"
        />
      </GlassCard>

      {/* Top/Bottom rides */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/8 border-gray-100">
            <h3 className="font-semibold text-emerald-400 text-sm">Top 10 Most Profitable Rides</h3>
          </div>
          <DataTable
            columns={[
              { key: 'driver', label: 'Driver' },
              { key: 'service', label: 'Service', mobileHide: true },
              { key: 'profit', label: 'Profit', render: r => <span className="text-emerald-500">{formatCurrency(r.profit)}</span> },
            ]}
            data={(data?.top_rides || []).slice(0, 10)}
            keyField="driver"
            emptyTitle="No data"
          />
        </GlassCard>
        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/8 border-gray-100">
            <h3 className="font-semibold text-red-400 text-sm">Bottom 10 Least Profitable Rides</h3>
          </div>
          <DataTable
            columns={[
              { key: 'driver', label: 'Driver' },
              { key: 'service', label: 'Service', mobileHide: true },
              { key: 'profit', label: 'Profit', render: r => <span className="text-red-400">{formatCurrency(r.profit)}</span> },
            ]}
            data={(data?.bottom_rides || []).slice(0, 10)}
            keyField="driver"
            emptyTitle="No data"
          />
        </GlassCard>
      </div>

      {/* Driver profitability */}
      <GlassCard padding={false}>
        <div className="p-4 border-b dark:border-white/8 border-gray-100">
          <h3 className="font-semibold dark:text-white text-gray-800">Driver Profitability</h3>
        </div>
        <DataTable
          columns={[
            { key: 'driver', label: 'Driver', sortable: true },
            { key: 'rides', label: 'Rides', sortable: true },
            { key: 'revenue', label: 'Revenue', sortable: true, render: r => formatCurrency(r.revenue) },
            { key: 'cost', label: 'Cost', render: r => formatCurrency(r.cost) },
            { key: 'profit', label: 'Profit', sortable: true, render: r => <span className={r.profit && r.profit >= 0 ? 'text-emerald-500' : 'text-red-400'}>{formatCurrency(r.profit)}</span> },
            { key: 'margin', label: 'Margin', render: r => formatPercent(r.margin) },
          ]}
          data={data?.driver_profitability || []}
          keyField="driver"
          emptyTitle="No driver data"
        />
      </GlassCard>
    </div>
  )
}
