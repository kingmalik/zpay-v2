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

export default function LoopsPanel({ loops, drivers, onChanged }: LoopsPanelProps) {
  const active = loops.filter(l => l.status !== 'dismissed')

  return (
    <div className="rounded-2xl border dark:border-white/8 border-gray-200 dark:bg-white/[0.02] bg-white p-4 space-y-3 lg:sticky lg:top-32 lg:max-h-[calc(100vh-9rem)] lg:overflow-y-auto">
      <div className="flex items-center gap-2">
        <Route className="w-4 h-4 text-[#667eea]" />
        <h2 className="text-sm font-semibold dark:text-white text-gray-800">Loops</h2>
        <span className="text-xs dark:text-white/30 text-gray-400 ml-auto">{active.length}</span>
      </div>

      {active.length === 0 ? (
        <p className="text-xs dark:text-white/30 text-gray-400 italic py-6 text-center">
          No loops yet — click &ldquo;Propose loops&rdquo; to build standing driver schedules.
        </p>
      ) : (
        <div className="space-y-3">
          <AnimatePresence>
            {active.map((loop, i) => (
              <LoopCard key={loop.loop_id} loop={loop} drivers={drivers} onChanged={onChanged} index={i} />
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}
