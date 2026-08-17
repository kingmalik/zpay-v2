'use client'

import { useMemo, useState } from 'react'
import { Loader2, Sparkles } from 'lucide-react'
import { checkCapabilityCoverage } from './capability'
import type { DriverCapabilityRow, RideOut } from './types'

interface RideAssignPickerProps {
  ride: RideOut
  drivers: DriverCapabilityRow[]
  /** person_id -> assigned season rides — the fairness badge in the dropdown. */
  rideCounts: Record<string, number>
  /** Resolves when the assign round-trip finishes (success or handled error). */
  onAssign: (ride: RideOut, personId: number) => Promise<void>
}

function ridesBadge(count: number): string {
  if (count === 0) return 'no rides yet'
  return `${count} ride${count !== 1 ? 's' : ''}`
}

/**
 * Single-ride assignment (2026-08-17): volume is too low for loops, so each
 * unassigned ride leads with the backend's fairness-first suggestion — the
 * best-fit driver is pre-selected and one tap assigns. The dropdown is the
 * override lane, showing every driver's current load.
 */
export default function RideAssignPicker({ ride, drivers, rideCounts, onAssign }: RideAssignPickerProps) {
  const suggestions = ride.suggestions ?? []
  const best = suggestions.length > 0 ? suggestions[0] : null
  const [selectedId, setSelectedId] = useState<string>(best ? String(best.person_id) : '')
  const [assigning, setAssigning] = useState(false)

  const driverOptions = useMemo(
    () => drivers.map(d => ({
      ...d,
      coverage: checkCapabilityCoverage(ride.requires, d.capabilities),
      count: rideCounts[String(d.person_id)] ?? 0,
    })),
    [drivers, ride.requires, rideCounts]
  )

  async function handleAssign() {
    if (!selectedId) return
    setAssigning(true)
    try {
      await onAssign(ride, Number(selectedId))
    } finally {
      setAssigning(false)
    }
  }

  return (
    <div className="space-y-1.5" onClick={e => e.stopPropagation()}>
      {suggestions.length > 0 && (
        <div className="space-y-1">
          {suggestions.map((s, i) => (
            <button
              key={s.person_id}
              onClick={() => setSelectedId(String(s.person_id))}
              className={`w-full text-left rounded-lg px-2 py-1 border transition-colors ${
                selectedId === String(s.person_id)
                  ? 'border-[#667eea]/60 bg-[#667eea]/10'
                  : 'dark:border-white/10 border-gray-200 dark:hover:bg-white/5 hover:bg-gray-50'
              }`}
            >
              <p className="flex items-center gap-1 text-[11px] font-medium dark:text-white/80 text-gray-700 truncate">
                {i === 0 && <Sparkles className="w-3 h-3 flex-shrink-0 text-[#667eea]" />}
                {s.name}
              </p>
              <p className="text-[10px] dark:text-white/35 text-gray-400 truncate">
                {s.reasons.join(' · ')}
              </p>
            </button>
          ))}
        </div>
      )}
      <div className="flex gap-1.5">
        <select
          value={selectedId}
          onChange={e => setSelectedId(e.target.value)}
          className="flex-1 min-w-0 px-2 py-1 rounded-lg text-xs dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
        >
          <option value="">Select driver…</option>
          {driverOptions.map(d => (
            <option key={d.person_id} value={d.person_id} disabled={!d.coverage.ok}>
              {best?.person_id === d.person_id ? '★ ' : ''}{d.name} — {
                d.coverage.ok ? ridesBadge(d.count) : `missing ${d.coverage.missing.join(', ')}`
              }
            </option>
          ))}
        </select>
        <button
          onClick={handleAssign}
          disabled={!selectedId || assigning}
          className="flex items-center justify-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium text-white bg-[#667eea] hover:bg-[#5a72d8] disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
        >
          {assigning && <Loader2 className="w-3 h-3 animate-spin" />}
          Assign
        </button>
      </div>
    </div>
  )
}
