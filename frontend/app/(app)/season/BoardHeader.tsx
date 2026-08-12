'use client'

import Link from 'next/link'
import { motion } from 'framer-motion'
import { Download, Loader2, School, Sliders, Upload, Wand2 } from 'lucide-react'
import { WEEKDAY_CHIPS } from './types'
import type { BoardStats, DayPart } from './types'

const DAY_PARTS: DayPart[] = ['AM', 'PM', 'MID']

interface BoardHeaderProps {
  stats: BoardStats
  districts: string[]
  district: string
  onDistrictChange: (d: string) => void
  dayPart: DayPart
  onDayPartChange: (d: DayPart) => void
  weekday: string
  onWeekdayChange: (w: string) => void
  onImportClick: () => void
  onProposeClick: () => void
  onExportClick: () => void
  proposing: boolean
}

export default function BoardHeader({
  stats, districts, district, onDistrictChange,
  dayPart, onDayPartChange, weekday, onWeekdayChange,
  onImportClick, onProposeClick, onExportClick, proposing,
}: BoardHeaderProps) {
  const pct = stats.total > 0 ? Math.round((stats.assigned / stats.total) * 100) : 0

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">2026–27 Season Board</h1>
          <p className="text-sm dark:text-white/40 text-gray-500 mt-0.5 flex items-center gap-3">
            <span>{stats.assigned} of {stats.total} assigned</span>
            <Link href="/schools" className="flex items-center gap-1 dark:text-[#7c93f0] text-[#667eea] hover:underline">
              <School className="w-3.5 h-3.5" /> Schools
            </Link>
            <Link href="/drivers/capabilities" className="flex items-center gap-1 dark:text-[#7c93f0] text-[#667eea] hover:underline">
              <Sliders className="w-3.5 h-3.5" /> Driver capabilities
            </Link>
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onExportClick}
            title="Download assigned rides as a spreadsheet to email FirstAlt"
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium dark:text-white text-gray-700 dark:bg-white/5 bg-gray-100 dark:hover:bg-white/10 hover:bg-gray-200 transition-colors"
          >
            <Download className="w-3.5 h-3.5" /> Export assigned
          </button>
          <button
            onClick={onImportClick}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium dark:text-white text-gray-700 dark:bg-white/5 bg-gray-100 dark:hover:bg-white/10 hover:bg-gray-200 transition-colors"
          >
            <Upload className="w-3.5 h-3.5" /> Import
          </button>
          <button
            onClick={onProposeClick}
            disabled={proposing}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium dark:text-white text-gray-700 dark:bg-white/5 bg-gray-100 dark:hover:bg-white/10 hover:bg-gray-200 disabled:opacity-50 transition-colors"
          >
            {proposing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
            Propose loops
          </button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-2 rounded-full dark:bg-white/8 bg-gray-100 overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.5 }}
          className="h-full rounded-full"
          style={{ background: 'linear-gradient(90deg, #667eea, #06b6d4)' }}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {/* District tabs */}
        <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100 flex-wrap">
          {['All', ...districts].map(d => (
            <button
              key={d}
              onClick={() => onDistrictChange(d === 'All' ? 'all' : d)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                (d === 'All' && district === 'all') || d === district
                  ? 'bg-[#667eea] text-white'
                  : 'dark:text-white/50 text-gray-500'
              }`}
            >
              {d}
            </button>
          ))}
        </div>

        {/* Day part toggle */}
        <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
          {DAY_PARTS.map(dp => (
            <button
              key={dp}
              onClick={() => onDayPartChange(dp)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                dayPart === dp ? 'bg-[#667eea] text-white' : 'dark:text-white/50 text-gray-500'
              }`}
            >
              {dp}
            </button>
          ))}
        </div>

        {/* Weekday chips */}
        <div className="flex gap-1">
          {WEEKDAY_CHIPS.map(w => (
            <button
              key={w.code}
              onClick={() => onWeekdayChange(w.code)}
              className={`w-7 h-7 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                weekday === w.code
                  ? 'bg-[#667eea] text-white'
                  : 'dark:bg-white/5 bg-gray-100 dark:text-white/50 text-gray-500'
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
