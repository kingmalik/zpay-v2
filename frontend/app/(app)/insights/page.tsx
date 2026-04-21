'use client'

import { useEffect, useState } from 'react'
import { Brain, TrendingUp, TrendingDown } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatPercent } from '@/lib/utils'
import StatCard from '@/components/ui/StatCard'
import GlassCard from '@/components/ui/GlassCard'
import FilterBar from '@/components/ui/FilterBar'
import DataTable from '@/components/ui/DataTable'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface InsightsData {
  summary?: { revenue?: number; cost?: number; profit?: number; margin?: number; rides?: number; drivers?: number; avg_rate?: number }
  ai_analysis?: string
  top_drivers?: { driver?: string; rides?: number; profit?: number; margin?: number }[]
  bottom_drivers?: { driver?: string; rides?: number; profit?: number }[]
  profitable_routes?: { service?: string; rides?: number; profit?: number }[]
  unprofitable_routes?: { service?: string; rides?: number; profit?: number }[]
  recent_periods?: { period?: string; revenue?: number; profit?: number; rides?: number }[]
}

export default function InsightsPage() {
  const [data, setData] = useState<InsightsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [company, setCompany] = useState('all')

  useEffect(() => {
    api.get<InsightsData>('/api/data/insights').then(setData).catch(console.error).finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  const s = data?.summary || {}

  return (
    <div className="max-w-7xl mx-auto space-y-6 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Insights</h1>
        <FilterBar company={company} onCompanyChange={setCompany} />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-7 gap-3">
        <StatCard label="Revenue" value={formatCurrency(s.revenue)} index={0} />
        <StatCard label="Cost" value={formatCurrency(s.cost)} color="warning" index={1} />
        <StatCard label="Profit" value={formatCurrency(s.profit)} color={(s.profit || 0) >= 0 ? 'success' : 'danger'} index={2} />
        <StatCard label="Margin" value={formatPercent(s.margin)} color="info" index={3} />
        <StatCard label="Rides" value={s.rides || 0} index={4} />
        <StatCard label="Drivers" value={s.drivers || 0} index={5} />
        <StatCard label="Avg Rate" value={formatCurrency(s.avg_rate)} color="success" index={6} />
      </div>

      {/* AI Analysis */}
      {data?.ai_analysis && (
        <div className="rounded-2xl p-5" style={{ background: 'linear-gradient(135deg, rgba(102,126,234,0.1), rgba(6,182,212,0.05))', border: '1px solid rgba(102,126,234,0.3)' }}>
          <div className="flex items-center gap-2 mb-3">
            <Brain className="w-5 h-5 text-[#667eea]" />
            <h3 className="font-semibold dark:text-white text-gray-800">AI Analysis</h3>
          </div>
          <p className="text-sm dark:text-white/70 text-gray-600 leading-relaxed whitespace-pre-wrap">{data.ai_analysis}</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/8 border-gray-100 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-emerald-400" />
            <h3 className="font-semibold text-emerald-400 text-sm">Most Profitable Drivers</h3>
          </div>
          <DataTable
            columns={[
              { key: 'driver', label: 'Driver' },
              { key: 'rides', label: 'Rides' },
              { key: 'profit', label: 'Profit', render: r => <span className="text-emerald-500">{formatCurrency(r.profit)}</span> },
              { key: 'margin', label: 'Margin', render: r => formatPercent(r.margin), mobileHide: true },
            ]}
            data={data?.top_drivers || []}
            keyField="driver"
            emptyTitle="No data"
          />
        </GlassCard>

        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/8 border-gray-100 flex items-center gap-2">
            <TrendingDown className="w-4 h-4 text-red-400" />
            <h3 className="font-semibold text-red-400 text-sm">Least Profitable Drivers</h3>
          </div>
          <DataTable
            columns={[
              { key: 'driver', label: 'Driver' },
              { key: 'rides', label: 'Rides' },
              { key: 'profit', label: 'Profit', render: r => <span className="text-red-400">{formatCurrency(r.profit)}</span> },
            ]}
            data={data?.bottom_drivers || []}
            keyField="driver"
            emptyTitle="No data"
          />
        </GlassCard>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/8 border-gray-100">
            <h3 className="font-semibold dark:text-white/80 text-sm">Most Profitable Routes</h3>
          </div>
          <DataTable
            columns={[
              { key: 'service', label: 'Route' },
              { key: 'rides', label: 'Rides' },
              { key: 'profit', label: 'Profit', render: r => <span className="text-emerald-500">{formatCurrency(r.profit)}</span> },
            ]}
            data={data?.profitable_routes || []}
            keyField="service"
            emptyTitle="No data"
          />
        </GlassCard>

        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/8 border-gray-100">
            <h3 className="font-semibold dark:text-white/80 text-sm">Least Profitable Routes</h3>
          </div>
          <DataTable
            columns={[
              { key: 'service', label: 'Route' },
              { key: 'rides', label: 'Rides' },
              { key: 'profit', label: 'Profit', render: r => <span className="text-red-400">{formatCurrency(r.profit)}</span> },
            ]}
            data={data?.unprofitable_routes || []}
            keyField="service"
            emptyTitle="No data"
          />
        </GlassCard>
      </div>

      {/* Recent periods */}
      <GlassCard padding={false}>
        <div className="p-4 border-b dark:border-white/8 border-gray-100">
          <h3 className="font-semibold dark:text-white text-gray-800">Recent Periods</h3>
        </div>
        <DataTable
          columns={[
            { key: 'period', label: 'Period', sortable: true },
            { key: 'rides', label: 'Rides', sortable: true },
            { key: 'revenue', label: 'Revenue', render: r => formatCurrency(r.revenue) },
            { key: 'profit', label: 'Profit', sortable: true, render: r => <span className={r.profit && r.profit >= 0 ? 'text-emerald-500' : 'text-red-400'}>{formatCurrency(r.profit)}</span> },
          ]}
          data={data?.recent_periods || []}
          keyField="period"
          emptyTitle="No period data"
        />
      </GlassCard>
    </div>
  )
}
