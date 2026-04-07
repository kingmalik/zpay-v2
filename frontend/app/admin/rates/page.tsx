'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Search, Save, RefreshCw, AlertTriangle, Filter } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface Rate {
  id?: string | number
  service_code?: string
  service_name?: string
  default_rate?: number
  source?: string
  company_name?: string
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

  const needsRate = !rate.default_rate || rate.default_rate === 0
  const isFa = (rate.source || '').includes('acumen') || (rate.company_name || '').includes('First')

  return (
    <tr className={`border-b last:border-0 border-gray-100 hover:bg-gray-50 ${needsRate ? 'bg-amber-50 border-l-4 border-l-amber-400' : ''}`}>
      <td className="px-4 py-3">
        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${isFa ? 'bg-indigo-100 text-indigo-700' : 'bg-cyan-100 text-cyan-700'}`}>
          {isFa ? 'FA' : 'ED'}
        </span>
      </td>
      <td className="px-4 py-3">
        <p className="text-sm text-gray-800 font-medium">{rate.service_name}</p>
        <p className="text-xs text-gray-400 font-mono">{rate.service_code}</p>
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-400">$</span>
          <input
            type="number" step="0.01" value={val}
            onChange={e => { setVal(e.target.value); setSaved(false) }}
            className={`w-24 px-2.5 py-2 rounded-lg text-sm border text-gray-800 focus:outline-none focus:border-[#667eea] focus:ring-1 focus:ring-[#667eea]/30 font-mono ${needsRate ? 'border-amber-300 bg-amber-50' : 'border-gray-200 bg-white'}`}
          />
          <button onClick={save} disabled={saving}
            className={`px-3 py-2 rounded-lg text-xs font-medium transition-all cursor-pointer ${saved ? 'bg-emerald-100 text-emerald-700' : 'bg-[#667eea] text-white hover:bg-[#5a6fd6]'} disabled:opacity-50`}>
            {saving ? '...' : saved ? 'Saved' : 'Save'}
          </button>
        </div>
      </td>
      <td className="px-4 py-3">
        <Link href={`/admin/rates/${rate.id}/overrides`} className="text-xs text-[#667eea] hover:text-[#5a6fd6] font-medium">
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
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'needs_rate' | 'fa' | 'ed'>('all')

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

  const allRates = data?.rates || []
  const unmatched = data?.unmatched || []

  // Filter
  let filtered = allRates
  if (filter === 'needs_rate') filtered = filtered.filter(r => !r.default_rate || r.default_rate === 0)
  if (filter === 'fa') filtered = filtered.filter(r => (r.source || '').includes('acumen'))
  if (filter === 'ed') filtered = filtered.filter(r => (r.source || '').includes('maz'))

  // Search
  if (search) {
    const q = search.toLowerCase()
    filtered = filtered.filter(r =>
      (r.service_name || '').toLowerCase().includes(q) ||
      (r.service_code || '').toLowerCase().includes(q)
    )
  }

  // Sort: zero-rate first, then alphabetical
  filtered.sort((a, b) => {
    const aZero = !a.default_rate || a.default_rate === 0 ? 0 : 1
    const bZero = !b.default_rate || b.default_rate === 0 ? 0 : 1
    if (aZero !== bZero) return aZero - bZero
    return (a.service_name || '').localeCompare(b.service_name || '')
  })

  const zeroCount = allRates.filter(r => !r.default_rate || r.default_rate === 0).length

  return (
    <div className="max-w-6xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Rates</h1>
          <p className="text-sm text-gray-500 mt-1">{allRates.length} services total</p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/admin/rates/review" className="px-3 py-2 rounded-xl text-sm bg-gray-100 text-gray-600 hover:bg-gray-200 transition-all">
            Rate Review
          </Link>
          <button onClick={recalculate} disabled={recalculating}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm bg-gray-100 text-gray-600 hover:bg-gray-200 transition-all cursor-pointer disabled:opacity-60">
            <RefreshCw className={`w-4 h-4 ${recalculating ? 'animate-spin' : ''}`} />
            Recalculate
          </button>
        </div>
      </div>

      {/* Alert for zero-rate services */}
      {zeroCount > 0 && (
        <div className="flex items-center justify-between px-4 py-3 rounded-2xl bg-amber-50 border border-amber-200">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0" />
            <div>
              <p className="text-sm font-semibold text-amber-700">{zeroCount} services need a rate</p>
              <p className="text-xs text-amber-600 mt-0.5">These are shown first. Set the driver pay rate and click Save.</p>
            </div>
          </div>
          <button onClick={() => setFilter('needs_rate')}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-200 text-amber-800 hover:bg-amber-300 transition-all cursor-pointer">
            Show only
          </button>
        </div>
      )}

      {/* Search + Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search routes..."
            className="w-full pl-10 pr-4 py-2.5 rounded-xl text-sm bg-white border border-gray-200 text-gray-700 focus:outline-none focus:border-[#667eea] focus:ring-1 focus:ring-[#667eea]/30"
          />
        </div>
        <div className="flex gap-1 p-1 rounded-xl bg-gray-100">
          {([['all', 'All'], ['needs_rate', `Needs Rate (${zeroCount})`], ['fa', 'FirstAlt'], ['ed', 'EverDriven']] as const).map(([v, l]) => (
            <button key={v} onClick={() => setFilter(v)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer ${filter === v ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
              {l}
            </button>
          ))}
        </div>
        <span className="text-xs text-gray-400">{filtered.length} shown</span>
      </div>

      {/* Table */}
      <GlassCard padding={false}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50">
                {['Source', 'Service', 'Driver Rate (z_rate)', 'Overrides'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((rate, i) => (
                <RateRow key={rate.id || i} rate={rate} onSave={(id, r) => setData(prev => ({
                  ...prev,
                  rates: prev?.rates?.map(x => x.id === id ? { ...x, default_rate: r } : x)
                }))} />
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-400">No rates match your search</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </div>
  )
}
