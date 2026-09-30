'use client'

import { useCallback, useEffect, useState } from 'react'

// The payroll workflow panel is the only current caller of the Paychex API
// preview endpoint, and it always proxies through the plain "/api/data"
// rewrite — keep this consistent with PaychexBotPanel's own base path.
const PAYCHEX_API_BASE_PATH = '/api/data/paychex-api'

export interface PaychexOpenPayPeriod {
  pay_period_id: string
  start_date: string
  end_date: string
  status: string
  check_date: string
  description: string
}

export interface PaychexMatchedRow {
  person_id: string | number
  person: string
  code: string
  amount: number
  worker_id: string
  worker_name: string
}

export interface PaychexUnmatchedRow {
  person_id: string | number
  person: string
  code: string
  amount: number
  reason: string
}

export interface PaychexPreview {
  batch_id: string | number
  company: string
  pay_period: PaychexOpenPayPeriod | null
  pay_period_error: string | null
  open_pay_periods: PaychexOpenPayPeriod[]
  component_id: string | null
  component_ok: boolean
  matched: PaychexMatchedRow[]
  unmatched: PaychexUnmatchedRow[]
  total_amount: number
  count: number
  /** Rows already staged (or in flight) in Paychex for this batch — push refuses to stage these twice. */
  already_staged?: number
}

interface PaychexPreviewErrorResponse {
  error?: string
}

export interface UsePaychexApiPreviewResult {
  preview: PaychexPreview | null
  loading: boolean
  error: string | null
  disabled: boolean
  refetch: () => void
}

const PREVIEW_CACHE_TTL_MS = 2 * 60 * 1000

interface PreviewResult {
  disabled: boolean
  preview: PaychexPreview | null
}

interface CacheEntry {
  promise: Promise<PreviewResult>
  fetchedAt: number
}

// One in-flight/recent preview per batch, shared across mounts. The Stubs step
// warms it (prefetchPaychexPreview) so the Done step's Send button is ready the
// moment it renders instead of ~11s later.
const previewCache = new Map<string, CacheEntry>()

async function requestPreview(batchId: string | number): Promise<PreviewResult> {
  const res = await fetch(`${PAYCHEX_API_BASE_PATH}/preview/${batchId}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  })
  if (res.status === 404) return { disabled: true, preview: null }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error((data as PaychexPreviewErrorResponse).error ?? 'Failed to load Paychex API preview')
  }
  return { disabled: false, preview: data as PaychexPreview }
}

function loadPreview(batchId: string | number, force = false): Promise<PreviewResult> {
  const key = String(batchId)
  const hit = previewCache.get(key)
  if (!force && hit && Date.now() - hit.fetchedAt < PREVIEW_CACHE_TTL_MS) return hit.promise
  const promise = requestPreview(batchId)
  previewCache.set(key, { promise, fetchedAt: Date.now() })
  promise.catch(() => {
    if (previewCache.get(key)?.promise === promise) previewCache.delete(key)
  })
  return promise
}

/** Start the preview early (e.g. while stubs are sending). Errors are swallowed; the panel refetches. */
export function prefetchPaychexPreview(batchId: string | number): void {
  loadPreview(batchId).catch(() => undefined)
}

/** Drop the cached preview — call after a push so the next read sees the staged rows. */
export function invalidatePaychexPreview(batchId: string | number): void {
  previewCache.delete(String(batchId))
}

/**
 * Fetches the Paychex API staging preview for a batch. A 404 means the rail
 * is disabled server-side — callers should treat `disabled` as "render
 * nothing", not as an error.
 */
export function usePaychexApiPreview(batchId: string | number): UsePaychexApiPreviewResult {
  const [preview, setPreview] = useState<PaychexPreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [disabled, setDisabled] = useState(false)

  const fetchPreview = useCallback(async (force = false) => {
    setLoading(true)
    setError(null)
    try {
      const result = await loadPreview(batchId, force)
      setDisabled(result.disabled)
      setPreview(result.preview)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load Paychex API preview')
    } finally {
      setLoading(false)
    }
  }, [batchId])

  useEffect(() => {
    fetchPreview()
  }, [fetchPreview])

  const refetch = useCallback(() => { fetchPreview(true) }, [fetchPreview])

  return { preview, loading, error, disabled, refetch }
}
