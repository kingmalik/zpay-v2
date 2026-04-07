'use client'

import { cn } from '@/lib/utils'

interface FilterBarProps {
  company: string
  onCompanyChange: (c: string) => void
  dateFrom?: string
  dateTo?: string
  onDateFromChange?: (d: string) => void
  onDateToChange?: (d: string) => void
  showDates?: boolean
  className?: string
}

const COMPANY_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'fa', label: 'FirstAlt' },
  { value: 'ed', label: 'EverDriven' },
]

export default function FilterBar({
  company, onCompanyChange,
  dateFrom, dateTo,
  onDateFromChange, onDateToChange,
  showDates = false,
  className,
}: FilterBarProps) {
  return (
    <div className={cn('flex flex-wrap items-center gap-3', className)}>
      {/* Company pills */}
      <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
        {COMPANY_OPTIONS.map(opt => (
          <button
            key={opt.value}
            onClick={() => onCompanyChange(opt.value)}
            className={cn(
              'px-3 py-1.5 rounded-lg text-sm font-medium transition-all cursor-pointer',
              company === opt.value
                ? 'bg-[#667eea] text-white shadow-sm'
                : 'dark:text-white/50 text-gray-500 hover:dark:text-white/80 hover:text-gray-700'
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Date range */}
      {showDates && (
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={dateFrom || ''}
            onChange={e => onDateFromChange?.(e.target.value)}
            className="px-3 py-1.5 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60 transition-all"
          />
          <span className="dark:text-white/40 text-gray-400 text-sm">to</span>
          <input
            type="date"
            value={dateTo || ''}
            onChange={e => onDateToChange?.(e.target.value)}
            className="px-3 py-1.5 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60 transition-all"
          />
        </div>
      )}
    </div>
  )
}
