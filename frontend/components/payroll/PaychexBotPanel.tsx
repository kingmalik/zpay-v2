'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Upload } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'
import { usePaychexJob, PAYCHEX_MFA_CODE_LENGTH, type PaychexJobStatus } from '@/hooks/usePaychexJob'

interface PaychexBotPanelProps {
  batchId: string | number
  onComplete?: () => void
}

// This panel proxies through the plain "/api/data" rewrite (no "/v1" segment) —
// keep it consistent with the rest of this file's existing fetch calls.
const PAYCHEX_BOT_BASE_PATH = '/api/data/paychex-bot'

const IN_PROGRESS_STATUSES: ReadonlySet<PaychexJobStatus> = new Set(['queued', 'pending', 'running'])
const FAILED_STATUSES: ReadonlySet<PaychexJobStatus> = new Set(['failed', 'error', 'killed'])

export default function PaychexBotPanel({ batchId, onComplete }: PaychexBotPanelProps) {
  const { job, start, submitMfaCode, reset } = usePaychexJob(PAYCHEX_BOT_BASE_PATH)
  const [startError, setStartError] = useState<string | null>(null)
  const [mfaCode, setMfaCode] = useState('')
  const [submittingMfa, setSubmittingMfa] = useState(false)

  useEffect(() => {
    if (job.status === 'done') {
      onComplete?.()
    }
  }, [job.status, onComplete])

  useEffect(() => {
    if (job.status !== 'mfa_required') setMfaCode('')
  }, [job.status])

  const handleSendToPaychex = async () => {
    setStartError(null)
    try {
      const res = await fetch(`${PAYCHEX_BOT_BASE_PATH}/push/${batchId}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Accept': 'application/json' },
      })
      if (!res.ok) throw new Error('Failed to start Paychex bot')
      const data = await res.json()
      start(data.job_id, data.total)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to start'
      setStartError(msg)
    }
  }

  const handleSubmitMfaCode = async () => {
    setSubmittingMfa(true)
    try {
      await submitMfaCode(mfaCode)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to submit code'
      toast.error(msg)
    } finally {
      setSubmittingMfa(false)
    }
  }

  const handleReset = () => {
    setStartError(null)
    setMfaCode('')
    reset()
  }

  const debugSnapshotsBlock = (urls: string[]) => {
    if (!urls.length) return null
    // The R2 presigned URL embeds the original filename in the path —
    // surface it so each snap is identifiable instead of just "snap 1".
    const labelFor = (url: string) => {
      try {
        const path = new URL(url).pathname
        const name = path.split("/").pop() || "snap"
        return decodeURIComponent(name)
      } catch {
        return "snap"
      }
    }
    const pngs = urls.filter(u => labelFor(u).toLowerCase().endsWith(".png"))
    const others = urls.filter(u => !labelFor(u).toLowerCase().endsWith(".png"))
    return (
      <details className="text-xs mt-2" open>
        <summary className="cursor-pointer dark:text-white/60 text-gray-500 hover:dark:text-white/80 hover:text-gray-700 transition-colors select-none font-medium">
          Debug snapshots ({urls.length})
        </summary>
        {pngs.length > 0 && (
          <div className="mt-3 grid grid-cols-2 gap-3">
            {pngs.map((url, i) => (
              <a key={`png-${i}`} href={url} target="_blank" rel="noopener noreferrer" className="block group">
                <img
                  src={url}
                  alt={labelFor(url)}
                  className="w-full h-auto rounded-lg border dark:border-white/15 border-gray-300 group-hover:dark:border-white/40 group-hover:border-gray-500 transition-colors"
                />
                <p className="mt-1 font-mono text-[10px] dark:text-white/60 text-gray-500 truncate">
                  {labelFor(url)}
                </p>
              </a>
            ))}
          </div>
        )}
        {others.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {others.map((url, i) => (
              <a
                key={`o-${i}`}
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="px-2 py-1 rounded-lg dark:bg-white/10 bg-gray-200 dark:text-white/80 text-gray-700 hover:dark:bg-white/20 hover:bg-gray-300 transition-colors font-mono"
              >
                {labelFor(url)}
              </a>
            ))}
          </div>
        )}
      </details>
    )
  }

  const hasFailed = startError !== null || FAILED_STATUSES.has(job.status)
  const failureMessage = startError ?? job.error ?? job.message ?? 'Something went wrong'

  if (job.status === 'idle' && !hasFailed) {
    return (
      <button
        onClick={handleSendToPaychex}
        className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-gradient-to-r from-indigo-500 to-cyan-500 text-white hover:opacity-90 transition-all cursor-pointer"
      >
        <Upload className="w-4 h-4" />
        Send to Paychex
      </button>
    )
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        className="p-4 rounded-2xl bg-gradient-to-r from-indigo-500/10 to-cyan-500/10 border dark:border-white/10 border-gray-200"
      >
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-semibold dark:text-white text-gray-900">
            {job.status === 'done'
              ? 'Entries Complete'
              : hasFailed
              ? 'Bot Failed'
              : job.status === 'mfa_required'
              ? 'MFA Required'
              : 'Sending to Paychex...'}
          </span>
          {job.status === 'done' && (
            <button
              onClick={handleReset}
              className="text-xs dark:text-white/50 text-gray-400 hover:dark:text-white/70 cursor-pointer"
            >
              Dismiss
            </button>
          )}
        </div>

        {IN_PROGRESS_STATUSES.has(job.status) && (
          <>
            <div className="w-full bg-gray-200 dark:bg-white/10 rounded-full h-2 mb-2">
              <div
                className="bg-gradient-to-r from-indigo-500 to-cyan-500 h-2 rounded-full transition-all duration-500"
                style={{ width: `${job.total > 0 ? (job.progress / job.total) * 100 : 0}%` }}
              />
            </div>
            <p className="text-xs dark:text-white/50 text-gray-500">
              {job.currentDriver ? `Entering: ${job.currentDriver}` : job.message}
              {job.total > 0 && ` (${job.progress}/${job.total})`}
            </p>
          </>
        )}

        {job.status === 'done' && (
          <div className="space-y-2">
            <p className="text-sm dark:text-green-400 text-green-600">
              All entries filled. Log into Paychex to review and submit.
            </p>
            {debugSnapshotsBlock(job.debugUrls)}
            <Link
              href={`/payroll/history/${batchId}`}
              className="text-xs dark:text-indigo-400 text-indigo-500 hover:underline inline-block mt-1"
            >
              View in History
            </Link>
          </div>
        )}

        {job.status === 'mfa_required' && (
          <div className="space-y-3">
            <p className="text-sm dark:text-yellow-400 text-yellow-600">
              {job.message || 'Paychex texted a code to the phone on file — type it here'}
            </p>
            <div className="flex items-center gap-2">
              <input
                type="text"
                inputMode="numeric"
                autoFocus
                maxLength={PAYCHEX_MFA_CODE_LENGTH}
                value={mfaCode}
                onChange={e => setMfaCode(e.target.value.replace(/\D/g, ''))}
                placeholder="123456"
                disabled={submittingMfa}
                className="w-32 px-3 py-2 rounded-lg text-sm font-mono tracking-widest dark:bg-white/10 bg-white border dark:border-white/15 border-gray-300 dark:text-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
              />
              <button
                onClick={handleSubmitMfaCode}
                disabled={submittingMfa || mfaCode.length !== PAYCHEX_MFA_CODE_LENGTH}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-indigo-500 to-cyan-500 text-white hover:opacity-90 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submittingMfa ? 'Submitting...' : 'Submit code'}
              </button>
            </div>
          </div>
        )}

        {hasFailed && (
          <div>
            <p className="text-sm dark:text-red-400 text-red-600">
              {failureMessage}
            </p>
            {debugSnapshotsBlock(job.debugUrls)}
            <button
              onClick={handleReset}
              className="mt-2 text-xs dark:text-white/50 text-gray-400 cursor-pointer"
            >
              Try again
            </button>
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  )
}
