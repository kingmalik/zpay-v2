'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Upload } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

interface PaychexBotPanelProps {
  batchId: string | number
  onComplete?: () => void
}

interface PaychexJobState {
  jobId: string | null
  status: 'idle' | 'pending' | 'running' | 'done' | 'failed' | 'mfa_required'
  progress: number
  total: number
  currentDriver: string
  message: string
  error: string | null
  debugUrls: string[]
}

export default function PaychexBotPanel({ batchId, onComplete }: PaychexBotPanelProps) {
  const [paychexJob, setPaychexJob] = useState<PaychexJobState>({
    jobId: null,
    status: 'idle',
    progress: 0,
    total: 0,
    currentDriver: '',
    message: '',
    error: null,
    debugUrls: [],
  })

  useEffect(() => {
    if (!paychexJob.jobId || ['done', 'failed'].includes(paychexJob.status)) return
    const interval = setInterval(async () => {
      const res = await fetch(`/api/data/paychex-bot/status/${paychexJob.jobId}`, { credentials: 'include' })
      if (res.ok) {
        const d = await res.json()
        setPaychexJob(prev => ({
          ...prev,
          status: d.status,
          progress: d.progress,
          total: d.total,
          currentDriver: d.current_driver,
          message: d.message,
          error: d.error,
          debugUrls: Array.isArray(d.debug_urls) ? d.debug_urls : [],
        }))
        if (d.status === 'done') {
          onComplete?.()
        }
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [paychexJob.jobId, paychexJob.status, onComplete])

  const handleSendToPaychex = async () => {
    setPaychexJob(prev => ({ ...prev, status: 'pending', message: 'Starting...' }))
    try {
      const res = await fetch(`/api/data/paychex-bot/push/${batchId}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Accept': 'application/json' },
      })
      if (!res.ok) throw new Error('Failed to start Paychex bot')
      const d = await res.json()
      setPaychexJob(prev => ({ ...prev, jobId: d.job_id, total: d.total, status: 'pending' }))
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to start'
      setPaychexJob(prev => ({ ...prev, status: 'failed', error: msg, debugUrls: [] }))
    }
  }

  const debugSnapshotsBlock = (urls: string[]) =>
    urls.length > 0 ? (
      <details className="text-xs mt-2">
        <summary className="cursor-pointer dark:text-white/40 text-gray-400 hover:dark:text-white/60 hover:text-gray-600 transition-colors select-none">
          View debug snapshots ({urls.length})
        </summary>
        <div className="mt-2 flex flex-wrap gap-2">
          {urls.map((url, i) => (
            <a
              key={i}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="px-2 py-1 rounded-lg dark:bg-white/5 bg-gray-100 dark:text-white/50 text-gray-500 hover:dark:text-white/80 hover:text-gray-800 transition-colors font-mono"
            >
              snap {i + 1}
            </a>
          ))}
        </div>
      </details>
    ) : null

  if (paychexJob.status === 'idle') {
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
            {paychexJob.status === 'done'
              ? 'Entries Complete'
              : paychexJob.status === 'failed'
              ? 'Bot Failed'
              : paychexJob.status === 'mfa_required'
              ? 'MFA Required'
              : 'Sending to Paychex...'}
          </span>
          {paychexJob.status === 'done' && (
            <button
              onClick={() => setPaychexJob(prev => ({ ...prev, status: 'idle', jobId: null, debugUrls: [] }))}
              className="text-xs dark:text-white/50 text-gray-400 hover:dark:text-white/70 cursor-pointer"
            >
              Dismiss
            </button>
          )}
        </div>

        {paychexJob.status !== 'done' && paychexJob.status !== 'failed' && (
          <>
            <div className="w-full bg-gray-200 dark:bg-white/10 rounded-full h-2 mb-2">
              <div
                className="bg-gradient-to-r from-indigo-500 to-cyan-500 h-2 rounded-full transition-all duration-500"
                style={{ width: `${paychexJob.total > 0 ? (paychexJob.progress / paychexJob.total) * 100 : 0}%` }}
              />
            </div>
            <p className="text-xs dark:text-white/50 text-gray-500">
              {paychexJob.currentDriver ? `Entering: ${paychexJob.currentDriver}` : paychexJob.message}
              {paychexJob.total > 0 && ` (${paychexJob.progress}/${paychexJob.total})`}
            </p>
          </>
        )}

        {paychexJob.status === 'done' && (
          <div className="space-y-2">
            <p className="text-sm dark:text-green-400 text-green-600">
              All entries filled. Log into Paychex to review and submit.
            </p>
            {debugSnapshotsBlock(paychexJob.debugUrls)}
            <Link
              href={`/payroll/history/${batchId}`}
              className="text-xs dark:text-indigo-400 text-indigo-500 hover:underline inline-block mt-1"
            >
              View in History
            </Link>
          </div>
        )}

        {paychexJob.status === 'mfa_required' && (
          <p className="text-sm dark:text-yellow-400 text-yellow-600">
            MFA code sent to your phone — enter it in Paychex to continue
          </p>
        )}

        {paychexJob.status === 'failed' && (
          <div>
            <p className="text-sm dark:text-red-400 text-red-600">{paychexJob.error || 'Something went wrong'}</p>
            {debugSnapshotsBlock(paychexJob.debugUrls)}
            <button
              onClick={() => setPaychexJob({ jobId: null, status: 'idle', progress: 0, total: 0, currentDriver: '', message: '', error: null, debugUrls: [] })}
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
