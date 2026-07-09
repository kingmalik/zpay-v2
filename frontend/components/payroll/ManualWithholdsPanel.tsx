'use client'

import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { api } from '@/lib/api'

interface ManualWithholdItem {
  person_id: number
  name: string
  note: string | null
  created_at: string | null
}

interface ManualWithholdsResponse {
  items: ManualWithholdItem[]
}

// Amber warning panel surfacing drivers with a PERMANENT manual withhold —
// these people are excluded from every payroll batch (not just the current
// one) until someone explicitly clears the withhold. Silent when there are
// none, or when the fetch fails, so this never blocks the rest of the page.
export default function ManualWithholdsPanel() {
  const [items, setItems] = useState<ManualWithholdItem[]>([])

  useEffect(() => {
    let cancelled = false
    api
      .get<ManualWithholdsResponse>('/api/data/workflow/manual-withholds')
      .then((res) => {
        if (!cancelled) setItems(res.items || [])
      })
      .catch((e) => {
        console.warn('Failed to load manual withholds', e)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (items.length === 0) return null

  return (
    <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0 text-amber-400" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-amber-300">
            Permanent manual withholds active ({items.length})
          </p>
          <p className="text-xs text-white/50 mt-0.5">
            These drivers are excluded from every payroll batch until the
            withhold is cleared — not just this one.
          </p>
          <ul className="mt-3 space-y-1.5">
            {items.map((item) => (
              <li
                key={item.person_id}
                className="text-xs text-white/70 flex flex-wrap items-baseline gap-x-1.5"
              >
                <span className="font-medium text-white">{item.name}</span>
                {item.note && (
                  <span className="text-white/40 italic">"{item.note}"</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
