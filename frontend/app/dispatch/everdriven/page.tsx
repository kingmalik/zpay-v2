'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { RefreshCw, AlertCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { todayStr } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface EDRun { id?: string | number; time?: string; status?: string; students?: number; miles?: number }
interface EDDriver { id?: string | number; name?: string; phone?: string; address?: string; trip_count?: number; runs?: EDRun[] }
interface EDData { drivers?: EDDriver[]; unmatched?: EDRun[]; authenticated?: boolean; stats?: { total?: number; completed?: number; active?: number; scheduled?: number; cancelled?: number } }

export default function EverDrivenPage() {
  const [data, setData] = useState<EDData | null>(null)
  const [loading, setLoading] = useState(true)
  const [date, setDate] = useState(todayStr())

  useEffect(() => {
    api.get<EDData>(`/api/data/dispatch-everdriven?date=${date}`).then(setData).catch(console.error).finally(() => setLoading(false))
  }, [date])

  if (loading) return <LoadingSpinner fullPage />

  const stats = data?.stats || {}
  const drivers = data?.drivers || []
  const unmatched = data?.unmatched || []

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">EverDriven Dispatch</h1>
          {!data?.authenticated && (
            <Link href="/dispatch/everdriven/auth" className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25 transition-all">
              <AlertCircle className="w-3.5 h-3.5" />
              Re-authenticate
            </Link>
          )}
        </div>
        <div className="flex items-center gap-3">
          <input type="date" value={date} onChange={e => setDate(e.target.value)}
            className="px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
          <button onClick={() => { setLoading(true); api.get<EDData>(`/api/data/dispatch-everdriven?date=${date}`).then(setData).finally(() => setLoading(false)) }}
            className="p-2 rounded-xl dark:hover:bg-white/8 hover:bg-gray-100 transition-all cursor-pointer">
            <RefreshCw className="w-4 h-4 dark:text-white/50 text-gray-500" />
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="flex flex-wrap gap-2">
        {[['Total', stats.total || 0, ''], ['Completed', stats.completed || 0, 'text-emerald-400'], ['Active', stats.active || 0, 'text-blue-400'], ['Scheduled', stats.scheduled || 0, 'text-amber-400'], ['Cancelled', stats.cancelled || 0, 'text-red-400']].map(([l, v, c]) => (
          <div key={String(l)} className={`px-3 py-1.5 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 ${c}`}>
            <span className="dark:text-white/40 text-gray-400 mr-1">{l}:</span>
            <strong>{v}</strong>
          </div>
        ))}
      </div>

      {/* Driver cards */}
      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
        {drivers.map((d, i) => (
          <div key={d.id || i} className="rounded-xl dark:bg-white/[0.04] dark:border dark:border-white/[0.08] bg-white border border-gray-200 overflow-hidden">
            <div className="px-4 py-3 border-b dark:border-white/[0.08] border-gray-100 flex items-center justify-between">
              <div>
                <p className="font-semibold dark:text-white text-gray-800 text-sm">{d.name}</p>
                <p className="text-xs dark:text-white/40 text-gray-400">{d.phone} • {d.address}</p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="ed">ED</Badge>
                <span className="text-xs dark:text-white/40 text-gray-400">{d.trip_count} runs</span>
              </div>
            </div>
            <div className="divide-y dark:divide-white/5 divide-gray-50">
              {(d.runs || []).map((run, j) => {
                const s = (run.status || '').toLowerCase()
                const color = s.includes('complete') ? 'text-emerald-400' : s.includes('active') || s.includes('start') ? 'text-blue-400' : s.includes('cancel') ? 'text-red-400' : 'text-amber-400'
                return (
                  <div key={run.id || j} className="px-4 py-2.5 flex items-center justify-between">
                    <div>
                      <p className="text-xs font-medium dark:text-white/80 text-gray-700">{run.time}</p>
                      <p className="text-xs dark:text-white/40 text-gray-400">{run.students} students • {run.miles} mi</p>
                    </div>
                    <span className={`text-xs font-medium ${color}`}>{run.status || 'Scheduled'}</span>
                  </div>
                )
              })}
              {(d.runs || []).length === 0 && (
                <p className="px-4 py-3 text-xs dark:text-white/30 text-gray-400 italic">No runs today</p>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Unmatched */}
      {unmatched.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-amber-400 mb-3">Unmatched Runs ({unmatched.length})</h2>
          <div className="rounded-xl border-2 border-amber-500/30 bg-amber-500/5 divide-y dark:divide-amber-500/10">
            {unmatched.map((r, i) => (
              <div key={r.id || i} className="px-4 py-3 flex items-center justify-between text-sm">
                <span className="dark:text-white/70 text-gray-700">{r.time}</span>
                <span className="text-amber-400">{r.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {drivers.length === 0 && unmatched.length === 0 && (
        <div className="text-center py-16 dark:text-white/30 text-gray-400">No EverDriven data for {date}</div>
      )}
    </div>
  )
}
