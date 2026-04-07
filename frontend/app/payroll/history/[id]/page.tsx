'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface BatchDetail {
  id?: string | number
  batch_ref?: string
  company?: string
  status?: string
  period?: string
  drivers?: {
    id?: string | number
    name?: string
    pay_code?: string
    days?: number
    net_pay?: number
    carried_over?: number
    pay_this_period?: number
    status?: string
  }[]
  stats?: { driver_count?: number; total_pay?: number; withheld?: number }
}

export default function BatchDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [batch, setBatch] = useState<BatchDetail | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<BatchDetail>(`/api/data/payroll-history/${id}`).then(setBatch).catch(console.error).finally(() => setLoading(false))
  }, [id])

  if (loading) return <LoadingSpinner fullPage />
  if (!batch) return <div className="text-center py-16 dark:text-white/40 text-gray-400">Batch not found</div>

  const src = (batch.company || '').toLowerCase()
  const isFa = src.includes('first') || src.includes('fa')
  const drivers = batch.drivers || []

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      <div className="flex items-center gap-3">
        <Link href="/payroll/history" className="p-2 rounded-xl dark:hover:bg-white/8 hover:bg-gray-100 transition-all dark:text-white/50 text-gray-500">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold dark:text-white text-gray-900">Batch Detail</h1>
          <div className="flex items-center gap-2 mt-1">
            <Badge variant={isFa ? 'fa' : 'ed'}>{batch.company || '—'}</Badge>
            <Badge variant={batch.status?.toLowerCase() === 'final' ? 'final' : 'draft'}>{batch.status || 'Draft'}</Badge>
            <span className="text-xs dark:text-white/40 text-gray-400">{batch.period}</span>
            <span className="text-xs font-mono dark:text-white/30 text-gray-400">{batch.batch_ref}</span>
          </div>
        </div>
      </div>

      <div className="rounded-2xl overflow-hidden dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b dark:border-white/8 border-gray-100">
                {['#', 'Name', 'Pay Code', 'Days', 'Net Pay', 'Carried Over', 'Pay This Period', 'Status'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {drivers.map((d, i) => (
                <tr key={d.id || i} className="border-b last:border-0 dark:border-white/5 border-gray-50 dark:hover:bg-white/3 hover:bg-gray-50">
                  <td className="px-4 py-3 text-xs dark:text-white/40 text-gray-400">{i + 1}</td>
                  <td className="px-4 py-3 font-medium dark:text-white text-gray-800">{d.name}</td>
                  <td className="px-4 py-3 font-mono text-xs dark:text-white/50 text-gray-500">{d.pay_code}</td>
                  <td className="px-4 py-3 dark:text-white/60 text-gray-600">{d.days}</td>
                  <td className="px-4 py-3 dark:text-white/80 text-gray-700">{formatCurrency(d.net_pay)}</td>
                  <td className="px-4 py-3 text-amber-400">{d.carried_over ? formatCurrency(d.carried_over) : '—'}</td>
                  <td className="px-4 py-3 text-emerald-500 font-semibold">{formatCurrency(d.pay_this_period)}</td>
                  <td className="px-4 py-3">
                    <Badge variant={d.status?.toLowerCase().includes('paid') ? 'success' : 'default'}>
                      {d.status || '—'}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
