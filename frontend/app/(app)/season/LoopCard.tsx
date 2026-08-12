'use client'

import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { Loader2, MessageSquare, XCircle } from 'lucide-react'
import { checkCapabilityCoverage, mergeRequiresProfiles } from './capability'
import { assignLoop, AssignConflictError, dismissLoop, extendLoop } from './seasonApi'
import { formatHHMM, studentFromNotes } from './utils'
import RequirementIcons from './RequirementIcons'
import type { DriverCapabilityRow, LoopOut, RideOut } from './types'

interface LoopCardProps {
  loop: LoopOut
  /** Paired PM loop (same kids, reverse direction) — renders as one driver-day card. */
  companion?: LoopOut
  drivers: DriverCapabilityRow[]
  onChanged: () => void
  index?: number
}

function minutesOf(hhmm: string | null): number | null {
  if (!hhmm) return null
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm)
  return m ? Number(m[1]) * 60 + Number(m[2]) : null
}

/** Human line for the gap between two chained legs: total minutes between
 * dropoff and next pickup, split into drive+buffer vs idle (engine slack). */
function gapLabel(prev: RideOut, next: RideOut, slack: number | undefined): string {
  const drop = minutesOf(prev.dropoff_time)
  const pickup = minutesOf(next.pickup_time)
  if (drop == null || pickup == null) return 'then'
  const total = pickup - drop
  const idle = typeof slack === 'number' ? Math.max(0, Math.round(slack)) : null
  if (idle == null) return `${total} min between rides`
  const driving = total - idle
  return idle > 0
    ? `${total} min between rides (${driving} drive + buffer, ${idle} idle)`
    : `${total} min between rides — drive + buffer, no idle time`
}

/** One half of a driver day: the ordered legs of a single loop. */
function LegList({ rides, slacks }: { rides: RideOut[]; slacks: number[] }) {
  return (
    <ol className="space-y-0.5 pl-0.5 border-l dark:border-white/10 border-gray-200">
      {rides.map((r, i) => (
        <li key={r.season_ride_id} className="pl-2.5 -ml-px border-l-2 dark:border-white/10 border-gray-200 py-0.5">
          {i > 0 && (
            <p className="text-[10px] italic dark:text-white/30 text-gray-400 pb-0.5">
              {gapLabel(rides[i - 1], r, slacks[i - 1])}
            </p>
          )}
          <p className="text-xs dark:text-white/70 text-gray-600 truncate tabular-nums">
            {formatHHMM(r.pickup_time)}–{formatHHMM(r.dropoff_time)} · {r.school_display}{' '}
            <span className="dark:text-white/30 text-gray-400">#{r.number} {r.direction}</span>
          </p>
          {studentFromNotes(r.notes) && (
            <p className="text-[11px] font-medium dark:text-white/60 text-gray-500 truncate">
              {studentFromNotes(r.notes)}
            </p>
          )}
          <p className="text-[10px] dark:text-white/35 text-gray-400 truncate">
            {r.pickup_city || '?'} → {r.dropoff_city || '?'}
          </p>
        </li>
      ))}
    </ol>
  )
}

