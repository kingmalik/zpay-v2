'use client'

import { useEffect, useState } from 'react'
import { History } from 'lucide-react'
import { api } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { IntakeListItem, IntakesResponse } from './types'

function statusChip(status: string) {
  const s = status.toLowerCase()
  const cls =
    s === 'take' || s === 'taken'
      ? 'bg-emerald-500/15 text-emerald-500 border-emerald-500/30'
      : s === 'pass' || s === 'passed'
      ? 'bg-gray-500/15 text-gray-500 border-gray-500/30'
      : s === 'pending'
      ? 'bg-amber-500/15 text-amber-500 border-amber-500/30'
      : 'bg-blue-500/15 text-blue-500 border-blue-500/30'
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide border ${cls}`}>
      {status}
    </span>
  )
}

export interface IntakeHistoryHandle {
  refresh: () => void
}

interface IntakeHistoryProps {
  refreshKey: number
}

export default function IntakeHistory({ refreshKey }: IntakeHistoryProps) {
  const [intakes, setIntakes] = useState<IntakeListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    api.get<IntakesResponse>('/api/data/assignment/intakes')
      .then(res => { setIntakes(res.intakes ?? []); setError(null) })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load recent intakes'))
      .finally(() => setLoading(false))
  }, [refreshKey])

  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <History className="w-3.5 h-3.5 dark:text-white/30 text-gray-400" />
        <h3 className="text-xs font-bold uppercase tracking-widest dark:text-white/35 text-gray-400">
          Recent Rides
        </h3>
      </div>

      {loading && <div className="py-4"><LoadingSpinner size="sm" /></div>}

      {!loading && error && (
        <p className="text-xs text-red-500">{error}</p>
      )}

      {!loading && !error && intakes.length === 0 && (
        <p className="text-xs dark:text-white/30 text-gray-400">Nothing pasted in yet.</p>
      )}

      {!loading && intakes.length > 0 && (
        <div className="rounded-2xl border dark:border-white/8 border-gray-200 overflow-hidden">
          <table className="w-full text-xs">
            <tbody>
              {intakes.map(item => (
                <tr key={item.intake_id} className="border-b last:border-0 dark:border-white/5 border-gray-50">
                  <td className="px-3 py-2 dark:text-white/70 text-gray-700 whitespace-nowrap">
                    {formatDate(item.created_at)}
                  </td>
                  <td className="px-3 py-2 dark:text-white/60 text-gray-600">
                    {item.parsed?.school || '—'}
                    <span className="dark:text-white/30 text-gray-400 ml-1">
                      {item.parsed?.direction} {item.parsed?.number}
                    </span>
                  </td>
                  <td className="px-3 py-2">{statusChip(item.status)}</td>
                  <td className="px-3 py-2 dark:text-white/40 text-gray-400 truncate max-w-[200px]">
                    {item.decision_reason || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
