'use client'

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Badge from '@/components/ui/Badge'

interface BatchDriver {
  person_id: number
  name: string
  paycheck_code: string
  rides: number
  gross: number
  partner_net: number
  carried_over: number
  pay_this_period: number
  withheld: boolean
  withheld_amount: number
}

interface BatchTotals {
  rides: number
  gross: number
  partner_net: number
  payout: number
  withheld: number
  margin: number
}

interface BatchData {
  batch_id: number
  period: string | null
  status: string | null
  week_start: string | null
  week_end: string | null
  drivers: BatchDriver[]
  totals: BatchTotals
}

interface SummaryOverview {
  fa: BatchData | null
  ed: BatchData | null
}

function DriverTable({ drivers, label, variant }: { drivers: BatchDriver[]; label: string; variant: 'fa' | 'ed' }) {
  const accentClass = variant === 'fa' ? 'text-indigo-400' : 'text-cyan-400'
  const bgClass = variant === 'fa' ? 'bg-indigo-500/15' : 'bg-cyan-500/15'

  if (drivers.length === 0) {
    return (
      <div className="py-8 text-center text-sm dark:text-white/30 text-gray-400">
        No drivers in this batch
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b dark:border-white/8 border-gray-100 bg-gray-50/50 dark:bg-white/[0.02]">
            {['Driver', 'Code', 'Rides', 'Driver Pay', 'Carried In', 'Paid Out', 'Status'].map(h => (
              <th key={h} className="px-3 py-2.5 text-left text-xs font-medium dark:text-white/40 text-gray-400 whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {drivers.map((d, i) => (
            <motion.tr
              key={d.person_id}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.02 }}
              className="border-b last:border-0 dark:border-white/5 border-gray-50 dark:hover:bg-white/[0.02] hover:bg-gray-50 transition-colors"
            >
              <td className="px-3 py-2.5 dark:text-white text-gray-900 font-medium">{d.name}</td>
              <td className="px-3 py-2.5 font-mono text-xs dark:text-white/40 text-gray-400">{d.paycheck_code || '—'}</td>
              <td className="px-3 py-2.5 dark:text-white/70 text-gray-600">{d.rides}</td>
              <td className="px-3 py-2.5 text-emerald-500 font-medium">{formatCurrency(d.gross)}</td>
              <td className="px-3 py-2.5 dark:text-white/50 text-gray-500 text-xs">{d.carried_over > 0 ? formatCurrency(d.carried_over) : '—'}</td>
              <td className="px-3 py-2.5 font-semibold">
                {d.withheld
                  ? <span className="text-amber-400">{formatCurrency(d.withheld_amount)} held</span>
                  : <span className="text-emerald-500">{formatCurrency(d.pay_this_period)}</span>
                }
              </td>
              <td className="px-3 py-2.5">
                {d.withheld
                  ? <Badge variant="warning" dot>Withheld</Badge>
                  : <Badge variant="success" dot>Paid</Badge>
                }
              </td>
            </motion.tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TotalsRow({ totals, variant }: { totals: BatchTotals; variant: 'fa' | 'ed' }) {
  const accentClass = variant === 'fa' ? 'text-indigo-400' : 'text-cyan-400'
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 px-4 py-3 border-t dark:border-white/8 border-gray-100 bg-gray-50/50 dark:bg-white/[0.02]">
      {[
        { label: 'Rides', value: String(totals.rides) },
        { label: 'Driver Pay', value: formatCurrency(totals.gross), cls: 'text-emerald-500' },
        { label: 'Partner Net', value: formatCurrency(totals.partner_net), cls: accentClass },
        { label: 'Payout', value: formatCurrency(totals.payout), cls: 'text-emerald-500' },
        { label: 'Withheld', value: formatCurrency(totals.withheld), cls: 'text-amber-400' },
        { label: 'Margin', value: formatCurrency(totals.margin), cls: totals.margin >= 0 ? 'text-emerald-500' : 'text-red-400' },
      ].map(({ label, value, cls = 'dark:text-white text-gray-900' }) => (
        <div key={label}>
          <p className="text-[10px] dark:text-white/30 text-gray-400 uppercase tracking-wide">{label}</p>
          <p className={`text-sm font-bold mt-0.5 ${cls}`}>{value}</p>
        </div>
      ))}
    </div>
  )
}

function BatchPanel({ data, source }: { data: BatchData; source: 'fa' | 'ed' }) {
  const label = source === 'fa' ? 'FirstAlt / Acumen' : 'EverDriven / Maz'
  const badgeVariant = source === 'fa' ? 'fa' : 'ed'
  const accentClass = source === 'fa' ? 'text-indigo-400' : 'text-cyan-400'
  const borderClass = source === 'fa' ? 'border-indigo-500/20' : 'border-cyan-500/20'

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`rounded-2xl overflow-hidden bg-white dark:bg-white/[0.03] border ${borderClass}`}
    >
      <div className={`px-4 py-3 border-b ${borderClass} flex items-center justify-between`}>
        <div className="flex items-center gap-2">
          <Badge variant={badgeVariant}>{label}</Badge>
          {data.period && (
            <span className="text-xs dark:text-white/40 text-gray-400">{data.period}</span>
          )}
        </div>
        {data.status && (
          <span className={`text-xs font-medium capitalize ${
            data.status === 'complete' ? 'text-emerald-400' :
            data.status === 'approved' ? 'text-blue-400' : 'dark:text-white/40 text-gray-400'
          }`}>
            {data.status}
          </span>
        )}
      </div>

      <DriverTable drivers={data.drivers} label={label} variant={source} />
      <TotalsRow totals={data.totals} variant={source} />
    </motion.div>
  )
}

export default function SummaryPage() {
  const [data, setData] = useState<SummaryOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<SummaryOverview>('/api/data/summary/overview')
      .then(setData)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  if (error) {
    return (
      <div className="max-w-7xl mx-auto py-10">
        <div className="rounded-2xl p-6 bg-red-500/10 border border-red-500/20 text-center">
          <p className="text-red-400 font-medium">Failed to load payroll summary</p>
          <p className="text-sm dark:text-white/40 text-gray-400 mt-1">{error}</p>
          <button
            onClick={() => { setError(null); setLoading(true); api.get<SummaryOverview>('/api/data/summary/overview').then(setData).catch(e => setError(e instanceof Error ? e.message : 'Failed')).finally(() => setLoading(false)) }}
            className="mt-4 px-4 py-2 rounded-xl text-sm bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  const totalRides = (data?.fa?.totals.rides ?? 0) + (data?.ed?.totals.rides ?? 0)
  const totalPayout = (data?.fa?.totals.payout ?? 0) + (data?.ed?.totals.payout ?? 0)
  const totalMargin = (data?.fa?.totals.margin ?? 0) + (data?.ed?.totals.margin ?? 0)

  return (
    <div className="max-w-7xl mx-auto space-y-6 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Payroll Summary</h1>
        <div className="flex items-center gap-2 text-xs dark:text-white/30 text-gray-400">
          <span>Latest batch per partner</span>
        </div>
      </div>

      {/* Combined headline stats */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Total Rides', value: String(totalRides) },
          { label: 'Total Payout', value: formatCurrency(totalPayout), cls: 'text-emerald-500' },
          { label: 'Total Margin', value: formatCurrency(totalMargin), cls: totalMargin >= 0 ? 'text-emerald-500' : 'text-red-400' },
        ].map(({ label, value, cls = 'dark:text-white text-gray-900' }, i) => (
          <motion.div
            key={label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            className="rounded-2xl p-4 bg-white dark:bg-white/[0.04] border border-gray-200 dark:border-white/8"
          >
            <p className="text-[10px] dark:text-white/30 text-gray-400 uppercase tracking-wide">{label}</p>
            <p className={`text-xl font-bold mt-1 ${cls}`}>{value}</p>
          </motion.div>
        ))}
      </div>

      {/* FA + ED side by side */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        {data?.fa ? (
          <BatchPanel data={data.fa} source="fa" />
        ) : (
          <GlassCard>
            <p className="text-sm dark:text-white/30 text-gray-400 text-center py-6">No FirstAlt batch found</p>
          </GlassCard>
        )}
        {data?.ed ? (
          <BatchPanel data={data.ed} source="ed" />
        ) : (
          <GlassCard>
            <p className="text-sm dark:text-white/30 text-gray-400 text-center py-6">No EverDriven batch found</p>
          </GlassCard>
        )}
      </div>
    </div>
  )
}
