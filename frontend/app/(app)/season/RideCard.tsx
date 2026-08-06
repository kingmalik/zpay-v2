'use client'

import { motion } from 'framer-motion'
import { Link2, X } from 'lucide-react'
import { formatHHMM } from './utils'
import RequirementIcons from './RequirementIcons'
import type { RideOut } from './types'

interface RideCardProps {
  ride: RideOut
  onUnassign?: (ride: RideOut) => void
  onClick?: (ride: RideOut) => void
  index?: number
}

const WEEKDAY_ORDER = ['M', 'T', 'W', 'R', 'F']

function daysLabel(days: string | null): string | null {
  if (!days) return null
  const set = new Set(days.split(',').map(d => d.trim()).filter(Boolean))
  if (WEEKDAY_ORDER.every(d => set.has(d)) && set.size === WEEKDAY_ORDER.length) return null // Mon-Fri, don't show
  return WEEKDAY_ORDER.filter(d => set.has(d)).join(' ')
}

export default function RideCard({ ride, onUnassign, onClick, index = 0 }: RideCardProps) {
  const days = daysLabel(ride.days)
  const isAssigned = ride.status === 'assigned'
  const ringColor = isAssigned
    ? 'dark:border-emerald-500/25 border-emerald-300 dark:bg-emerald-500/[0.04] bg-emerald-50/40'
    : 'dark:border-amber-500/30 border-amber-300 dark:bg-amber-500/[0.04] bg-amber-50/40'

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.02, 0.3), duration: 0.2 }}
      onClick={() => onClick?.(ride)}
      className={`rounded-xl border p-3 space-y-1.5 ${ringColor} ${onClick ? 'cursor-pointer' : ''}`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium dark:text-white text-gray-800 leading-tight truncate">
          {ride.school_display}
        </p>
        <div className="flex items-center gap-1 flex-shrink-0">
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
            ride.direction === 'IB' ? 'bg-blue-500/15 text-blue-400' : 'bg-purple-500/15 text-purple-400'
          }`}>
            {ride.direction}
          </span>
          {ride.is_odt && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-orange-500/15 text-orange-400">
              ODT
            </span>
          )}
        </div>
      </div>

      <p className="text-xs dark:text-white/40 text-gray-400">
        #{ride.number} {days && <span className="ml-1.5 font-medium dark:text-white/60 text-gray-500">{days}</span>}
      </p>

      <p className="text-xs dark:text-white/50 text-gray-500 tabular-nums">
        {formatHHMM(ride.pickup_time)}–{formatHHMM(ride.dropoff_time)}
      </p>

      <div className="flex items-center justify-between gap-2 pt-1">
        <RequirementIcons requires={ride.requires} />
        {ride.loop_id != null && (
          <span title="In a loop" className="flex items-center gap-1 text-[10px] font-medium dark:text-white/40 text-gray-400">
            <Link2 className="w-3 h-3" /> loop {ride.loop_id}
          </span>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 pt-1 border-t dark:border-white/[0.06] border-gray-100">
        {isAssigned ? (
          <span className="text-xs font-medium text-emerald-500 truncate">{ride.assigned_person?.name || 'Assigned'}</span>
        ) : (
          <span className="text-xs font-medium text-amber-500">Unassigned</span>
        )}
        {isAssigned && onUnassign && (
          <button
            onClick={e => { e.stopPropagation(); onUnassign(ride) }}
            title="Unassign"
            className="p-0.5 rounded dark:hover:bg-white/10 hover:bg-gray-200 dark:text-white/30 text-gray-400"
          >
            <X className="w-3 h-3" />
          </button>
        )}
      </div>
    </motion.div>
  )
}
