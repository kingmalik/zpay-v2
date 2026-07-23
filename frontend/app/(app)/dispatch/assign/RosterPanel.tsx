'use client'

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Loader2, Pencil, AlertCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import { toast } from 'sonner'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Badge from '@/components/ui/Badge'
import RosterBackupModal from './RosterBackupModal'
import { RosterRow, RostersResponse, RosterSyncResult } from './types'

export default function RosterPanel() {
  const [rosters, setRosters] = useState<RosterRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [editing, setEditing] = useState<RosterRow | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    api.get<RostersResponse>('/api/data/assignment/rosters')
      .then(res => { setRosters(res.rosters ?? []); setError(null) })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load rosters'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  async function syncFromHistory() {
    setSyncing(true)
    try {
      const res = await api.post<RosterSyncResult>('/api/data/assignment/rosters/sync')
      toast.success(`${res.created} added · ${res.updated} updated · ${res.deactivated} retired`)
      load()
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Refresh failed')
    } finally {
      setSyncing(false)
    }
  }

  if (loading && rosters.length === 0) return <LoadingSpinner fullPage />

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-sm font-semibold dark:text-white text-gray-900">
          Recurring Routes ({rosters.length})
        </h2>
        <button
          onClick={syncFromHistory}
          disabled={syncing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold dark:bg-white/5 bg-gray-100 dark:text-white/65 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-200 disabled:opacity-50 cursor-pointer"
        >
          {syncing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Refresh from history
        </button>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/25 text-sm text-red-500">
          {error}
        </div>
      )}

      <div className="rounded-2xl overflow-hidden border dark:border-white/8 border-gray-200 dark:bg-white/[0.02] bg-white">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b dark:border-white/8 border-gray-100">
                {['', 'School', 'Route', 'Source', 'Primary', 'Backups', 'Last Seen', ''].map((h, i) => (
                  <th key={i} className="px-4 py-2.5 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rosters.map(r => {
                const isFa = r.source.toLowerCase().includes('first') || r.source.toLowerCase() === 'acumen'
                const noBackups = r.backups.length === 0
                return (
                  <tr key={r.roster_id} className="border-b last:border-0 dark:border-white/5 border-gray-50">
                    <td className="px-4 py-3">
                      {noBackups && (
                        <span title="No backup driver on this route" className="inline-flex">
                          <AlertCircle className="w-3.5 h-3.5 text-amber-500" />
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 dark:text-white/80 text-gray-700">{r.school}</td>
                    <td className="px-4 py-3 dark:text-white/60 text-gray-600 whitespace-nowrap">
                      {r.direction} {r.number}
                      {r.is_odt && <span className="ml-1 text-[10px] font-bold dark:text-white/30 text-gray-400 uppercase">ODT</span>}
                    </td>
                    <td className="px-4 py-3"><Badge variant={isFa ? 'fa' : 'ed'}>{r.source}</Badge></td>
                    <td className="px-4 py-3 dark:text-white/70 text-gray-700">{r.primary?.name ?? '—'}</td>
                    <td className="px-4 py-3">
                      {noBackups ? (
                        <span className="inline-flex items-center gap-1 text-xs text-amber-500 font-medium">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                          none set
                        </span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {r.backups.map(b => (
                            <span key={b.person_id} className="text-xs px-2 py-0.5 rounded-full dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-500">
                              #{b.rank} {b.name}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 dark:text-white/40 text-gray-400 whitespace-nowrap">{formatDate(r.last_seen_ride_ts)}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => setEditing(r)}
                        className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-200 cursor-pointer"
                      >
                        <Pencil className="w-3 h-3" />
                        Edit
                      </button>
                    </td>
                  </tr>
                )
              })}
              {rosters.length === 0 && !loading && (
                <tr><td colSpan={8} className="px-4 py-10 text-center text-sm dark:text-white/30 text-gray-400">
                  No recurring routes found yet
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {editing && (
        <RosterBackupModal
          roster={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); toast.success('Backups saved') }}
        />
      )}
    </div>
  )
}
