'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Plus, Save, RefreshCw, AlertTriangle } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface Rate {
  id?: string | number
  service_code?: string
  service_name?: string
  default_rate?: number
  override_count?: number
  unmatched?: boolean
}

interface RatesData {
  rates?: Rate[]
  unmatched?: { service_code?: string; count?: number }[]
}

function RateRow({ rate, onSave }: { rate: Rate; onSave: (id: string | number, r: number) => void }) {
  const [val, setVal] = useState(String(rate.default_rate || ''))
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  async function save() {
    setSaving(true)
    try {
      await api.post(`/api/data/rates/${rate.id}/set`, { rate: parseFloat(val) })
      onSave(rate.id!, parseFloat(val))
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  return (
    <tr className={`border-b last:border-0 dark:border-white/5 border-gray-50 dark:hover:bg-white/3 hover:bg-gray-50 ${rate.unmatched ? 'border-l-2 border-amber-500/60' : ''}`}>
      <td className="px-4 py-3 font-mono text-xs dark:text-white/60 text-gray-500">{rate.service_code}</td>
      <td className="px-4 py-3 dark:text-white/80 text-gray-700">{rate.service_name}</td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-xs dark:text-white/40 text-gray-400">$</span>
          <input
            type="number" step="0.01" value={val}
            onChange={e => { setVal(e.target.value); setSaved(false) }}
            className="w-24 px-2 py-1.5 rounded-lg text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60 font-mono"
          />
          <button onClick={save} disabled={saving}
            className={`p-1.5 rounded-lg transition-all cursor-pointer ${saved ? 'bg-emerald-500/15 text-emerald-400' : 'dark:bg-white/8 bg-gray-100 dark:text-white/60 text-gray-600 hover:dark:bg-white/12 hover:bg-gray-200'}`}>
            <Save className="w-3.5 h-3.5" />
          </button>
        </div>
      </td>
      <td className="px-4 py-3">
        <Link href={`/admin/rates/${rate.id}/overrides`} className="text-xs text-[#667eea] hover:text-[#7c93f0] transition-colors">
          {rate.override_count || 0} overrides →
        </Link>
      </td>
    </tr>
  )
}

export default function RatesPage() {
  const [data, setData] = useState<RatesData | null>(null)
  const [loading, setLoading] = useState(true)
  const [recalculating, setRecalculating] = useState(false)

  useEffect(() => {
    api.get<RatesData>('/api/data/rates').then(setData).catch(console.error).finally(() => setLoading(false))
  }, [])

  async function recalculate() {
    setRecalculating(true)
    try {
      await api.post('/admin/rates/recalculate')
      const d = await api.get<RatesData>('/api/data/rates')
      setData(d)
    } catch (e) { console.error(e) }
    finally { setRecalculating(false) }
  }

  if (loading) return <LoadingSpinner fullPage />

  const rates = data?.rates || []
  const unmatched = data?.unmatched || []

  return (
    <div className="max-w-5xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Rates</h1>
        <div className="flex items-center gap-2">
          <Link href="/admin/rates/review" className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm dark:bg-white/8 bg-gray-100 dark:text-white/70 text-gray-600 hover:dark:bg-white/12 transition-all">
            Rate Review
          </Link>
          <button onClick={recalculate} disabled={recalculating}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm dark:bg-white/8 bg-gray-100 dark:text-white/70 text-gray-600 hover:dark:bg-white/12 transition-all cursor-pointer disabled:opacity-60">
            <RefreshCw className={`w-4 h-4 ${recalculating ? 'animate-spin' : ''}`} />
            Recalculate
          </button>
        </div>
      </div>

      {/* Unmatched alert */}
      {unmatched.length > 0 && (
        <div className="flex items-start gap-3 px-4 py-3 rounded-2xl bg-amber-500/10 border border-amber-500/30">
          <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-400">{unmatched.length} unmatched services</p>
            <p className="text-xs dark:text-white/50 text-gray-500 mt-0.5">These services have no rate assigned. Rows are highlighted.</p>
          </div>
        </div>
      )}

      <GlassCard padding={false}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b dark:border-white/8 border-gray-100">
                {['Service Code', 'Service Name', 'Default Rate', 'Overrides'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rates.map((rate, i) => (
                <RateRow key={rate.id || i} rate={rate} onSave={(id, r) => setData(prev => ({
                  ...prev,
                  rates: prev?.rates?.map(x => x.id === id ? { ...x, default_rate: r } : x)
                }))} />
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </div>
  )
}
