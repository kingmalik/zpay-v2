'use client'

import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Loader2, UserPlus, UserMinus } from 'lucide-react'
import { api } from '@/lib/api'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import SuggestionList from './SuggestionList'
import { BackupCandidatesResponse, DriverSuggestion, RosterBackup, RosterRow } from './types'

const MAX_BACKUPS = 2

interface RosterBackupModalProps {
  roster: RosterRow
  onClose: () => void
  onSaved: () => void
}

export default function RosterBackupModal({ roster, onClose, onSaved }: RosterBackupModalProps) {
  const [candidates, setCandidates] = useState<DriverSuggestion[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selected, setSelected] = useState<RosterBackup[]>(roster.backups)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    api.get<BackupCandidatesResponse>(`/api/data/assignment/rosters/${roster.roster_id}/backup-candidates`)
      .then(res => { setCandidates(res.candidates ?? []); setLoadError(null) })
      .catch(e => setLoadError(e instanceof Error ? e.message : 'Failed to load candidates'))
      .finally(() => setLoading(false))
  }, [roster.roster_id])

  function addBackup(driver: DriverSuggestion) {
    setSelected(prev => {
      if (prev.some(b => b.person_id === driver.person_id)) return prev
      if (prev.length >= MAX_BACKUPS) return prev
      const usedRanks = prev.map(b => b.rank)
      const rank = usedRanks.includes(1) ? 2 : 1
      return [...prev, { person_id: driver.person_id, name: driver.name, rank }].sort((a, b) => a.rank - b.rank)
    })
  }

  function removeBackup(personId: number) {
    setSelected(prev => prev.filter(b => b.person_id !== personId))
  }

  async function save() {
    setSaving(true)
    setSaveError(null)
    try {
      await api.put(`/api/data/assignment/rosters/${roster.roster_id}/backups`, {
        backups: selected.map(b => ({ person_id: b.person_id, rank: b.rank })),
      })
      onSaved()
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : 'Failed to save backups')
    } finally {
      setSaving(false)
    }
  }

  const remainingCandidates = candidates.filter(c => !selected.some(s => s.person_id === c.person_id))

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onClose}
      >
        <motion.div
          className="w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-2xl p-5 dark:bg-[#16161d] bg-white border dark:border-white/10 border-gray-200 shadow-2xl"
          initial={{ opacity: 0, scale: 0.96, y: 12 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96, y: 12 }}
          onClick={e => e.stopPropagation()}
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="text-base font-semibold dark:text-white text-gray-900">Backup drivers</h2>
              <p className="text-xs dark:text-white/40 text-gray-400">
                {roster.school} · {roster.direction} {roster.number}
              </p>
            </div>
            <button onClick={onClose} className="p-1 rounded-lg dark:hover:bg-white/10 hover:bg-gray-100">
              <X className="w-4 h-4 dark:text-white/50 text-gray-400" />
            </button>
          </div>

          {/* Selected backups (max 2, ranked) */}
          <div className="mb-4">
            <h3 className="text-[11px] font-bold uppercase tracking-widest dark:text-white/35 text-gray-400 mb-2">
              Backup lineup ({selected.length}/{MAX_BACKUPS})
            </h3>
            {selected.length === 0 ? (
              <p className="text-xs dark:text-white/30 text-gray-400">No backups picked yet — this route has a yellow dot until one is added.</p>
            ) : (
              <div className="space-y-1.5">
                {selected.map(b => (
                  <div key={b.person_id} className="flex items-center justify-between px-3 py-2 rounded-xl dark:bg-white/[0.04] bg-gray-50 border dark:border-white/8 border-gray-200">
                    <span className="flex items-center gap-2 text-sm dark:text-white/80 text-gray-700">
                      <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white bg-[#667eea]">
                        {b.rank}
                      </span>
                      {b.name}
                    </span>
                    <button
                      onClick={() => removeBackup(b.person_id)}
                      className="p-1 rounded-lg dark:text-white/30 text-gray-400 hover:text-red-400 dark:hover:bg-white/10 hover:bg-gray-100"
                    >
                      <UserMinus className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Candidates */}
          <div>
            <h3 className="text-[11px] font-bold uppercase tracking-widest dark:text-white/35 text-gray-400 mb-2">
              Suggested candidates
            </h3>
            {loading && <div className="py-6"><LoadingSpinner size="sm" /></div>}
            {!loading && loadError && <p className="text-xs text-red-500">{loadError}</p>}
            {!loading && !loadError && (
              <SuggestionList
                drivers={remainingCandidates}
                emptyLabel={selected.length >= MAX_BACKUPS ? 'Lineup full — remove one to add another' : 'No more candidates for this route'}
                renderAction={driver => (
                  <button
                    onClick={() => addBackup(driver as DriverSuggestion)}
                    disabled={selected.length >= MAX_BACKUPS}
                    className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-200 disabled:opacity-40 cursor-pointer"
                  >
                    <UserPlus className="w-3 h-3" />
                    Add
                  </button>
                )}
              />
            )}
          </div>

          {saveError && <p className="mt-3 text-xs text-red-500">{saveError}</p>}

          <div className="flex justify-end gap-2 mt-5">
            <button onClick={onClose} className="px-4 py-2 rounded-xl text-sm dark:text-white/60 text-gray-500 dark:hover:bg-white/5 hover:bg-gray-100">
              Cancel
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="px-4 py-2 rounded-xl text-sm font-medium text-white flex items-center gap-2 disabled:opacity-50"
              style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
            >
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Save backups
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
