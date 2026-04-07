'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, Plus } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface Override {
  id?: string | number
  start_date?: string
  end_date?: string
  rate?: number
  active?: boolean
  note?: string
}

interface OverridesData {
  service_code?: string
  service_name?: string
  default_rate?: number
  overrides?: Override[]
}

export default function RateOverridesPage() {
  const { id } = useParams<{ id: string }>()
  const [data, setData] = useState<OverridesData | null>(null)
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({ start_date: '', end_date: '', rate: '', note: '' })
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    api.get<OverridesData>(`/admin/rates/${id}/overrides`).then(setData).catch(console.error).finally(() => setLoading(false))
  }, [id])

  async function addOverride() {
    setAdding(true)
    try {
      const updated = await api.post<OverridesData>(`/admin/rates/${id}/overrides/add`, { ...form, rate: parseFloat(form.rate) })
      setData(updated)
      setForm({ start_date: '', end_date: '', rate: '', note: '' })
    } catch (e) { console.error(e) }
    finally { setAdding(false) }
  }

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-3xl mx-auto space-y-5 py-6">
      <div className="flex items-center gap-3">
        <Link href="/admin/rates" className="p-2 rounded-xl dark:hover:bg-white/8 hover:bg-gray-100 transition-all dark:text-white/50 text-gray-500">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div>
          <h1 className="text-xl font-bold dark:text-white text-gray-900">{data?.service_name}</h1>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-xs font-mono dark:text-white/40 text-gray-400">{data?.service_code}</span>
            <span className="text-xs dark:text-white/40 text-gray-400">Default: {formatCurrency(data?.default_rate)}</span>
          </div>
        </div>
      </div>

      {/* Add override form */}
      <GlassCard>
        <h3 className="text-sm font-semibold dark:text-white/70 text-gray-700 mb-4">Add Override</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs dark:text-white/40 text-gray-500 mb-1">Start Date</label>
            <input type="date" value={form.start_date} onChange={e => setForm(s => ({ ...s, start_date: e.target.value }))}
              className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs dark:text-white/40 text-gray-500 mb-1">End Date</label>
            <input type="date" value={form.end_date} onChange={e => setForm(s => ({ ...s, end_date: e.target.value }))}
              className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs dark:text-white/40 text-gray-500 mb-1">Override Rate ($)</label>
            <input type="number" step="0.01" value={form.rate} onChange={e => setForm(s => ({ ...s, rate: e.target.value }))} placeholder="0.00"
              className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none font-mono" />
          </div>
          <div>
            <label className="block text-xs dark:text-white/40 text-gray-500 mb-1">Note</label>
            <input value={form.note} onChange={e => setForm(s => ({ ...s, note: e.target.value }))} placeholder="Reason..."
              className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
          </div>
        </div>
        <button onClick={addOverride} disabled={adding || !form.start_date || !form.rate}
          className="mt-4 flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all cursor-pointer disabled:opacity-60"
          style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}>
          <Plus className="w-4 h-4" />
          {adding ? 'Adding...' : 'Add Override'}
        </button>
      </GlassCard>

      {/* Overrides list */}
      <div className="space-y-2">
        {(data?.overrides || []).map((ov, i) => (
          <div key={ov.id || i} className="rounded-xl px-4 py-3 dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 mb-0.5">
                <span className="text-sm dark:text-white/80 text-gray-700">{formatDate(ov.start_date)} → {ov.end_date ? formatDate(ov.end_date) : 'ongoing'}</span>
                {ov.active ? <Badge variant="active" dot>Active</Badge> : <Badge variant="inactive">Expired</Badge>}
              </div>
              {ov.note && <p className="text-xs dark:text-white/40 text-gray-400">{ov.note}</p>}
            </div>
            <span className="font-mono font-semibold dark:text-white text-gray-800">{formatCurrency(ov.rate)}</span>
          </div>
        ))}
        {(data?.overrides || []).length === 0 && (
          <div className="text-center py-10 dark:text-white/30 text-gray-400 text-sm">No overrides set</div>
        )}
      </div>
    </div>
  )
}
