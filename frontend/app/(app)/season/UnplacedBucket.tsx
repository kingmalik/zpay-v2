'use client'

import { motion } from 'framer-motion'
import { AlertTriangle } from 'lucide-react'
import { formatHHMM } from './utils'
import type { RideOut } from './types'

interface UnplacedBucketProps {
  rides: RideOut[]
  onEdit: (ride: RideOut) => void
}

export default function UnplacedBucket({ rides, onEdit }: UnplacedBucketProps) {
  if (rides.length === 0) return null

  return (
    <div>
      <h2 className="text-xs font-semibold uppercase tracking-wider text-amber-400 mb-3 flex items-center gap-2">
        <AlertTriangle className="w-3.5 h-3.5" />
        Needs info ({rides.length})
      </h2>
      <div className="rounded-2xl border-2 border-amber-500/30 bg-amber-500/5 divide-y dark:divide-amber-500/10 divide-amber-100">
        {rides.map((ride, i) => (
          <motion.button
            key={ride.season_ride_id}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: Math.min(i * 0.02, 0.3) }}
            onClick={() => onEdit(ride)}
            className="w-full px-4 py-3 flex items-center justify-between gap-3 text-left dark:hover:bg-amber-500/5 hover:bg-amber-50/60 transition-colors"
          >
            <div className="min-w-0">
              <p className="text-sm dark:text-white/80 text-gray-700 truncate">
                {ride.school_display} <span className="dark:text-white/30 text-gray-400">#{ride.number} {ride.direction}</span>
              </p>
              <p className="text-xs text-amber-400/80 tabular-nums">
                {formatHHMM(ride.pickup_time)}–{formatHHMM(ride.dropoff_time)}
              </p>
            </div>
            <div className="flex gap-1.5 flex-shrink-0">
              {ride.needs.address && (
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-400">
                  needs address
                </span>
              )}
              {ride.needs.time && (
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-400">
                  needs time
                </span>
              )}
            </div>
          </motion.button>
        ))}
      </div>
    </div>
  )
}
