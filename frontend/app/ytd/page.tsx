'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import DataTable from '@/components/ui/DataTable'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface YTDData {
  totals?: { fa?: { revenue?: number; profit?: number; rides?: number; cost?: number }; ed?: { revenue?: number; profit?: number; rides?: number; cost?: number } }
  weeks?: { week?: string; fa_revenue?: number; fa_profit?: number; ed_revenue?: number; ed_profit?: number; rides?: number; cumulative_profit?: number }[]
  drivers?: { driver?: string; weeks_active?: number; rides?: number; revenue?: number; cost?: number; profit?: number }[]
}

export default function YTDPage() {
  const [data, setData] = useState<YTDData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<YTDData>('/api/data/ytd').then(setData).catch(console.error).finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  const fa = data?.totals?.fa || {}
  const ed = data?.totals?.ed || {}

  return (
    <div className="max-w-7xl mx-auto space-y-6 py-6">
      <h1 className="text-2xl font-bold dark:text-white text-gray-900">Year to Date</h1>

      {/* Company totals */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {[{ label: 'FirstAlt', data: fa, variant: 'indigo' }, { label: 'EverDriven', data: ed, variant: 'cyan' }].map(({ label, data: d, variant }) => (
          <GlassCard key={label}>
            <div className="flex items-center gap-2 mb-4">
              <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${variant === 'indigo' ? 'bg-indigo-500/15 text-indigo-400' : 'bg-cyan-500/15 text-cyan-400'}`}>{label}</span>
              <span className="text-sm dark:text-white/40 text-gray-400">YTD</span>
            </div>
            <div className="grid grid-cols-2 gap-4">
              {[['Revenue', formatCurrency(d.revenue)], ['Profit', formatCurrency(d.profit)], ['Rides', String(d.rides || 0)], ['Driver Cost', formatCurrency(d.cost)]].map(([l, v]) => (
                <div key={l}>
                  <p className="text-xs dark:text-white/40 text-gray-400">{l}</p>
                  <p className="text-base font-bold dark:text-white text-gray-800 mt-0.5">{v}</p>
                </div>
              ))}
            </div>
          </GlassCard>
        ))}
      </div>

      {/* Week by week */}
      <GlassCard padding={false}>
        <div className="p-4 border-b dark:border-white/8 border-gray-100">
          <h3 className="font-semibold dark:text-white text-gray-800">Week by Week</h3>
        </div>
        <DataTable
          columns={[
            { key: 'week', label: 'Week', sortable: true },
            { key: 'fa_revenue', label: 'FA Revenue', render: r => formatCurrency(r.fa_revenue) },
            { key: 'fa_profit', label: 'FA Profit', render: r => <span className="text-indigo-400">{formatCurrency(r.fa_profit)}</span> },
            { key: 'ed_revenue', label: 'ED Revenue', render: r => formatCurrency(r.ed_revenue), mobileHide: true },
            { key: 'ed_profit', label: 'ED Profit', render: r => <span className="text-cyan-400">{formatCurrency(r.ed_profit)}</span>, mobileHide: true },
            { key: 'rides', label: 'Rides', sortable: true },
            { key: 'cumulative_profit', label: 'Cumulative', render: r => <span className="font-semibold text-emerald-500">{formatCurrency(r.cumulative_profit)}</span> },
          ]}
          data={data?.weeks || []}
          keyField="week"
          emptyTitle="No weekly data"
        />
      </GlassCard>

      {/* Driver YTD */}
      <GlassCard padding={false}>
        <div className="p-4 border-b dark:border-white/8 border-gray-100">
          <h3 className="font-semibold dark:text-white text-gray-800">Driver YTD</h3>
        </div>
        <DataTable
          columns={[
            { key: 'driver', label: 'Driver', sortable: true },
            { key: 'weeks_active', label: 'Weeks Active', sortable: true },
            { key: 'rides', label: 'Rides', sortable: true },
            { key: 'revenue', label: 'Revenue', sortable: true, render: r => formatCurrency(r.revenue) },
            { key: 'cost', label: 'Cost', render: r => formatCurrency(r.cost), mobileHide: true },
            { key: 'profit', label: 'Profit', sortable: true, render: r => <span className={r.profit && r.profit >= 0 ? 'text-emerald-500' : 'text-red-400'}>{formatCurrency(r.profit)}</span> },
          ]}
          data={data?.drivers || []}
          keyField="driver"
          emptyTitle="No driver data"
        />
      </GlassCard>
    </div>
  )
}
