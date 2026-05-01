'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { TrendingDown, TrendingUp, DollarSign, RefreshCw, ChevronUp, ChevronDown } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import StatCard from '@/components/ui/StatCard'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

interface RouteMargin {
  service_name: string
  ride_count: number
  partner_paid: number
  driver_pay: number
  margin: number
  margin_pct: number | null
}

interface MarginTotals {
  total_partner_paid: number
  total_driver_pay: number
  total_margin: number
  margin_pct: number | null
}

interface MarginData {
  from: string
  to: string
  ride_count: number
  totals: MarginTotals
  by_route: RouteMargin[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt$(n: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(n)
}

function fmtPct(n: number | null): string {
  if (n === null || n === undefined) return '—'
  return `${n.toFixed(1)}%`
}

type SortKey = 'service_name' | 'ride_count' | 'partner_paid' | 'driver_pay' | 'margin' | 'margin_pct'

// ── Route table ───────────────────────────────────────────────────────────────

function RouteTable({ routes }: { routes: RouteMargin[] }) {
  const [sortKey, setSortKey] = useState<SortKey>('margin')
  const [sortAsc, setSortAsc] = useState(true)

  const sorted = [...routes].sort((a, b) => {
    const av = a[sortKey] ?? 0
    const bv = b[sortKey] ?? 0
    if (typeof av === 'string' && typeof bv === 'string') {
      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av)
    }
    const an = Number(av)
    const bn = Number(bv)
    return sortAsc ? an - bn : bn - an
  })

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortAsc(a => !a)
    } else {
      setSortKey(key)
      setSortAsc(true)
    }
  }

  function SortIcon({ col }: { col: SortKey }) {
    if (sortKey !== col) return <span className="w-3 h-3" />
    return sortAsc
      ? <ChevronUp className="w-3 h-3" />
      : <ChevronDown className="w-3 h-3" />
  }

  const cols: { key: SortKey; label: string; right?: boolean }[] = [
    { key: 'service_name', label: 'Route' },
    { key: 'ride_count',   label: 'Rides',       right: true },
    { key: 'partner_paid', label: 'Partner Paid', right: true },
    { key: 'driver_pay',   label: 'Driver Pay',   right: true },
    { key: 'margin',       label: 'Margin $',     right: true },
    { key: 'margin_pct',   label: 'Margin %',     right: true },
  ]

  return (
    <div className="overflow-x-auto rounded-xl border dark:border-white/[0.08] border-gray-200">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b dark:border-white/[0.08] border-gray-100">
            {cols.map(c => (
              <th
                key={c.key}
                onClick={() => toggleSort(c.key)}
                className={cn(
                  'px-4 py-3 font-semibold text-[11px] uppercase tracking-wider cursor-pointer select-none',
                  'dark:text-white/40 text-gray-400 dark:hover:text-white/70 hover:text-gray-600 transition-colors',
                  c.right ? 'text-right' : 'text-left'
                )}
              >
                <span className="inline-flex items-center gap-1">
                  {c.label}
                  <SortIcon col={c.key} />
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const isNeg = r.margin < 0
            const isLow = r.margin_pct !== null && r.margin_pct < 10
            return (
              <motion.tr
                key={r.service_name}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.22, delay: i * 0.03 }}
                className={cn(
                  'border-b last:border-0 dark:border-white/[0.05] border-gray-50 transition-colors duration-100',
                  'dark:hover:bg-white/[0.03] hover:bg-gray-50/50'
                )}
              >
                <td className="px-4 py-3 font-medium dark:text-white text-gray-900">{r.service_name}</td>
                <td className="px-4 py-3 text-right dark:text-white/60 text-gray-500 tabular-nums">{r.ride_count}</td>
                <td className="px-4 py-3 text-right dark:text-white/60 text-gray-500 tabular-nums">{formatCurrency(r.partner_paid)}</td>
                <td className="px-4 py-3 text-right dark:text-white/60 text-gray-500 tabular-nums">{formatCurrency(r.driver_pay)}</td>
                <td className={cn(
                  'px-4 py-3 text-right font-semibold tabular-nums',
                  isNeg ? 'text-red-400' : isLow ? 'text-amber-400' : 'text-emerald-400'
                )}>
                  {isNeg ? '-' : ''}{formatCurrency(Math.abs(r.margin))}
                </td>
                <td className={cn(
                  'px-4 py-3 text-right font-medium tabular-nums',
                  isNeg ? 'text-red-400' : isLow ? 'text-amber-400' : 'text-emerald-400'
                )}>
                  {fmtPct(r.margin_pct)}
                </td>
              </motion.tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

const RANGE_OPTS = [
  { label: '7 days',  days: 7 },
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
]

export default function MarginPage() {
  const [data, setData] = useState<MarginData | null>(null)
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(30)
  const [source, setSource] = useState<'all' | 'acumen' | 'maz'>('all')
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const today = new Date()
      const from = new Date(today)
      from.setDate(from.getDate() - days)
      const fromStr = from.toISOString().slice(0, 10)
      const toStr = today.toISOString().slice(0, 10)

      const params = new URLSearchParams({ from: fromStr, to: toStr })
      if (source !== 'all') params.set('source', source)

      const result = await api.get<MarginData>(`/api/data/margin/routes?${params}`)
      setData(result)
    } catch (err) {
      console.error('[MarginPage] load failed', err)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [days, source])

  useEffect(() => { load() }, [load])

  function refresh() {
    setRefreshing(true)
    load()
  }

  const totals = data?.totals
  const worstRoutes = data?.by_route.slice(0, 3) ?? []

  return (
    <div className="max-w-6xl mx-auto space-y-6 py-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold dark:text-white text-gray-900">Margin</h1>
          <p className="text-sm dark:text-white/40 text-gray-400 mt-0.5">
            Partner paid − driver pay, per route
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm dark:text-white/50 text-gray-500 dark:hover:bg-white/[0.06] hover:bg-gray-100 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn('w-4 h-4', refreshing && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        {/* Date range */}
        <div className="flex rounded-xl overflow-hidden border dark:border-white/[0.08] border-gray-200">
          {RANGE_OPTS.map(o => (
            <button
              key={o.days}
              onClick={() => setDays(o.days)}
              className={cn(
                'px-4 py-2 text-sm font-medium transition-colors duration-100',
                days === o.days
                  ? 'dark:bg-white/10 bg-gray-100 dark:text-white text-gray-900'
                  : 'dark:text-white/40 text-gray-400 dark:hover:bg-white/[0.06] hover:bg-gray-50'
              )}
            >
              {o.label}
            </button>
          ))}
        </div>

        {/* Source */}
        <div className="flex rounded-xl overflow-hidden border dark:border-white/[0.08] border-gray-200">
          {(['all', 'acumen', 'maz'] as const).map(s => (
            <button
              key={s}
              onClick={() => setSource(s)}
              className={cn(
                'px-4 py-2 text-sm font-medium transition-colors duration-100',
                source === s
                  ? 'dark:bg-white/10 bg-gray-100 dark:text-white text-gray-900'
                  : 'dark:text-white/40 text-gray-400 dark:hover:bg-white/[0.06] hover:bg-gray-50'
              )}
            >
              {s === 'all' ? 'All' : s === 'acumen' ? 'FirstAlt' : 'EverDriven'}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <LoadingSpinner />
      ) : !data ? (
        <p className="text-sm dark:text-white/40 text-gray-400">Failed to load margin data.</p>
      ) : (
        <AnimatePresence mode="wait">
          <motion.div
            key={`${days}-${source}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="space-y-6"
          >
            {/* Stat cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <StatCard
                label="Partner Paid"
                value={fmt$(totals?.total_partner_paid ?? 0)}
                icon={<DollarSign className="w-4 h-4" />}
                color="info"
                index={0}
              />
              <StatCard
                label="Driver Pay"
                value={fmt$(totals?.total_driver_pay ?? 0)}
                icon={<DollarSign className="w-4 h-4" />}
                color="default"
                index={1}
              />
              <StatCard
                label="Total Margin"
                value={fmt$(totals?.total_margin ?? 0)}
                icon={(totals?.total_margin ?? 0) >= 0
                  ? <TrendingUp className="w-4 h-4" />
                  : <TrendingDown className="w-4 h-4" />
                }
                color={(totals?.total_margin ?? 0) >= 0 ? 'success' : 'danger'}
                index={2}
              />
              <StatCard
                label="Margin %"
                value={fmtPct(totals?.margin_pct ?? null)}
                icon={<TrendingUp className="w-4 h-4" />}
                color={(totals?.margin_pct ?? 0) >= 15 ? 'success' : (totals?.margin_pct ?? 0) >= 5 ? 'warning' : 'danger'}
                index={3}
              />
            </div>

            {/* Worst routes callout */}
            {worstRoutes.length > 0 && worstRoutes[0].margin < 20 && (
              <div className="rounded-xl p-4 dark:bg-amber-500/5 bg-amber-50 border dark:border-amber-500/20 border-amber-200">
                <p className="text-xs font-semibold uppercase tracking-wider dark:text-amber-400 text-amber-600 mb-2">
                  Lowest-margin routes
                </p>
                <div className="flex flex-wrap gap-3">
                  {worstRoutes.map(r => (
                    <span
                      key={r.service_name}
                      className={cn(
                        'px-3 py-1.5 rounded-lg text-sm font-medium',
                        r.margin < 0
                          ? 'dark:bg-red-500/15 dark:text-red-300 bg-red-100 text-red-700'
                          : 'dark:bg-amber-500/15 dark:text-amber-300 bg-amber-100 text-amber-700'
                      )}
                    >
                      {r.service_name}
                      {' '}
                      <span className="opacity-70">
                        {formatCurrency(r.margin)} ({fmtPct(r.margin_pct)})
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Route breakdown table */}
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider dark:text-white/30 text-gray-400 mb-3">
                By Route — {data.ride_count} rides · {data.from} to {data.to}
              </p>
              {data.by_route.length === 0 ? (
                <p className="text-sm dark:text-white/30 text-gray-400 py-8 text-center">
                  No rides in this date range.
                </p>
              ) : (
                <RouteTable routes={data.by_route} />
              )}
            </div>
          </motion.div>
        </AnimatePresence>
      )}
    </div>
  )
}
