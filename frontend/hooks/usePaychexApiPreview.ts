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

  const fetchPreview = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${PAYCHEX_API_BASE_PATH}/preview/${batchId}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Accept': 'application/json' },
      })
      if (res.status === 404) {
        setDisabled(true)
        setPreview(null)
        return
      }
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error((data as PaychexPreviewErrorResponse).error ?? 'Failed to load Paychex API preview')
      }
      setDisabled(false)
      setPreview(data as PaychexPreview)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load Paychex API preview')
    } finally {
      setLoading(false)
    }
  }, [batchId])

  useEffect(() => {
    fetchPreview()
  }, [fetchPreview])

  return { preview, loading, error, disabled, refetch: fetchPreview }
}
