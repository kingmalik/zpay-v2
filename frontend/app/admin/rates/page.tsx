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
    <div className={`rounded-xl border transition-all overflow-hidden ${
      needsRate
        ? 'dark:bg-amber-500/5 dark:border-amber-500/30 bg-amber-50/80 border-amber-200'
        : 'dark:bg-white/[0.04] dark:border-white/[0.08] dark:hover:border-white/[0.14] bg-white border-gray-100 hover:border-gray-200'
    }`}>
      {/* Top bar: name + badge */}
      <div className="px-5 pt-4 pb-3 border-b dark:border-white/[0.08] border-gray-100">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold dark:text-[#fafafa] text-gray-900 leading-tight">{rate.service_name}</h3>
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
            isFa
              ? 'bg-[#6366f1]/15 text-[#6366f1] dark:bg-[#6366f1]/20 dark:text-indigo-300'
              : 'bg-[#06b6d4]/15 text-[#06b6d4] dark:bg-[#06b6d4]/20 dark:text-cyan-300'
          }`}>
            {isFa ? 'FirstAlt' : 'EverDriven'}
          </span>
        </div>
        {driverLabel && (
          <p className="text-xs dark:text-white/40 text-gray-500 mt-1 font-medium truncate" title={driverLabel}>
            Driver: {driverLabel}
          </p>
        )}
        {weekLabel && (
          <p className="text-[10px] dark:text-white/30 text-gray-400 mt-0.5">
            {weekLabel}
          </p>
        )}
        {!isRecent && !weekLabel && <span className="text-[10px] dark:text-white/25 text-gray-400 mt-1 inline-block">No longer active</span>}
        {!isRecent && weekLabel && <span className="text-[10px] dark:text-white/25 text-gray-400"> &middot; No longer active</span>}
      </div>

      {/* Info row */}
      <div className="px-5 py-3 flex items-center gap-6">
        <div>
          <p className="text-[10px] dark:text-white/40 text-gray-400 uppercase font-medium tracking-wider">Miles</p>
          <p className="text-xl font-bold dark:text-[#fafafa] text-gray-800">{rate.avg_miles || '—'}</p>
        </div>
        <div>
          <p className="text-[10px] dark:text-white/40 text-gray-400 uppercase font-medium tracking-wider">They Pay Us</p>
          <p className="text-xl font-bold dark:text-[#fafafa] text-gray-800">{rate.avg_net_pay ? `$${rate.avg_net_pay.toFixed(2)}` : '—'}</p>
        </div>
        <div>
          <p className="text-[10px] dark:text-white/40 text-gray-400 uppercase font-medium tracking-wider">Rides</p>
          <p className="text-xl font-bold dark:text-[#fafafa] text-gray-800">{rate.ride_count || 0}</p>
        </div>
        {margin && parseFloat(margin) !== 0 && (
          <div className="ml-auto">
            <p className="text-[10px] dark:text-white/40 text-gray-400 uppercase font-medium tracking-wider">Our Margin</p>
            <p className={`text-xl font-bold ${parseFloat(margin) > 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'}`}>${margin}</p>
          </div>
        )}
      </div>

      {/* Rate input */}
      <div className={`px-5 py-3 flex items-center gap-3 ${
        needsRate
          ? 'dark:bg-amber-500/10 bg-amber-100/50'
          : 'dark:bg-white/[0.02] bg-gray-50'
      }`}>
        <span className="text-sm font-medium dark:text-white/50 text-gray-500">We Pay Driver</span>
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 dark:text-white/30 text-gray-400 text-sm">$</span>
          <input
            type="number" step="0.01" value={val}
            onChange={e => { setVal(e.target.value); setSaved(false) }}
            placeholder="0.00"
            className={`w-28 pl-7 pr-3 py-2.5 rounded-xl text-base border font-mono dark:text-[#fafafa] text-gray-800 focus:outline-none focus:border-[#667eea] focus:ring-2 focus:ring-[#667eea]/20 ${
              needsRate
                ? 'border-amber-300 dark:border-amber-500/40 dark:bg-white/5 bg-white'
                : 'border-gray-200 dark:border-white/[0.08] dark:bg-white/5 bg-white'
            }`}
          />
        </div>
        <button onClick={save} disabled={saving}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer ${
            saved ? 'bg-emerald-500 text-white' : 'bg-[#667eea] hover:bg-[#7c93f0] text-white'
          } disabled:opacity-50`}>
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
          <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">Rate Configuration</h1>
          <p className="text-sm dark:text-white/40 text-gray-500 mt-0.5">{allRates.length} routes &middot; {activeCount} active in last 3 months</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={recalculate} disabled={recalculating}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm dark:bg-white/[0.06] dark:hover:bg-white/[0.10] dark:text-white/70 bg-gray-100 hover:bg-gray-200 text-gray-600 font-medium transition-colors cursor-pointer disabled:opacity-60">
            <RefreshCw className={`w-4 h-4 ${recalculating ? 'animate-spin' : ''}`} />
            Recalculate
          </button>
        </div>
      </div>

      {zeroCount > 0 && (
        <div className="flex items-center justify-between px-5 py-4 rounded-xl dark:bg-amber-500/10 dark:border dark:border-amber-500/30 bg-amber-50 border border-amber-200">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-500 dark:text-amber-400 flex-shrink-0" />
            <div>
              <p className="text-sm font-semibold dark:text-amber-400 text-amber-700">{zeroCount} routes need a driver rate</p>
              <p className="text-xs dark:text-amber-400/70 text-amber-600 mt-0.5">Look at the miles and what they pay us, then set what we pay the driver.</p>
            </div>
          </div>
          <button onClick={() => setFilter('needs_rate')}
            className="px-4 py-2 rounded-lg text-xs font-semibold dark:bg-amber-500/20 dark:text-amber-400 dark:hover:bg-amber-500/30 bg-amber-200 text-amber-800 hover:bg-amber-300 transition-all cursor-pointer">
            Show only
          </button>
        </div>
      )}

      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search routes..."
            className="w-full pl-10 pr-4 py-2.5 rounded-xl text-sm dark:bg-white/5 dark:border dark:border-white/[0.08] dark:text-white bg-white border border-gray-200 text-gray-700 focus:outline-none focus:border-[#667eea] focus:ring-2 focus:ring-[#667eea]/20"
          />
        </div>
        <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
          {([['all', 'All'], ['needs_rate', `Needs Rate (${zeroCount})`], ['active', `Active (${activeCount})`], ['fa', 'FirstAlt'], ['ed', 'EverDriven']] as const).map(([v, l]) => (
            <button key={v} onClick={() => setFilter(v)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                filter === v
                  ? 'dark:bg-[#667eea] dark:text-white bg-white text-gray-800 shadow-sm'
                  : 'dark:text-white/50 text-gray-500 dark:hover:text-white/70 hover:text-gray-700'
              }`}>
              {l}
            </button>
          ))}
        </div>
        <span className="text-xs dark:text-white/30 text-gray-400">{filtered.length} shown</span>
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
        <div className="text-center py-12 dark:text-white/30 text-gray-400">No rates match your search</div>
      )}
    </div>
  )
}
