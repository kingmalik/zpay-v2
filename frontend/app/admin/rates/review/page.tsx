'use client'

import { useEffect, useState } from 'react'
import { Search, Save, CheckCircle2, AlertTriangle } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface ReviewRoute {
  service_code?: string
  service_name?: string
  company?: string
  rides?: number
  partner_pays?: number
  miles?: number
  est_rate?: number
  current_rate?: number
  set_rate?: number
}

export default function RateReviewPage() {
  const [routes, setRoutes] = useState<ReviewRoute[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [rateInputs, setRateInputs] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<Record<string, boolean>>({})

  useEffect(() => {
    api.get<ReviewRoute[]>('/admin/rates/review').then(d => {
      setRoutes(d)
      const inputs: Record<string, string> = {}
      d.forEach(r => { if (r.service_code) inputs[r.service_code] = String(r.current_rate || '') })
      setRateInputs(inputs)
    }).catch(console.error).finally(() => setLoading(false))
  }, [])

  async function saveRate(code: string) {
    setSaving(s => ({ ...s, [code]: true }))
    try {
      await api.post(`/admin/rates/review/apply`, { service_code: code, rate: parseFloat(rateInputs[code] || '0') })
    } catch (e) { console.error(e) }
    finally { setSaving(s => ({ ...s, [code]: false })) }
  }

  const filtered = routes.filter(r => {
    const q = search.toLowerCase()
    return !q || r.service_name?.toLowerCase().includes(q) || r.service_code?.toLowerCase().includes(q)
  })

  const allMatch = routes.every(r => r.current_rate !== undefined && Math.abs((r.current_rate || 0) - (r.est_rate || 0)) < 0.01)

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-6xl mx-auto space-y-5 py-6">
      <h1 className="text-2xl font-bold dark:text-white text-gray-900">Rate Review</h1>

      {/* Banner */}
      <div className={`flex items-center gap-3 px-4 py-3 rounded-2xl border ${allMatch ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-amber-500/10 border-amber-500/30'}`}>
        {allMatch ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <AlertTriangle className="w-4 h-4 text-amber-400" />}
        <p className={`text-sm font-medium ${allMatch ? 'text-emerald-400' : 'text-amber-400'}`}>
          {allMatch ? 'All rates are correct' : `${routes.filter(r => Math.abs((r.current_rate || 0) - (r.est_rate || 0)) > 0.01).length} routes may need rate adjustment`}
        </p>
      </div>

      {/* Search */}
      <div className="relative w-64">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search routes..."
          className="w-full pl-9 pr-4 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
      </div>

      <div className="rounded-2xl overflow-hidden dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b dark:border-white/8 border-gray-100">
                {['Company', 'Service', 'Rides', 'Partner Pays', 'Miles', 'Est Rate', 'Set Correct Rate'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => {
                const isFa = (r.company || '').toLowerCase().includes('first')
                const needsUpdate = Math.abs((r.current_rate || 0) - (r.est_rate || 0)) > 0.01
                return (
                  <tr key={i} className={`border-b last:border-0 dark:border-white/5 border-gray-50 ${needsUpdate ? 'dark:bg-amber-500/5 bg-amber-50/30' : ''}`}>
                    <td className="px-4 py-3"><Badge variant={isFa ? 'fa' : 'ed'}>{r.company}</Badge></td>
                    <td className="px-4 py-3">
                      <p className="dark:text-white/80 text-gray-700">{r.service_name}</p>
                      <p className="text-xs font-mono dark:text-white/30 text-gray-400">{r.service_code}</p>
                    </td>
                    <td className="px-4 py-3 dark:text-white/60 text-gray-600">{r.rides}</td>
                    <td className="px-4 py-3 dark:text-white/70 text-gray-700">{formatCurrency(r.partner_pays)}</td>
                    <td className="px-4 py-3 dark:text-white/60 text-gray-600">{r.miles}</td>
                    <td className="px-4 py-3 text-amber-400 font-mono text-xs">{formatCurrency(r.est_rate)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="text-xs dark:text-white/30 text-gray-400">$</span>
                        <input
                          type="number" step="0.01"
                          value={r.service_code ? rateInputs[r.service_code] || '' : ''}
                          onChange={e => setRateInputs(s => ({ ...s, [r.service_code!]: e.target.value }))}
                          className="w-20 px-2 py-1 rounded-lg text-xs dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none font-mono"
                        />
                        <button
                          onClick={() => r.service_code && saveRate(r.service_code)}
                          disabled={saving[r.service_code!]}
                          className="p-1 rounded-lg dark:bg-white/8 bg-gray-100 dark:text-white/60 text-gray-600 hover:dark:bg-white/12 transition-all cursor-pointer disabled:opacity-50"
                        >
                          <Save className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
