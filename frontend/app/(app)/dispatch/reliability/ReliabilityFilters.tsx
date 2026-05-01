'use client'

import { Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'

export type TierFilter = 'all' | 'gold' | 'silver' | 'bronze' | 'probation'

interface ReliabilityFiltersProps {
  tierFilter: TierFilter
  onTierChange: (t: TierFilter) => void
  minTrips: number
  onMinTripsChange: (n: number) => void
  search: string
  onSearchChange: (s: string) => void
  className?: string
}

const TIER_OPTIONS: { value: TierFilter; label: string }[] = [
  { value: 'all',       label: 'All Tiers' },
  { value: 'gold',      label: 'Gold' },
  { value: 'silver',    label: 'Silver' },
  { value: 'bronze',    label: 'Bronze' },
  { value: 'probation', label: 'Probation' },
]

export default function ReliabilityFilters({
  tierFilter, onTierChange,
  minTrips, onMinTripsChange,
  search, onSearchChange,
  className,
}: ReliabilityFiltersProps) {
  return (
    <div className={cn('flex flex-wrap items-center gap-3', className)}>
      {/* Tier pills */}
      <div className="flex gap-0.5 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
        {TIER_OPTIONS.map(opt => (
          <button
            key={opt.value}
            onClick={() => onTierChange(opt.value)}
            className={cn(
              'px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer whitespace-nowrap',
              tierFilter === opt.value
                ? 'bg-[#667eea] text-white shadow-sm'
                : 'dark:text-white/50 text-gray-500 hover:dark:text-white/80 hover:text-gray-700'
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Min trips */}
      <div className="flex items-center gap-2">
        <label className="text-xs dark:text-white/40 text-gray-400 whitespace-nowrap">
          Min trips
        </label>
        <input
          type="number"
          min={0}
          max={50}
          value={minTrips}
          onChange={e => onMinTripsChange(Math.max(0, parseInt(e.target.value, 10) || 0))}
          className="w-14 px-2 py-1.5 rounded-lg text-xs dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60 transition-all text-center"
        />
      </div>

      {/* Name search */}
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 dark:text-white/30 text-gray-400 pointer-events-none" />
        <input
          type="text"
          placeholder="Search driver"
          value={search}
          onChange={e => onSearchChange(e.target.value)}
          className="pl-7 pr-7 py-1.5 rounded-lg text-xs dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white/80 text-gray-700 placeholder:dark:text-white/25 placeholder:text-gray-400 focus:outline-none focus:border-[#667eea]/60 transition-all w-44"
        />
        {search && (
          <button
            onClick={() => onSearchChange('')}
            className="absolute right-2 top-1/2 -translate-y-1/2 dark:text-white/30 text-gray-400 hover:dark:text-white/60 hover:text-gray-600 cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}
