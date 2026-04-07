'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { formatCurrency, formatPercent } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import FilterBar from '@/components/ui/FilterBar'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface ParetoData {
  drivers?: { rank?: number; driver?: string; rides?: number; profit?: number; share?: number; cumulative?: number }[]
  least_profitable?: { driver?: string; rides?: number; profit?: number }[]
  services_by_volume?: { service?: string; rides?: number; revenue?: number }[]
  services_by_profit?: { service?: string; profit?: number; margin?: number }[]
  periods?: { period?: string; rides?: number; profit?: number }[]
}

export default function ParetoPage() {
  const [data, setData] = useState<ParetoData | null>(null)
  const [loading, setLoading] = useState(true)
  const [company, setCompany] = useState('all')

  useEffect(() => {
    api.get<ParetoData>('/api/data/pareto').then(setData).catch(console.error).finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  const drivers = data?.drivers || []

  return (
    <div className="max-w-7xl mx-auto space-y-6 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Pareto Analysis</h1>
        <FilterBar company={company} onCompanyChange={setCompany} />
      </div>

      {/* Explanation */}
      <GlassCard>
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 rounded-xl bg-[#667eea]/15 flex items-center justify-center text-[#667eea] flex-shrink-0 text-sm font-bold">80</div>
          <div>
            <h3 className="font-semibold dark:text-white text-gray-800 mb-1">Pareto Principle (80/20 Rule)</h3>
            <p className="text-sm dark:text-white/60 text-gray-500">The highlighted row marks where 80% of total profit is reached. The top drivers above this line generate most of your profit.</p>
          </div>
        </div>
      </GlassCard>

      {/* Drivers table with progress bar */}
      <GlassCard padding={false}>
        <div className="p-4 border-b dark:border-white/8 border-gray-100">
          <h3 className="font-semibold dark:text-white text-gray-800">Driver Ranking</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b dark:border-white/8 border-gray-100">
                {['Rank', 'Driver', 'Rides', 'Profit', 'Share %', 'Cumulative %', 'Progress'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {drivers.map((d, i) => {
                const is80Line = d.cumulative !== undefined && d.cumulative >= 80 && (drivers[i - 1]?.cumulative || 0) < 80
                return (
                  <>
                    {is80Line && (
                      <tr key={`line-${i}`}>
                        <td colSpan={7} className="px-4 py-2 text-center">
                          <div className="flex items-center gap-2">
                            <div className="flex-1 border-t-2 border-dashed border-[#667eea]/60" />
                            <span className="text-xs font-bold text-[#667eea]">80% line</span>
                            <div className="flex-1 border-t-2 border-dashed border-[#667eea]/60" />
                          </div>
                        </td>
                      </tr>
                    )}
                    <tr key={d.rank || i} className={`border-b last:border-0 dark:border-white/5 border-gray-50 ${i < drivers.findIndex(x => (x.cumulative || 0) >= 80) + 1 ? 'dark:bg-[#667eea]/5 bg-indigo-50/50' : ''}`}>
                      <td className="px-4 py-3 text-xs dark:text-white/40 text-gray-400 font-mono">{d.rank || i + 1}</td>
                      <td className="px-4 py-3 font-medium dark:text-white text-gray-800">{d.driver}</td>
                      <td className="px-4 py-3 dark:text-white/60 text-gray-600">{d.rides || 0}</td>
                      <td className="px-4 py-3 text-emerald-500">{formatCurrency(d.profit)}</td>
                      <td className="px-4 py-3 dark:text-white/70 text-gray-600">{formatPercent(d.share)}</td>
                      <td className="px-4 py-3 dark:text-white/50 text-gray-500">{formatPercent(d.cumulative)}</td>
                      <td className="px-4 py-3 w-40">
                        <div className="h-2 rounded-full dark:bg-white/10 bg-gray-200">
                          <div className="h-2 rounded-full bg-gradient-to-r from-[#667eea] to-[#06b6d4]" style={{ width: `${Math.min(d.cumulative || 0, 100)}%` }} />
                        </div>
                      </td>
                    </tr>
                  </>
                )
              })}
            </tbody>
          </table>
        </div>
      </GlassCard>

      {/* Services by volume and profit */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/8 border-gray-100">
            <h3 className="font-semibold dark:text-white/80 text-sm">Services by Volume</h3>
          </div>
          <div className="divide-y dark:divide-white/5 divide-gray-50">
            {(data?.services_by_volume || []).slice(0, 10).map((s, i) => (
              <div key={i} className="px-4 py-3 flex items-center justify-between">
                <div>
                  <p className="text-sm dark:text-white/80 text-gray-700">{s.service}</p>
                  <p className="text-xs dark:text-white/40 text-gray-400">{s.rides} rides</p>
                </div>
                <span className="text-sm dark:text-white/60 text-gray-600">{formatCurrency(s.revenue)}</span>
              </div>
            ))}
          </div>
        </GlassCard>
        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/8 border-gray-100">
            <h3 className="font-semibold dark:text-white/80 text-sm">Services by Profit</h3>
          </div>
          <div className="divide-y dark:divide-white/5 divide-gray-50">
            {(data?.services_by_profit || []).slice(0, 10).map((s, i) => (
              <div key={i} className="px-4 py-3 flex items-center justify-between">
                <p className="text-sm dark:text-white/80 text-gray-700">{s.service}</p>
                <div className="text-right">
                  <p className="text-sm text-emerald-500">{formatCurrency(s.profit)}</p>
                  <p className="text-xs dark:text-white/40 text-gray-400">{formatPercent(s.margin)} margin</p>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>
    </div>
  )
}
