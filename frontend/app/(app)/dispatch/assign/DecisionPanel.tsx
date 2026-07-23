'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { Decision } from './types'

const TAKE_REASONS = ['good margin', 'easy cover', 'keeps driver busy']
const PASS_REASONS = ['too far', 'pay too low', 'no driver near it']

interface DecisionPanelProps {
  intakeId: number
  onDecided: (decision: Decision, reason: string) => void
}

export default function DecisionPanel({ intakeId, onDecided }: DecisionPanelProps) {
  const [picking, setPicking] = useState<Decision | null>(null)
  const [custom, setCustom] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<{ decision: Decision; reason: string } | null>(null)

  async function submit(decision: Decision, reason: string) {
    if (!reason.trim()) return
    setSaving(true)
    setError(null)
    try {
      await api.post(`/api/data/assignment/intake/${intakeId}/decision`, { decision, reason })
      setDone({ decision, reason })
      setPicking(null)
      onDecided(decision, reason)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to save decision')
    } finally {
      setSaving(false)
    }
  }

  if (done) {
    return (
      <span className={
        done.decision === 'take'
          ? 'flex items-center gap-1.5 text-sm font-semibold text-emerald-500'
          : 'flex items-center gap-1.5 text-sm font-semibold text-red-500'
      }>
        {done.decision === 'take' ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
        {done.decision === 'take' ? 'Took it' : 'Passed'} — {done.reason}
      </span>
    )
  }

  const reasons = picking === 'take' ? TAKE_REASONS : PASS_REASONS

  return (
    <div className="space-y-2">
      {!picking ? (
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPicking('take')}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold text-white cursor-pointer"
            style={{ background: 'linear-gradient(135deg, #10b981, #06b6d4)' }}
          >
            <CheckCircle2 className="w-4 h-4" />
            Take
          </button>
          <button
            onClick={() => setPicking('pass')}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-500 dark:hover:bg-white/10 hover:bg-gray-200 cursor-pointer"
          >
            <XCircle className="w-4 h-4" />
            Pass
          </button>
        </div>
      ) : (
        <AnimatePresence mode="wait">
          <motion.div
            key={picking}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="space-y-2"
          >
            <p className="text-xs dark:text-white/40 text-gray-400">
              Why {picking === 'take' ? 'take it' : 'pass'}?
            </p>
            <div className="flex flex-wrap gap-1.5">
              {reasons.map(r => (
                <button
                  key={r}
                  onClick={() => submit(picking, r)}
                  disabled={saving}
                  className="px-3 py-1.5 rounded-full text-xs font-medium dark:bg-white/5 bg-gray-100 dark:text-white/65 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-200 border dark:border-white/8 border-gray-200 disabled:opacity-50 cursor-pointer"
                >
                  {r}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={custom}
                onChange={e => setCustom(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && submit(picking, custom)}
                placeholder="or type your own reason…"
                className="flex-1 px-3 py-1.5 rounded-lg text-xs dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 focus:outline-none focus:border-[#667eea]/60"
              />
              <button
                onClick={() => submit(picking, custom)}
                disabled={saving || !custom.trim()}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold dark:bg-white/10 bg-gray-200 dark:text-white text-gray-700 disabled:opacity-40 cursor-pointer flex items-center gap-1.5"
              >
                {saving && <Loader2 className="w-3 h-3 animate-spin" />}
                Save
              </button>
              <button
                onClick={() => { setPicking(null); setCustom('') }}
                className="text-xs dark:text-white/30 text-gray-400 hover:text-gray-600 cursor-pointer"
              >
                Cancel
              </button>
            </div>
          </motion.div>
        </AnimatePresence>
      )}
      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  )
}
