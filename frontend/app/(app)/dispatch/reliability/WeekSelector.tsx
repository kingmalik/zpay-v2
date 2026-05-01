'use client'

import { ChevronLeft, ChevronRight, CalendarDays } from 'lucide-react'
import { cn } from '@/lib/utils'

interface WeekSelectorProps {
  weekIso: string          // e.g. "2026-W18"
  onWeekChange: (w: string) => void
  className?: string
}

// ─── ISO week helpers ─────────────────────────────────────────────────────────

/** Parse "YYYY-WNN" → Monday Date */
function isoWeekToMonday(weekIso: string): Date {
  const [yearStr, weekStr] = weekIso.split('-W')
  const year = parseInt(yearStr, 10)
  const week = parseInt(weekStr, 10)
  // Jan 4th is always in week 1
  const jan4 = new Date(year, 0, 4)
  const jan4Day = jan4.getDay() || 7  // treat Sunday as 7
  const monday = new Date(jan4)
  monday.setDate(jan4.getDate() - (jan4Day - 1) + (week - 1) * 7)
  return monday
}

/** Date → "YYYY-WNN" */
function dateToIsoWeek(d: Date): string {
  // Copy to avoid mutation
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  // Get Thursday of the current week (ISO week belongs to the year of its Thursday)
  date.setUTCDate(date.getUTCDate() + 4 - (date.getUTCDay() || 7))
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1))
  const week = Math.ceil(((date.getTime() - yearStart.getTime()) / 86400000 + 1) / 7)
  return `${date.getUTCFullYear()}-W${String(week).padStart(2, '0')}`
}

/** Shift week by ±1 */
function shiftWeek(weekIso: string, delta: number): string {
  const monday = isoWeekToMonday(weekIso)
  monday.setDate(monday.getDate() + delta * 7)
  return dateToIsoWeek(monday)
}

/** Current ISO week in PT (approximate — uses local time) */
export function currentIsoWeek(): string {
  return dateToIsoWeek(new Date())
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "Week of Apr 28 – May 4 (2026-W18)" */
function formatWeekLabel(weekIso: string): string {
  const monday = isoWeekToMonday(weekIso)
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)
  const mLabel = `${MONTHS[monday.getMonth()]} ${monday.getDate()}`
  const sLabel = `${MONTHS[sunday.getMonth()]} ${sunday.getDate()}`
  return `Week of ${mLabel} – ${sLabel} (${weekIso.replace('-W', ' W').replace(' W', '-W')})`
}

export default function WeekSelector({ weekIso, onWeekChange, className }: WeekSelectorProps) {
  const isCurrentWeek = weekIso === currentIsoWeek()

  function handlePrev() {
    onWeekChange(shiftWeek(weekIso, -1))
  }

  function handleNext() {
    onWeekChange(shiftWeek(weekIso, +1))
  }

  function handleDatePicker(e: React.ChangeEvent<HTMLInputElement>) {
    const d = new Date(e.target.value + 'T12:00:00')
    if (!isNaN(d.getTime())) {
      onWeekChange(dateToIsoWeek(d))
    }
  }

  // For the date picker default, show Monday of selected week
  const mondayStr = isoWeekToMonday(weekIso).toISOString().split('T')[0]

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <button
        onClick={handlePrev}
        aria-label="Previous week"
        className="w-8 h-8 rounded-lg flex items-center justify-center dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-500 dark:hover:bg-white/10 hover:bg-gray-200 hover:text-gray-700 dark:hover:text-white transition-all cursor-pointer"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>

      <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl dark:bg-white/5 bg-gray-50 border dark:border-white/8 border-gray-200">
        <CalendarDays className="w-3.5 h-3.5 dark:text-white/40 text-gray-400 flex-shrink-0" />
        <span className="text-sm font-medium dark:text-white/80 text-gray-700 whitespace-nowrap">
          {formatWeekLabel(weekIso)}
        </span>
        {isCurrentWeek && (
          <span className="px-1.5 py-0.5 rounded-md text-xs font-medium bg-[#667eea]/15 text-[#667eea] border border-[#667eea]/25 ml-1 flex-shrink-0">
            Current
          </span>
        )}
      </div>

      <button
        onClick={handleNext}
        aria-label="Next week"
        className="w-8 h-8 rounded-lg flex items-center justify-center dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-500 dark:hover:bg-white/10 hover:bg-gray-200 hover:text-gray-700 dark:hover:text-white transition-all cursor-pointer"
      >
        <ChevronRight className="w-4 h-4" />
      </button>

      {/* Date picker fallback — compact icon button */}
      <label
        className="w-8 h-8 rounded-lg flex items-center justify-center dark:bg-white/5 bg-gray-100 dark:text-white/40 text-gray-400 dark:hover:bg-white/10 hover:bg-gray-200 transition-all cursor-pointer relative"
        title="Jump to date"
      >
        <CalendarDays className="w-3.5 h-3.5 pointer-events-none" />
        <input
          type="date"
          value={mondayStr}
          onChange={handleDatePicker}
          className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
          aria-label="Jump to week containing date"
        />
      </label>
    </div>
  )
}
