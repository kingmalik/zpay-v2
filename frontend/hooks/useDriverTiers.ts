'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api'
import type { Tier } from '@/components/ui/TierBadge'

export interface DriverTierEntry {
  person_id: number
  driver_name: string
  tier: Tier
  tier_label: string
  composite_score: number | null
  week_iso: string
  total_trips: number
}

/**
 * Fetch driver tier data from GET /dispatch/manage/drivers.
 * Returns a Map<person_id, DriverTierEntry> for O(1) lookup when rendering
 * individual driver cards.
 *
 * Refreshes once per mount — tier data changes weekly, not per-second.
 */
export function useDriverTiers(): {
  tierMap: Map<number, DriverTierEntry>
  loading: boolean
} {
  const [tierMap, setTierMap] = useState<Map<number, DriverTierEntry>>(new Map())
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function fetch_() {
      try {
        const rows = await api.get<DriverTierEntry[]>('/dispatch/manage/drivers?tier=all')
        if (!cancelled && Array.isArray(rows)) {
          const map = new Map<number, DriverTierEntry>()
          for (const row of rows) {
            map.set(row.person_id, row)
          }
          setTierMap(map)
        }
      } catch {
        // Non-fatal — dispatch page degrades gracefully without tier data
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetch_()
    return () => { cancelled = true }
  }, [])

  return { tierMap, loading }
}
