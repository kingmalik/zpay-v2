'use client'

import { AnimatePresence } from 'framer-motion'
import { Route } from 'lucide-react'
import LoopCard from './LoopCard'
import type { DriverCapabilityRow, LoopOut } from './types'

interface LoopsPanelProps {
  loops: LoopOut[]
  drivers: DriverCapabilityRow[]
  onChanged: () => void
}

interface LoopEntry {
  loop: LoopOut
  companion?: LoopOut
}

/** Pair each AM loop with its companion PM loop (same kids, reverse direction)
 * so the panel shows one "driver day" card instead of two disconnected halves. */
function pairCompanions(loops: LoopOut[]): LoopEntry[] {
  const byId = new Map(loops.map(l => [l.loop_id, l]))
  const used = new Set<number>()
  const entries: LoopEntry[] = []
  for (const l of loops) {
    if (used.has(l.loop_id)) continue
    const comp = l.companion_loop_id != null ? byId.get(l.companion_loop_id) : undefined
    if (comp && !used.has(comp.loop_id) && comp.status === l.status) {
      const [am, pm] = l.day_part === 'PM' ? [comp, l] : [l, comp]
      entries.push({ loop: am, companion: pm })
      used.add(am.loop_id)
      used.add(pm.loop_id)
    } else {
      entries.push({ loop: l })
      used.add(l.loop_id)
    }
  }
  return entries
}

export default function LoopsPanel({ loops, drivers, onChanged }: LoopsPanelProps) {
  const active = loops.filter(l => l.status !== 'dismissed')
  const entries = pairCompanions(active)

  return (
    <div className="rounded-2xl border dark:border-white/8 border-gray-200 dark:bg-white/[0.02] bg-white p-4 space-y-3 lg:sticky lg:top-32 lg:max-h-[calc(100vh-9rem)] lg:overflow-y-auto">
      <div className="flex items-center gap-2">
        <Route className="w-4 h-4 text-[#667eea]" />
        <h2 className="text-sm font-semibold dark:text-white text-gray-800">Loops</h2>
        <span className="text-xs dark:text-white/30 text-gray-400 ml-auto">{entries.length}</span>
      </div>

      {active.length === 0 ? (
        <p className="text-xs dark:text-white/30 text-gray-400 italic py-6 text-center">
          No loops yet — click &ldquo;Propose loops&rdquo; to build standing driver schedules.
        </p>
      ) : (
        <div className="space-y-3">
          <AnimatePresence>
            {entries.map((entry, i) => (
              <LoopCard
                key={entry.loop.loop_id}
                loop={entry.loop}
                companion={entry.companion}
                drivers={drivers}
                onChanged={onChanged}
                index={i}
              />
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}
