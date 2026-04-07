'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import StatCard from '@/components/ui/StatCard'
import FilterBar from '@/components/ui/FilterBar'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Badge from '@/components/ui/Badge'

interface ReconciliationData {
  stats?: { total?: number; healthy?: number; needs_review?: number; largest_issue?: number }
  batches?: { week?: string; source?: string; company?: string; rides?: number; revenue?: number; cost?: number; profit?: number; status?: string }[]
}

function statusBadge(status?: string) {
  const s = (status || '').toLowerCase()
  if (s === 'ok') return <Badge variant="success" dot>OK</Badge>
  if (s.includes('warn')) return <Badge variant="warning" dot>Warning</Badge>
  if (s.includes('loss')) return <Badge variant="danger" dot>Loss</Badge>
  return <Badge>{status || '—'}</Badge>
}

export default function ReconciliationPage() {
  const [data, setData] = useState<ReconciliationData | null>(null)
  const [loading, setLoading] = useState(true)
  const [company, setCompany] = useState('all')

  useEffect(() => {
    api.get<ReconciliationData>('/api/data/reconciliation').then(setData).catch(console.error).finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  const s = data?.stats || {}
  const batches = (data?.batches || []).filter(b => {
    if (company === 'all') return true
    const src = (b.source || b.company || '').toLowerCase()
    return company === 'fa' ? src.includes('first') || src.includes('fa') : src.includes('ever') || src.includes('ed')
  })

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Reconciliation</h1>
        <FilterBar company={company} onCompanyChange={setCompany} />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Batches" value={s.total || 0} index={0} />
        <StatCard label="Healthy" value={s.healthy || 0} color="success" index={1} />
        <StatCard label="Needs Review" value={s.needs_review || 0} color={(s.needs_review || 0) > 0 ? 'warning' : 'default'} index={2} />
        <StatCard label="Largest Issue" value={formatCurrency(s.largest_issue)} color="danger" index={3} />
      </div>

      <div className="rounded-2xl overflow-hidden dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b dark:border-white/8 border-gray-100">
                {['Week', 'Source', 'Rides', 'Revenue', 'Cost', 'Profit', 'Status'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {batches.map((b, i) => {
                const status = (b.status || '').toLowerCase()
                const rowColor = status === 'ok' ? '' : status.includes('warn') ? 'dark:bg-amber-500/5 bg-amber-50/50 border-l-2 border-amber-500/40' : status.includes('loss') ? 'dark:bg-red-500/5 bg-red-50/50 border-l-2 border-red-500/40' : ''
                const isFa = (b.source || b.company || '').toLowerCase().includes('first')
                return (
                  <tr key={i} className={`border-b last:border-0 dark:border-white/5 border-gray-50 ${rowColor}`}>
                    <td className="px-4 py-3 dark:text-white/80 text-gray-700">{b.week}</td>
                    <td className="px-4 py-3"><Badge variant={isFa ? 'fa' : 'ed'}>{b.source || b.company}</Badge></td>
                    <td className="px-4 py-3 dark:text-white/60 text-gray-600">{b.rides}</td>
                    <td className="px-4 py-3 dark:text-white/70 text-gray-700">{formatCurrency(b.revenue)}</td>
                    <td className="px-4 py-3 dark:text-white/60 text-gray-600">{formatCurrency(b.cost)}</td>
                    <td className={`px-4 py-3 font-medium ${(b.profit || 0) >= 0 ? 'text-emerald-500' : 'text-red-400'}`}>{formatCurrency(b.profit)}</td>
                    <td className="px-4 py-3">{statusBadge(b.status)}</td>
                  </tr>
                )
              })}
              {batches.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-10 text-center text-sm dark:text-white/30 text-gray-400">No batches found</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
