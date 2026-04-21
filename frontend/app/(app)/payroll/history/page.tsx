'use client'

import { useEffect, useState, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { BookOpen } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import EmptyState from '@/components/ui/EmptyState'
import PageHeader from '@/components/ui/PageHeader'

interface PayrollBatch {
  id?: string | number
  batch_ref?: string
  company?: string
  status?: string
  week_label?: string
  period?: string
  uploaded?: string
  rides?: number
  partner_paid?: number
  driver_cost?: number
  profit?: number
  withheld?: number
  driver_payout?: number
}

const COMPANIES = ['All', 'FirstAlt', 'EverDriven'] as const
type CompanyFilter = typeof COMPANIES[number]

export default function PayrollHistoryPage() {
  const router = useRouter()
  const [batches, setBatches] = useState<PayrollBatch[]>([])
  const [loading, setLoading] = useState(true)
  const [company, setCompany] = useState<CompanyFilter>('All')
  const [weekFilter, setWeekFilter] = useState<string>('All')

  useEffect(() => {
    api.get<PayrollBatch[]>('/api/data/payroll-history').then(setBatches).catch(console.error).finally(() => setLoading(false))
  }, [])

  const weeks = useMemo(() => {
    const seen = new Set<string>()
    const out: string[] = ['All']
    batches.forEach(b => { if (b.week_label && !seen.has(b.week_label)) { seen.add(b.week_label); out.push(b.week_label) } })
    return out
  }, [batches])

  const filtered = useMemo(() => batches.filter(b => {
    const src = (b.company || '').toLowerCase()
    if (company === 'FirstAlt' && !src.includes('first') && !src.includes('fa')) return false
    if (company === 'EverDriven' && !src.includes('ever') && !src.includes('ed')) return false
    if (weekFilter !== 'All' && b.week_label !== weekFilter) return false
    return true
  }), [batches, company, weekFilter])

  const totals = filtered.reduce((acc: { rides: number; partner: number; cost: number; profit: number; withheld: number }, b) => ({
    rides: acc.rides + (b.rides || 0),
    partner: acc.partner + (b.partner_paid || 0),
    cost: acc.cost + (b.driver_cost || 0),
    profit: acc.profit + (b.profit || 0),
    withheld: acc.withheld + (b.withheld || 0),
  }), { rides: 0, partner: 0, cost: 0, profit: 0, withheld: 0 })

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      <PageHeader
        title="Payroll History"
        subtitle="All payroll runs, by batch"
        icon={<BookOpen className="w-4 h-4" />}
      />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Company tabs */}
        <div className="flex items-center gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
          {COMPANIES.map(c => (
            <button
              key={c}
              onClick={() => setCompany(c)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                company === c
                  ? 'bg-[#667eea] text-white shadow-sm'
                  : 'dark:text-white/50 text-gray-500 dark:hover:text-white/80 hover:text-gray-700'
              }`}
            >
              {c}
            </button>
          ))}
        </div>

        {/* Week filter */}
        <select
          value={weekFilter}
          onChange={e => setWeekFilter(e.target.value)}
          className="px-3 py-1.5 rounded-xl text-xs font-medium dark:bg-white/5 bg-gray-100 dark:text-white/70 text-gray-600 border dark:border-white/10 border-gray-200 cursor-pointer focus:outline-none"
        >
          {weeks.map(w => <option key={w} value={w}>{w}</option>)}
        </select>

        <span className="text-xs dark:text-white/30 text-gray-400 ml-auto">{filtered.length} batch{filtered.length !== 1 ? 'es' : ''}</span>
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon={<BookOpen className="w-8 h-8" />} title="No batches match" subtitle="Try adjusting the filters" />
      ) : (
        <div data-tour="payroll-list" className="rounded-2xl overflow-hidden dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b dark:border-white/8 border-gray-100">
                  {['Company', 'Status', 'Week', 'Period', 'Uploaded', 'Rides', 'Partner Paid', 'Driver Cost', 'Profit', 'Withheld'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((b, i) => {
                  const src = (b.company || '').toLowerCase()
                  const isFa = src.includes('first') || src.includes('fa')
                  const profit = b.profit || 0
                  return (
                    <motion.tr
                      key={b.id || i}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ delay: i * 0.02 }}
                      onClick={() => b.id && router.push(`/payroll/history/${b.id}`)}
                      className="border-b last:border-0 dark:border-white/5 border-gray-50 dark:hover:bg-white/5 hover:bg-gray-50 transition-colors cursor-pointer"
                    >
                      <td className="px-4 py-3">
                        <Badge variant={isFa ? 'fa' : 'ed'}>{b.company || '—'}</Badge>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={
                          b.status === 'complete' ? 'final'
                          : b.status === 'approved' || b.status === 'export_ready' ? 'success'
                          : b.status === 'rates_review' || b.status === 'stubs_sending' ? 'warning'
                          : b.status === 'payroll_review' ? 'info'
                          : b.status?.toLowerCase() === 'final' ? 'final'
                          : 'draft'
                        }>
                          {b.status === 'rates_review' ? 'Rates Review'
                          : b.status === 'payroll_review' ? 'Payroll Review'
                          : b.status === 'export_ready' ? 'Export Ready'
                          : b.status === 'stubs_sending' ? 'Sending Stubs'
                          : b.status === 'complete' ? 'Complete'
                          : b.status === 'approved' ? 'Approved'
                          : b.status || 'Draft'}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 font-medium dark:text-white/80 text-gray-700 whitespace-nowrap">{b.week_label || '—'}</td>
                      <td className="px-4 py-3 dark:text-white/70 text-gray-600 whitespace-nowrap">{b.period || '—'}</td>
                      <td className="px-4 py-3 dark:text-white/50 text-gray-500 whitespace-nowrap text-xs">{formatDate(b.uploaded)}</td>
                      <td className="px-4 py-3 dark:text-white/70 text-gray-600">{b.rides || 0}</td>
                      <td className="px-4 py-3 dark:text-white/80 text-gray-700">{formatCurrency(b.partner_paid)}</td>
                      <td className="px-4 py-3 dark:text-white/80 text-gray-700">{formatCurrency(b.driver_cost)}</td>
                      <td className={`px-4 py-3 font-semibold ${profit >= 0 ? 'text-emerald-500' : 'text-red-400'}`}>{formatCurrency(profit)}</td>
                      <td className="px-4 py-3 text-amber-400">{formatCurrency(b.withheld)}</td>
                    </motion.tr>
                  )
                })}
                {/* Totals */}
                <tr className="border-t-2 dark:border-white/20 border-gray-300 dark:bg-white/3 bg-gray-50 font-semibold text-sm">
                  <td colSpan={5} className="px-4 py-3 dark:text-white/50 text-gray-500">Totals</td>
                  <td className="px-4 py-3 dark:text-white text-gray-800">{totals.rides}</td>
                  <td className="px-4 py-3 dark:text-white text-gray-800">{formatCurrency(totals.partner)}</td>
                  <td className="px-4 py-3 dark:text-white text-gray-800">{formatCurrency(totals.cost)}</td>
                  <td className={`px-4 py-3 ${totals.profit >= 0 ? 'text-emerald-500' : 'text-red-400'}`}>{formatCurrency(totals.profit)}</td>
                  <td className="px-4 py-3 text-amber-400">{formatCurrency(totals.withheld)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
