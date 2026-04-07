'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Search, RefreshCw, AlertTriangle, TrendingUp } from 'lucide-react'
import { api } from '@/lib/api'
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
  avg_miles?: number
  avg_net_pay?: number
  ride_count?: number
  latest_period_end?: string
  earliest_period_start?: string
  driver_names?: string[]
}

interface RatesData {
  rates?: Rate[]
  unmatched?: { service_code?: string; count?: number }[]
}

function RateCard({ rate, onSave }: { rate: Rate; onSave: (id: string | number, r: number) => void }) {
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
  const margin = rate.avg_net_pay && parseFloat(val) ? (rate.avg_net_pay - parseFloat(val)).toFixed(2) : null

  const isRecent = (() => {
    if (!rate.latest_period_end) return false
    const latest = new Date(rate.latest_period_end)
    const threeMonthsAgo = new Date()
    threeMonthsAgo.setMonth(threeMonthsAgo.getMonth() - 3)
    return latest >= threeMonthsAgo
  })()

  const driverLabel = (rate.driver_names && rate.driver_names.length > 0)
    ? rate.driver_names.join(', ')
    : null

  const weekLabel = (() => {
    if (!rate.earliest_period_start && !rate.latest_period_end) return null
    const fmt = (d: string) => new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    if (rate.earliest_period_start && rate.latest_period_end) {
      return `${fmt(rate.earliest_period_start)} – ${fmt(rate.latest_period_end)}`
    }
    return rate.latest_period_end ? `Through ${fmt(rate.latest_period_end)}` : ''
  })()

  return (
    <div className={`rounded-2xl border transition-all ${needsRate ? 'bg-amber-50/80 border-amber-200' : 'bg-white border-gray-100 hover:border-gray-200'}`}>
      {/* Top bar: name + badge */}
      <div className="px-5 pt-4 pb-3 border-b border-gray-100">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-900 leading-tight">{rate.service_name}</h3>
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${isFa ? 'bg-indigo-100 text-indigo-600' : 'bg-cyan-100 text-cyan-600'}`}>
            {isFa ? 'FirstAlt' : 'EverDriven'}
          </span>
        </div>
        {driverLabel && (
          <p className="text-xs text-gray-500 mt-1 font-medium truncate" title={driverLabel}>
            Driver: {driverLabel}
          </p>
        )}
        {weekLabel && (
          <p className="text-[10px] text-gray-400 mt-0.5">
            {weekLabel}
          </p>
        )}
        {!isRecent && !weekLabel && <span className="text-[10px] text-gray-400 mt-1 inline-block">No longer active</span>}
        {!isRecent && weekLabel && <span className="text-[10px] text-gray-400"> &middot; No longer active</span>}
      </div>

      {/* Info row */}
      <div className="px-5 py-3 flex items-center gap-6">
        <div>
          <p className="text-[10px] text-gray-400 uppercase font-medium">Miles</p>
          <p className="text-xl font-bold text-gray-800">{rate.avg_miles || '—'}</p>
        </div>
        <div>
          <p className="text-[10px] text-gray-400 uppercase font-medium">They Pay Us</p>
          <p className="text-xl font-bold text-gray-800">{rate.avg_net_pay ? `$${rate.avg_net_pay.toFixed(2)}` : '—'}</p>
        </div>
        <div>
          <p className="text-[10px] text-gray-400 uppercase font-medium">Rides</p>
          <p className="text-xl font-bold text-gray-800">{rate.ride_count || 0}</p>
        </div>
        {margin && parseFloat(margin) !== 0 && (
          <div className="ml-auto">
            <p className="text-[10px] text-gray-400 uppercase font-medium">Our Margin</p>
            <p className={`text-xl font-bold ${parseFloat(margin) > 0 ? 'text-emerald-600' : 'text-red-500'}`}>${margin}</p>
          </div>
        )}
      </div>

      {/* Rate input */}
      <div className={`px-5 py-3 rounded-b-2xl flex items-center gap-3 ${needsRate ? 'bg-amber-100/50' : 'bg-gray-50'}`}>
        <span className="text-sm font-medium text-gray-500">We Pay Driver</span>
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
          <input
            type="number" step="0.01" value={val}
            onChange={e => { setVal(e.target.value); setSaved(false) }}
            placeholder="0.00"
            className={`w-28 pl-7 pr-3 py-2.5 rounded-xl text-base border font-mono text-gray-800 focus:outline-none focus:border-[#667eea] focus:ring-2 focus:ring-[#667eea]/20 ${needsRate ? 'border-amber-300 bg-white' : 'border-gray-200 bg-white'}`}
          />
        </div>
        <button onClick={save} disabled={saving}
          className={`px-5 py-2.5 rounded-xl text-sm font-semibold transition-all cursor-pointer ${saved ? 'bg-emerald-500 text-white' : 'bg-[#667eea] text-white hover:bg-[#5a6fd6]'} disabled:opacity-50`}>
          {saving ? '...' : saved ? 'Saved!' : 'Save'}
        </button>
      </div>
    </div>
  )
}

export default function RatesPage() {
  const [data, setData] = useState<RatesData | null>(null)
  const [loading, setLoading] = useState(true)
  const [recalculating, setRecalculating] = useState(false)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'needs_rate' | 'fa' | 'ed' | 'active'>('all')

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

  const isRecentRate = (r: Rate) => {
    if (!r.latest_period_end) return false
    const latest = new Date(r.latest_period_end)
    const threeMonthsAgo = new Date()
    threeMonthsAgo.setMonth(threeMonthsAgo.getMonth() - 3)
    return latest >= threeMonthsAgo
  }

  let filtered = allRates
  if (filter === 'needs_rate') filtered = filtered.filter(r => !r.default_rate || r.default_rate === 0)
  if (filter === 'fa') filtered = filtered.filter(r => (r.source || '').includes('acumen'))
  if (filter === 'ed') filtered = filtered.filter(r => (r.source || '').includes('maz'))
  if (filter === 'active') filtered = filtered.filter(isRecentRate)

  if (search) {
    const q = search.toLowerCase()
    filtered = filtered.filter(r => (r.service_name || '').toLowerCase().includes(q))
  }

  filtered.sort((a, b) => {
    const aZero = !a.default_rate || a.default_rate === 0 ? 0 : 1
    const bZero = !b.default_rate || b.default_rate === 0 ? 0 : 1
    if (aZero !== bZero) return aZero - bZero
    return (a.service_name || '').localeCompare(b.service_name || '')
  })

  const zeroCount = allRates.filter(r => !r.default_rate || r.default_rate === 0).length
  const activeCount = allRates.filter(isRecentRate).length

  return (
    <div className="max-w-5xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Rates</h1>
          <p className="text-sm text-gray-500 mt-1">{allRates.length} routes &middot; {activeCount} active</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={recalculate} disabled={recalculating}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm bg-gray-100 text-gray-600 hover:bg-gray-200 transition-all cursor-pointer disabled:opacity-60">
            <RefreshCw className={`w-4 h-4 ${recalculating ? 'animate-spin' : ''}`} />
            Recalculate
          </button>
        </div>
      </div>

      {zeroCount > 0 && (
        <div className="flex items-center justify-between px-5 py-4 rounded-2xl bg-amber-50 border border-amber-200">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0" />
            <div>
              <p className="text-sm font-semibold text-amber-700">{zeroCount} routes need a driver rate</p>
              <p className="text-xs text-amber-600 mt-0.5">Look at the miles and what they pay us, then set what we pay the driver.</p>
            </div>
          </div>
          <button onClick={() => setFilter('needs_rate')}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-amber-200 text-amber-800 hover:bg-amber-300 transition-all cursor-pointer">
            Show only
          </button>
        </div>
      )}

      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search routes..."
            className="w-full pl-10 pr-4 py-2.5 rounded-xl text-sm bg-white border border-gray-200 text-gray-700 focus:outline-none focus:border-[#667eea] focus:ring-2 focus:ring-[#667eea]/20"
          />
        </div>
        <div className="flex gap-1 p-1 rounded-xl bg-gray-100">
          {([['all', 'All'], ['needs_rate', `Needs Rate (${zeroCount})`], ['active', `Active (${activeCount})`], ['fa', 'FirstAlt'], ['ed', 'EverDriven']] as const).map(([v, l]) => (
            <button key={v} onClick={() => setFilter(v)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer ${filter === v ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
              {l}
            </button>
          ))}
        </div>
        <span className="text-xs text-gray-400">{filtered.length} shown</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {filtered.map((rate, i) => (
          <RateCard key={rate.id || i} rate={rate} onSave={(id, r) => setData(prev => ({
            ...prev,
            rates: prev?.rates?.map(x => x.id === id ? { ...x, default_rate: r } : x)
          }))} />
        ))}
      </div>

      {filtered.length === 0 && (
        <div className="text-center py-12 text-gray-400">No rates match your search</div>
      )}
    </div>
  )
}
