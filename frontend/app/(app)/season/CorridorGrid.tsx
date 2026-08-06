'use client'

import { motion } from 'framer-motion'
import { ArrowRight } from 'lucide-react'
import RideCard from './RideCard'
import type { Corridor, RideOut } from './types'

interface CorridorGridProps {
  corridors: Corridor[]
  onUnassign: (ride: RideOut) => void
}

export default function CorridorGrid({ corridors, onUnassign }: CorridorGridProps) {
  if (corridors.length === 0) {
    return (
      <div className="text-center py-16 dark:text-white/30 text-gray-400 text-sm rounded-2xl border dark:border-white/8 border-gray-200">
        No rides match this filter yet.
      </div>
    )
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 items-start">
      {corridors.map((corridor, ci) => (
        <motion.div
          key={`${corridor.pickup_city}-${corridor.dropoff_city}-${ci}`}
          layout
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: Math.min(ci * 0.03, 0.4) }}
          className="rounded-2xl border dark:border-white/8 border-gray-200 dark:bg-white/[0.02] bg-white overflow-hidden"
        >
          <div className="px-4 py-2.5 border-b dark:border-white/8 border-gray-100 flex items-center gap-1.5 dark:bg-white/[0.02] bg-gray-50/60">
            <span className="text-sm font-semibold dark:text-white text-gray-800">{corridor.pickup_city || 'Unknown'}</span>
            <ArrowRight className="w-3.5 h-3.5 dark:text-white/30 text-gray-400" />
            <span className="text-sm font-semibold dark:text-white text-gray-800">{corridor.dropoff_city || 'Unknown'}</span>
            <span className="ml-auto text-xs dark:text-white/30 text-gray-400">{corridor.rides.length}</span>
          </div>
          <div className="p-3 space-y-2.5">
            {corridor.rides.map((ride, ri) => (
              <RideCard key={ride.season_ride_id} ride={ride} onUnassign={onUnassign} index={ri} />
            ))}
          </div>
        </motion.div>
      ))}
    </div>
  )
}
