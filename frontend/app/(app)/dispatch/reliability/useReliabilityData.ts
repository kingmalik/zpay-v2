'use client'

import { useState, useEffect, useCallback } from 'react'
import { api } from '@/lib/api'
import type { ScorecardRow } from './types'

interface UseReliabilityDataResult {
  data: ScorecardRow[]
  loading: boolean
  error: string | null
  refetch: () => void
}

/**
 * Fetch the weekly reliability scorecard from the Phase 6 endpoint.
 * Uses the same api.get() pattern as the rest of the dispatch pages.
 */
export function useReliabilityData(weekIso: string): UseReliabilityDataResult {
  const [data, setData] = useState<ScorecardRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetch_ = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const rows = await api.get<ScorecardRow[]>(
        `/dispatch/manage/reliability?window=weekly&week=${encodeURIComponent(weekIso)}`
      )
      setData(Array.isArray(rows) ? rows : [])
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load reliability data')
      setData([])
    } finally {
      setLoading(false)
    }
  }, [weekIso])

  useEffect(() => {
    fetch_()
  }, [fetch_])

  return { data, loading, error, refetch: fetch_ }
}
