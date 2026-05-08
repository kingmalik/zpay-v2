'use client'

import { useState, useEffect, useCallback } from 'react'
import { api } from '@/lib/api'
import type { ScorecardRow, RollingRow, ViewWindow } from './types'

// ─── Weekly hook (existing) ───────────────────────────────────────────────────

interface UseWeeklyDataResult {
  data: ScorecardRow[]
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useReliabilityData(weekIso: string): UseWeeklyDataResult {
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

// ─── 30-day rolling hook (Phase 4) ───────────────────────────────────────────

interface UseRollingDataResult {
  data: RollingRow[]
  loading: boolean
  error: string | null
  refetch: () => void
}

/**
 * Fetch 30-day rolling average from scorecard_cache.
 * Returns empty array when cache has no data yet (first weeks before Sunday cron fires).
 */
export function useRollingData(weekIso: string): UseRollingDataResult {
  const [data, setData] = useState<RollingRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetch_ = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const rows = await api.get<RollingRow[]>(
        `/dispatch/manage/reliability?window=30d&week=${encodeURIComponent(weekIso)}`
      )
      setData(Array.isArray(rows) ? rows : [])
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load 30-day data')
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
