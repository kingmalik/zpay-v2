'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, Download } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface BatchResponse {
  batch?: {
    id?: number
    batch_ref?: string
    company?: string
    source?: string
    period_start?: string
    period_end?: string
    uploaded_at?: string
    week_label?: string
  }
  drivers?: {
    id?: number
    name?: string
    rides?: number
    net_pay?: number
    cost?: number
    profit?: number
  }[]
  totals?: { rides?: number; net_pay?: number; cost?: number; profit?: number }
}

function formatPeriod(start?: string, end?: string) {
  if (!start && !end) return '—'
  const fmt = (d: string) => new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  if (start && end) return `${fmt(start)} – ${fmt(end)}`
  return fmt(start || end || '')
}

export default function BatchDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [data, setData] = useState<BatchResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<BatchResponse>(`/api/data/payroll-history/${id}`).then(setData).catch(console.error).finally(() => setLoading(false))
  }, [id])

  if (loading) return <LoadingSpinner fullPage />
  if (!data?.batch) return <div className="text-center py-16 dark:text-white/40 text-gray-400">Batch not found</div>

  const batch = data.batch
  const drivers = data.drivers || []
  const totals = data.totals || {}
  const src = (batch.source || batch.company || '').toLowerCase()
  const isFa = src.includes('first') || src.includes('acumen')
  const companyLabel = isFa ? 'FirstAlt' : 'EverDriven'

  return (
    <div className="max-w-6xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Link href="/payroll/history" className="p-2 rounded-xl dark:hover:bg-white/8 hover:bg-gray-100 transition-all dark:text-white/50 text-gray-500">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold dark:text-white text-gray-900">
              {batch.week_label ? `${batch.week_label} — ${companyLabel}` : `Batch #${batch.id}`}
            </h1>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant={isFa ? 'fa' : 'ed'}>{companyLabel}</Badge>
              {batch.week_label && <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-400">{batch.week_label}</span>}
              <span className="text-xs dark:text-white/40 text-gray-400">{formatPeriod(batch.period_start, batch.period_end)}</span>
              {batch.batch_ref && <span className="text-xs font-mono dark:text-white/30 text-gray-400">Ref: {batch.batch_ref}</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              try {
                const res = await fetch(`/api/v1/summary/export/excel?batch_id=${batch.id}`, { credentials: 'include' })
                if (!res.ok) throw new Error('Download failed')
                const blob = await res.blob()
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                const cd = res.headers.get('content-disposition')
                a.download = cd?.match(/filename="?([^"]+)"?/)?.[1] || 'payroll.xlsx'
                a.click()
                URL.revokeObjectURL(url)
              } catch (e) { console.error(e) }
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium dark:bg-white/8 bg-gray-100 dark:text-white/70 text-gray-600 hover:dark:bg-white/12 hover:bg-gray-200 transition-all cursor-pointer"
          >
            <Download className="w-4 h-4" />
            Excel
          </button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-xl p-4 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
          <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Drivers</p>
          <p className="text-xl font-bold dark:text-white text-gray-900">{drivers.length}</p>
        </div>
        <div className="rounded-xl p-4 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
          <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Total Rides</p>
          <p className="text-xl font-bold dark:text-white text-gray-900">{totals.rides || 0}</p>
        </div>
        <div className="rounded-xl p-4 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
          <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Partner Paid</p>
          <p className="text-xl font-bold text-blue-500">{formatCurrency(totals.net_pay)}</p>
        </div>
        <div className="rounded-xl p-4 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
          <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Driver Cost</p>
          <p className="text-xl font-bold text-emerald-500">{formatCurrency(totals.cost)}</p>
        </div>
      </div>

      {/* Drivers table */}
      <div className="rounded-2xl overflow-hidden dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b dark:border-white/8 border-gray-100 bg-gray-50/50 dark:bg-white/3">
              {['#', 'Driver', 'Rides', 'Partner Paid', 'Driver Pay', 'Profit'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {drivers.map((d, i) => (
              <tr key={d.id || i} className="border-b last:border-0 dark:border-white/5 border-gray-50 dark:hover:bg-white/3 hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3 text-xs dark:text-white/40 text-gray-400">{i + 1}</td>
                <td className="px-4 py-3 font-medium">
                  {d.id ? (
                    <Link href={`/payroll/history/${id}/driver/${d.id}`} className="dark:text-white text-gray-800 hover:text-[#667eea] dark:hover:text-[#7c93f0] transition-colors">
                      {d.name || '—'}
                    </Link>
                  ) : (
                    <span className="dark:text-white text-gray-800">{d.name || '—'}</span>
                  )}
                </td>
                <td className="px-4 py-3 dark:text-white/60 text-gray-600">{d.rides || 0}</td>
                <td className="px-4 py-3 dark:text-white/80 text-gray-700">{formatCurrency(d.net_pay)}</td>
                <td className="px-4 py-3 text-emerald-500 font-semibold">{formatCurrency(d.cost)}</td>
                <td className="px-4 py-3">
                  <span className={`font-semibold ${(d.profit || 0) >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                    {formatCurrency(d.profit)}
                  </span>
                </td>
              </tr>
            ))}
            {/* Totals */}
            <tr className="border-t-2 dark:border-white/20 border-gray-300 dark:bg-white/3 bg-gray-50 font-semibold">
              <td colSpan={2} className="px-4 py-3 dark:text-white/60 text-gray-600 text-sm">Totals</td>
              <td className="px-4 py-3 dark:text-white text-gray-800">{totals.rides || 0}</td>
              <td className="px-4 py-3 dark:text-white text-gray-800">{formatCurrency(totals.net_pay)}</td>
              <td className="px-4 py-3 text-emerald-500">{formatCurrency(totals.cost)}</td>
              <td className="px-4 py-3 text-emerald-500">{formatCurrency(totals.profit)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
