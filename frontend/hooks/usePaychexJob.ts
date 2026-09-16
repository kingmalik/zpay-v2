'use client'

import { useCallback, useEffect, useState } from 'react'

/** How often we poll `status/{jobId}` while a job is in flight. */
export const PAYCHEX_POLL_INTERVAL_MS = 2000

/** Length of the Paychex SMS verification code. */
export const PAYCHEX_MFA_CODE_LENGTH = 6

export type PaychexJobStatus =
  | 'idle'
  | 'queued'
  | 'pending'
  | 'running'
  | 'mfa_required'
  | 'done'
  | 'failed'
  | 'error'
  | 'killed'

export type PaychexJobMode = 'entry' | 'login' | null

const TERMINAL_STATUSES: ReadonlySet<PaychexJobStatus> = new Set([
  'done',
  'failed',
  'error',
  'killed',
])

export interface PaychexJobState {
  jobId: string | null
  status: PaychexJobStatus
  stage: string | null
  message: string
  progress: number
  total: number
  currentDriver: string
  error: string | null
  debugUrls: string[]
  mode: PaychexJobMode
  mfaRequestedAt: string | null
}

const INITIAL_JOB_STATE: PaychexJobState = {
  jobId: null,
  status: 'idle',
  stage: null,
  message: '',
  progress: 0,
  total: 0,
  currentDriver: '',
  error: null,
  debugUrls: [],
  mode: null,
  mfaRequestedAt: null,
}

interface PaychexStatusResponse {
  job_id: string
  status: PaychexJobStatus
  stage?: string | null
  message?: string
  progress?: number
  total?: number
  current_driver?: string
  error?: string | null
  debug_urls?: string[]
  mode?: PaychexJobMode
  mfa_requested_at?: string | null
}

interface PaychexErrorResponse {
  error?: string
}

export interface UsePaychexJobResult {
  job: PaychexJobState
  start: (jobId: string, total?: number) => void
  submitMfaCode: (code: string) => Promise<void>
  reset: () => void
}

/**
 * Owns a Paychex bot job id plus its polled status, shared by the payroll
 * "push entries" flow (mode: "entry") and the admin "sign in" flow
 * (mode: "login").
 *
 * `basePath` must match whatever proxy route the caller already uses for
 * the paychex-bot endpoints — the payroll panel and the admin reauth page
 * go through different Next.js rewrites, so callers pass their own base
 * (e.g. "/api/data/paychex-bot" vs "/api/v1/api/data/paychex-bot") rather
 * than the hook assuming one.
 */
export function usePaychexJob(basePath: string): UsePaychexJobResult {
  const [job, setJob] = useState<PaychexJobState>(INITIAL_JOB_STATE)

  useEffect(() => {
    if (!job.jobId || TERMINAL_STATUSES.has(job.status)) return

    const pollStatus = async () => {
      const res = await fetch(`${basePath}/status/${job.jobId}`, { credentials: 'include' })
      if (!res.ok) return
      const data: PaychexStatusResponse = await res.json()
      setJob(prev => ({
        ...prev,
        status: data.status,
        stage: data.stage ?? null,
        message: data.message ?? '',
        progress: data.progress ?? prev.progress,
        total: data.total ?? prev.total,
        currentDriver: data.current_driver ?? '',
        error: data.error ?? null,
        debugUrls: Array.isArray(data.debug_urls) ? data.debug_urls : [],
        mode: data.mode ?? prev.mode,
        mfaRequestedAt: data.mfa_requested_at ?? null,
      }))
    }

    const interval = setInterval(pollStatus, PAYCHEX_POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [basePath, job.jobId, job.status])

  const start = useCallback((jobId: string, total: number = 0) => {
    setJob({ ...INITIAL_JOB_STATE, jobId, status: 'pending', total })
  }, [])

  const submitMfaCode = useCallback(async (code: string) => {
    if (!job.jobId) throw new Error('No active Paychex job')
    const res = await fetch(`${basePath}/mfa/${job.jobId}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    })
    if (!res.ok) {
      const data: PaychexErrorResponse = await res.json().catch(() => ({}))
      throw new Error(data.error || 'Failed to submit code')
    }
  }, [basePath, job.jobId])

  const reset = useCallback(() => {
    setJob(INITIAL_JOB_STATE)
  }, [])

  return { job, start, submitMfaCode, reset }
}