export default function LoopCard({ loop, companion, drivers, onChanged, index = 0 }: LoopCardProps) {
  const [selectedId, setSelectedId] = useState<string>('')
  const [assigning, setAssigning] = useState(false)
  const [dismissing, setDismissing] = useState(false)
  const [conflict, setConflict] = useState<string | null>(null)

  // API serializes these top-level; meta is the legacy fallback shape.
  // With a companion, capability requirements cover BOTH halves of the day.
  const requiresProfile = useMemo(
    () => companion
      ? mergeRequiresProfiles([...loop.rides, ...companion.rides])
      : loop.requires_profile ?? loop.meta?.requires_profile ?? mergeRequiresProfiles(loop.rides),
    [loop, companion]
  )
  const slacks = loop.slack_minutes ?? loop.meta?.slack_minutes ?? []
  const companionSlacks = companion ? companion.slack_minutes ?? companion.meta?.slack_minutes ?? [] : []
  const suggestions = loop.suggestions ?? []

  const driverOptions = useMemo(
    () => drivers.map(d => ({
      ...d,
      coverage: checkCapabilityCoverage(requiresProfile, d.capabilities),
    })),
    [drivers, requiresProfile]
  )

  const isProposed = loop.status === 'proposed'
  const isConfirmed = loop.status === 'confirmed'

  async function doAssign(override: boolean) {
    if (!selectedId) return
    setAssigning(true)
    setConflict(null)
    try {
      // Assign both halves of the day — a paired PM loop always goes to the
      // same driver (same kids, reverse direction). onChanged() only fires
      // after both succeed, so a conflict on either half keeps the card open.
      await assignLoop(loop.loop_id, Number(selectedId), override)
      if (companion) await assignLoop(companion.loop_id, Number(selectedId), override)
      toast.success(companion ? `Assigned AM + PM to one driver` : `Assigned to ${loop.label}`)
      onChanged()
    } catch (e) {
      if (e instanceof AssignConflictError) {
        setConflict(e.reason)
      } else {
        toast.error(e instanceof Error ? e.message : 'Failed to assign driver')
      }
    } finally {
      setAssigning(false)
    }
  }

  async function handleDismiss() {
    setDismissing(true)
    try {
      await dismissLoop(loop.loop_id)
      if (companion) await dismissLoop(companion.loop_id)
      toast.success('Loop dismissed')
      onChanged()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to dismiss loop')
    } finally {
      setDismissing(false)
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.03, 0.3) }}
      className="rounded-xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.03] bg-white p-3.5 space-y-2.5"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold dark:text-white text-gray-800 truncate">{loop.label}</p>
          <p className="text-[11px] dark:text-white/40 text-gray-400">
            One driver · {companion ? 'AM + PM' : loop.day_part}
            {loop.days ? ` · ${loop.days.replace(/,/g, ' ')}` : ' · Mon–Fri'}
            {companion && loop.rides[0] && companion.rides.length > 0 &&
              ` · day runs ${formatHHMM(loop.rides[0].pickup_time)} → ${formatHHMM(companion.rides[companion.rides.length - 1].dropoff_time)}`}
          </p>
        </div>
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full flex-shrink-0 ${
          isConfirmed
            ? 'bg-emerald-500/15 text-emerald-400'
            : loop.status === 'dismissed'
              ? 'bg-gray-500/15 text-gray-400'
              : 'bg-amber-500/15 text-amber-400'
        }`}>
          {loop.status}
        </span>
      </div>

      <RequirementIcons requires={requiresProfile} />

      {!companion && loop.meta?.companion_hint && (
        <p className="flex items-start gap-1.5 text-[11px] dark:text-white/40 text-gray-400 italic">
          <MessageSquare className="w-3 h-3 mt-0.5 flex-shrink-0" />
          {loop.meta.companion_hint}
        </p>
      )}

      {companion ? (
        <div className="space-y-2">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-500/80 pb-1">
              Morning — take to school
            </p>
            <LegList rides={loop.rides} slacks={slacks} />
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-sky-500/80 pb-1">
              Afternoon — bring home
            </p>
            <LegList rides={companion.rides} slacks={companionSlacks} />
          </div>
        </div>
      ) : (
        <LegList rides={loop.rides} slacks={slacks} />
      )}

      {isConfirmed && (
        <p className="text-xs font-medium text-emerald-500">
          Driver: {loop.person_name || `#${loop.person_id}`}
        </p>
      )}

      {isProposed && (
        <div className="pt-2 border-t dark:border-white/[0.06] border-gray-100 space-y-2">
          {!companion && loop.extension_hint && (
            <div className="rounded-lg px-2.5 py-2 bg-emerald-500/10 border border-emerald-500/25 space-y-1.5">
              <p className="text-[11px] dark:text-emerald-300 text-emerald-700">
                Fits <span className="font-semibold">{loop.extension_hint.driver}</span>&rsquo;s existing
                day ({loop.extension_hint.label}) — same driver can take this too.
              </p>
              <button
                onClick={async () => {
                  setAssigning(true)
                  try {
                    await extendLoop(loop.extension_hint!.loop_id, loop.loop_id)
                    toast.success(`Added to ${loop.extension_hint!.driver}'s loop`)
                    onChanged()
                  } catch (e) {
                    toast.error(e instanceof Error ? e.message : 'Could not add to that loop')
                  } finally {
                    setAssigning(false)
                  }
                }}
                disabled={assigning}
                className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 transition-colors"
              >
                {assigning && <Loader2 className="w-3 h-3 animate-spin" />}
                Add to {loop.extension_hint.driver}&rsquo;s loop
              </button>
            </div>
          )}
          {suggestions.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider dark:text-white/30 text-gray-400">
                Suggested drivers
              </p>
              {suggestions.map((s, i) => (
                <button
                  key={s.person_id}
                  onClick={() => { setSelectedId(String(s.person_id)); setConflict(null) }}
                  className={`w-full text-left rounded-lg px-2 py-1.5 border transition-colors ${
                    selectedId === String(s.person_id)
                      ? 'border-[#667eea]/60 bg-[#667eea]/10'
                      : 'dark:border-white/10 border-gray-200 dark:hover:bg-white/5 hover:bg-gray-50'
                  }`}
                >
                  <p className="text-xs font-medium dark:text-white/80 text-gray-700">
                    {i === 0 && '★ '}{s.name}
                  </p>
                  <p className="text-[10px] dark:text-white/35 text-gray-400 truncate">
                    {s.reasons.join(' · ')}
                  </p>
                </button>
              ))}
            </div>
          )}
          <select
            value={selectedId}
            onChange={e => { setSelectedId(e.target.value); setConflict(null) }}
            className="w-full px-2.5 py-1.5 rounded-lg text-xs dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
          >
            <option value="">Select driver…</option>
            {driverOptions.map(d => (
              <option key={d.person_id} value={d.person_id} disabled={!d.coverage.ok}>
                {d.name}{!d.coverage.ok ? ` — missing ${d.coverage.missing.join(', ')}` : ''}
              </option>
            ))}
          </select>

          {conflict && (
            <div className="rounded-lg px-2.5 py-2 bg-red-500/10 border border-red-500/20 space-y-1.5">
              <p className="text-[11px] text-red-400">{conflict}</p>
              <button
                onClick={() => doAssign(true)}
                disabled={assigning}
                className="text-[11px] font-medium text-red-400 underline underline-offset-2 disabled:opacity-50"
              >
                Assign anyway
              </button>
            </div>
          )}

          <div className="flex gap-2">
            <button
              onClick={() => doAssign(false)}
              disabled={!selectedId || assigning}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white bg-[#667eea] hover:bg-[#5a72d8] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {assigning && <Loader2 className="w-3 h-3 animate-spin" />}
              Assign
            </button>
            <button
              onClick={handleDismiss}
              disabled={dismissing}
              title="Dismiss loop"
              className="flex items-center justify-center px-2.5 py-1.5 rounded-lg text-xs dark:text-white/40 text-gray-400 dark:hover:bg-white/5 hover:bg-gray-100 border dark:border-white/10 border-gray-200 disabled:opacity-40"
            >
              {dismissing ? <Loader2 className="w-3 h-3 animate-spin" /> : <XCircle className="w-3 h-3" />}
            </button>
          </div>
        </div>
      )}
    </motion.div>
  )
}
