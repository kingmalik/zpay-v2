'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import EmptyState from './EmptyState'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export interface Column<T = any> {
  key: string
  label: string
  sortable?: boolean
  className?: string
  render?: (row: T) => React.ReactNode
  mobileHide?: boolean
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
interface DataTableProps<T = any> {
  columns: Column<T>[]
  data: T[]
  keyField?: string
  emptyTitle?: string
  emptySubtitle?: string
  mobileCard?: (row: T) => React.ReactNode
  rowClassName?: (row: T) => string
  className?: string
  pageSize?: number
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export default function DataTable<T = any>({
  columns, data, keyField = 'id',
  emptyTitle = 'No data', emptySubtitle,
  mobileCard, rowClassName, className, pageSize = 50,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(1)

  function handleSort(key: string) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
    setPage(1)
  }

  const sorted = sortKey
    ? [...data].sort((a, b) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const av = (a as any)[sortKey], bv = (b as any)[sortKey]
        if (av == null) return 1
        if (bv == null) return -1
        const cmp = av < bv ? -1 : av > bv ? 1 : 0
        return sortDir === 'asc' ? cmp : -cmp
      })
    : data

  const total = sorted.length
  const pages = Math.ceil(total / pageSize)
  const paged = sorted.slice((page - 1) * pageSize, page * pageSize)

  if (data.length === 0) {
    return <EmptyState title={emptyTitle} subtitle={emptySubtitle} />
  }

  return (
    <div className={cn('space-y-3', className)}>
      {/* Desktop table */}
      <div className="hidden md:block rounded-xl dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
        <table className="w-full text-sm table-fixed">
          <thead>
            <tr className="border-b dark:border-white/8 border-gray-100">
              {columns.map(col => (
                <th
                  key={col.key}
                  className={cn(
                    'px-4 py-3 text-left font-medium dark:text-white/50 text-gray-500 whitespace-nowrap',
                    col.sortable && 'cursor-pointer hover:dark:text-white/80 hover:text-gray-700 select-none',
                    col.className
                  )}
                  onClick={() => col.sortable && handleSort(col.key)}
                >
                  <div className="flex items-center gap-1">
                    {col.label}
                    {col.sortable && (
                      sortKey === col.key
                        ? sortDir === 'asc'
                          ? <ChevronUp className="w-3.5 h-3.5 text-[#667eea]" />
                          : <ChevronDown className="w-3.5 h-3.5 text-[#667eea]" />
                        : <ChevronsUpDown className="w-3.5 h-3.5 opacity-30" />
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paged.map((row, i) => {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const rowAny = row as any
              return (
              <motion.tr
                key={String(rowAny[keyField] ?? i)}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.02 }}
                className={cn(
                  'border-b last:border-0 dark:border-white/5 border-gray-50 transition-colors',
                  'dark:hover:bg-white/3 hover:bg-gray-50',
                  rowClassName?.(row)
                )}
              >
                {columns.map(col => (
                  <td
                    key={col.key}
                    className={cn('px-4 py-3 dark:text-white/80 text-gray-700 truncate', col.className)}
                  >
                    {col.render ? col.render(row) : String(rowAny[col.key] ?? '—')}
                  </td>
                ))}
              </motion.tr>
            )})}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="md:hidden space-y-2">
        {paged.map((row, i) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const mobileRowAny = row as any
          return mobileCard ? (
            <div key={String(mobileRowAny[keyField] ?? i)}>{mobileCard(row)}</div>
          ) : (
            <div
              key={String(mobileRowAny[keyField] ?? i)}
              className={cn(
                'rounded-xl p-4 dark:bg-white/5 dark:border dark:border-white/10 bg-white border border-gray-200',
                rowClassName?.(row)
              )}
            >
              {columns.filter(c => !c.mobileHide).map(col => (
                <div key={col.key} className="flex justify-between py-1.5 border-b last:border-0 dark:border-white/5 border-gray-50">
                  <span className="text-xs dark:text-white/40 text-gray-400">{col.label}</span>
                  <span className="text-xs dark:text-white/80 text-gray-700 text-right max-w-[60%]">
                    {col.render ? col.render(row) : String(mobileRowAny[col.key] ?? '—')}
                  </span>
                </div>
              ))}
            </div>
          )
        })}
      </div>

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <p className="text-xs dark:text-white/40 text-gray-400">
            {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}
          </p>
          <div className="flex gap-1">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 rounded-lg text-xs dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-600 disabled:opacity-40 cursor-pointer hover:dark:bg-white/10 hover:bg-gray-200 transition-all"
            >
              Prev
            </button>
            <button
              onClick={() => setPage(p => Math.min(pages, p + 1))}
              disabled={page === pages}
              className="px-3 py-1.5 rounded-lg text-xs dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-600 disabled:opacity-40 cursor-pointer hover:dark:bg-white/10 hover:bg-gray-200 transition-all"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
