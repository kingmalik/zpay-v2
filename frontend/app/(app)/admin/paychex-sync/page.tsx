'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { RefreshCw, Loader2, CheckCircle2, Link2, ExternalLink } from 'lucide-react'
import { api } from '@/lib/api'
import StatCard from '@/components/ui/StatCard'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface PaychexData {
  stats?: { total?: number; linked?: number; ready?: number; unmatched?: number }
  matched?: { zpay_driver?: string; paychex_name?: string; paychex_id?: string }[]
  linked?: { driver?: string; paychex_id?: string }[]
  unmatched?: { driver?: string; id?: string | number }[]
}

export default function PaychexSyncPage() {
  const [data, setData] = useState<PaychexData | null>(null)
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState(false)

  useEffect(() => {
    api.get<PaychexData>('/admin/paychex-sync').then(setData).catch(console.error).finally(() => setLoading(false))
  }, [])

  async function apply() {
    setApplying(true)
    try {
      const d = await api.post<PaychexData>('/admin/paychex-sync/apply')
      setData(d)
    } catch (e) { console.error(e) }
    finally { setApplying(false) }
  }

  if (loading) return <LoadingSpinner fullPage />

  const s = data?.stats || {}

  return (
    <div className="max-w-5xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">Paychex Sync</h1>
          <p className="text-sm dark:text-white/40 text-gray-500 mt-0.5">Match Z-Pay drivers to Paychex worker IDs for payroll export</p>
        </div>
        <button onClick={apply} disabled={applying}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white cursor-pointer disabled:opacity-60 transition-all"
          style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}>
          {applying ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          {applying ? 'Syncing...' : 'Apply Sync'}
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Workers" value={s.total || 0} index={0} />
        <StatCard label="Linked" value={s.linked || 0} color="success" index={1} />
        <StatCard label="Ready to Sync" value={s.ready || 0} color="info" index={2} />
        <StatCard label="Unmatched" value={s.unmatched || 0} color={(s.unmatched || 0) > 0 ? 'warning' : 'default'} index={3} />
      </div>

      {/* Matched */}
      <GlassCard padding={false}>
        <div className="p-4 border-b dark:border-white/8 border-gray-100 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <h3 className="font-semibold dark:text-white/80 text-sm">Matched Drivers ({(data?.matched || []).length})</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b dark:border-white/8 border-gray-100">
                {['Z-Pay Driver', 'Paychex Name', 'Paychex ID'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data?.matched || []).map((m, i) => (
                <tr key={i} className="border-b last:border-0 dark:border-white/[0.06] border-gray-100 dark:hover:bg-white/[0.04] hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-2.5 dark:text-white/80 text-gray-700">{m.zpay_driver}</td>
                  <td className="px-4 py-2.5 dark:text-white/60 text-gray-600">{m.paychex_name}</td>
                  <td className="px-4 py-2.5 font-mono text-xs dark:text-white/40 text-gray-400">{m.paychex_id}</td>
                </tr>
              ))}
              {(data?.matched || []).length === 0 && (
                <tr><td colSpan={3} className="px-4 py-6 text-center text-sm dark:text-white/30 text-gray-400">No matches found</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassCard>

      {/* Unmatched */}
      {(data?.unmatched || []).length > 0 && (
        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/8 border-gray-100 flex items-center gap-2">
            <Link2 className="w-4 h-4 text-amber-400" />
            <h3 className="font-semibold text-amber-400 text-sm">Unmatched Drivers ({(data?.unmatched || []).length})</h3>
          </div>
          <div className="divide-y dark:divide-white/5 divide-gray-50">
            {(data?.unmatched || []).map((d, i) => (
              <div key={i} className="px-4 py-3 flex items-center justify-between">
                <p className="text-sm dark:text-white/70 text-gray-700">{d.driver}</p>
                <Link href={`/people`} className="flex items-center gap-1 text-xs text-[#667eea] hover:text-[#7c93f0]">
                  Edit profile <ExternalLink className="w-3 h-3" />
                </Link>
              </div>
            ))}
          </div>
        </GlassCard>
      )}
    </div>
  )
}
