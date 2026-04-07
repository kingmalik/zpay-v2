'use client'

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Brain, AlertTriangle, AlertCircle, Info, Loader2, Sparkles } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatPercent } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import FilterBar from '@/components/ui/FilterBar'
import DataTable from '@/components/ui/DataTable'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface IntelligenceData {
  snapshots?: { company?: string; revenue?: number; cost?: number; profit?: number; margin?: number; rides?: number; drivers?: number }[]
  alerts?: { type?: string; title?: string; message?: string; severity?: 'warning' | 'danger' | 'info' }[]
  top_drivers?: { driver?: string; rides?: number; profit?: number; margin?: number }[]
  inactive_drivers?: { driver?: string; last_active?: string; rides?: number }[]
  insights?: string
}

const severityMap = {
  warning: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30' },
  danger: { icon: AlertCircle, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30' },
  info: { icon: Info, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/30' },
}

export default function IntelligencePage() {
  const [data, setData] = useState<IntelligenceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [company, setCompany] = useState('all')

  useEffect(() => {
    api.get<IntelligenceData>('/api/data/intelligence').then(setData).catch(console.error).finally(() => setLoading(false))
  }, [])

  async function generateInsights() {
    setGenerating(true)
    try {
      const d = await api.post<IntelligenceData>('/intelligence/generate-insights')
      setData(d)
    } catch (e) { console.error(e) }
    finally { setGenerating(false) }
  }

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-7xl mx-auto space-y-6 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Intelligence</h1>
        <div className="flex items-center gap-3">
          <FilterBar company={company} onCompanyChange={setCompany} />
          <button
            onClick={generateInsights}
            disabled={generating}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all cursor-pointer disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #667eea, #10B981)' }}
          >
            {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {generating ? 'Generating...' : 'Generate Insights'}
          </button>
        </div>
      </div>

      {/* Snapshots */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {(data?.snapshots || []).map((snap, i) => {
          const isFa = (snap.company || '').toLowerCase().includes('first')
          return (
            <motion.div key={i} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.1 }}>
              <GlassCard>
                <div className="flex items-center gap-2 mb-4">
                  <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${isFa ? 'bg-indigo-500/15 text-indigo-400' : 'bg-cyan-500/15 text-cyan-400'}`}>{snap.company}</span>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  {[
                    ['Revenue', formatCurrency(snap.revenue)],
                    ['Profit', formatCurrency(snap.profit)],
                    ['Margin', formatPercent(snap.margin)],
                    ['Rides', String(snap.rides || 0)],
                    ['Drivers', String(snap.drivers || 0)],
                    ['Cost', formatCurrency(snap.cost)],
                  ].map(([l, v]) => (
                    <div key={l}>
                      <p className="text-xs dark:text-white/40 text-gray-400">{l}</p>
                      <p className="text-sm font-semibold dark:text-white text-gray-800 mt-0.5">{v}</p>
                    </div>
                  ))}
                </div>
              </GlassCard>
            </motion.div>
          )
        })}
      </div>

      {/* Alerts */}
      {(data?.alerts || []).length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold dark:text-white/60 text-gray-500 uppercase tracking-wide">Alerts</h2>
          {(data?.alerts || []).map((alert, i) => {
            const sev = severityMap[alert.severity || 'info']
            const Icon = sev.icon
            return (
              <motion.div key={i} initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
                className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${sev.bg}`}>
                <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${sev.color}`} />
                <div>
                  <p className={`text-sm font-medium ${sev.color}`}>{alert.title}</p>
                  <p className="text-xs dark:text-white/60 text-gray-600 mt-0.5">{alert.message}</p>
                </div>
              </motion.div>
            )
          })}
        </div>
      )}

      {/* AI Insights */}
      {data?.insights && (
        <div className="rounded-2xl p-5" style={{ background: 'linear-gradient(135deg, rgba(102,126,234,0.1), rgba(16,185,129,0.05))', border: '1px solid rgba(102,126,234,0.3)' }}>
          <div className="flex items-center gap-2 mb-3">
            <Brain className="w-5 h-5 text-[#667eea]" />
            <h3 className="font-semibold dark:text-white text-gray-800">Intelligence Report</h3>
          </div>
          <p className="text-sm dark:text-white/70 text-gray-600 leading-relaxed whitespace-pre-wrap">{data.insights}</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/8 border-gray-100">
            <h3 className="font-semibold dark:text-white/80 text-sm">Driver Performance</h3>
          </div>
          <DataTable
            columns={[
              { key: 'driver', label: 'Driver' },
              { key: 'rides', label: 'Rides', sortable: true },
              { key: 'profit', label: 'Profit', sortable: true, render: r => <span className={r.profit && r.profit >= 0 ? 'text-emerald-500' : 'text-red-400'}>{formatCurrency(r.profit)}</span> },
              { key: 'margin', label: 'Margin', render: r => formatPercent(r.margin), mobileHide: true },
            ]}
            data={data?.top_drivers || []}
            keyField="driver"
            emptyTitle="No data"
          />
        </GlassCard>

        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/8 border-gray-100">
            <h3 className="font-semibold text-amber-400 text-sm">Inactive Drivers</h3>
          </div>
          <DataTable
            columns={[
              { key: 'driver', label: 'Driver' },
              { key: 'rides', label: 'Rides' },
              { key: 'last_active', label: 'Last Active' },
            ]}
            data={data?.inactive_drivers || []}
            keyField="driver"
            emptyTitle="No inactive drivers"
          />
        </GlassCard>
      </div>
    </div>
  )
}
