'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { ArrowRight, BookOpen } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import EmptyState from '@/components/ui/EmptyState'

interface PayrollBatch {
  id?: string | number
  batch_ref?: string
  company?: string
  status?: string
  period?: string
  uploaded?: string
  rides?: number
  partner_paid?: number
  driver_cost?: number
  profit?: number
  withheld?: number
  driver_payout?: number
}

export default function PayrollHistoryPage() {
  const [batches, setBatches] = useState<PayrollBatch[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<PayrollBatch[]>('/api/data/payroll-history').then(setBatches).catch(console.error).finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  const totals = batches.reduce((acc: { rides: number; partner: number; cost: number; profit: number; withheld: number; payout: number }, b) => ({
    rides: acc.rides + (b.rides || 0),
    partner: acc.partner + (b.partner_paid || 0),
    cost: acc.cost + (b.driver_cost || 0),
    profit: acc.profit + (b.profit || 0),
    withheld: acc.withheld + (b.withheld || 0),
    payout: acc.payout + (b.driver_payout || 0),
  }), { rides: 0, partner: 0, cost: 0, profit: 0, withheld: 0, payout: 0 })

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      <h1 className="text-2xl font-bold dark:text-white text-gray-900">Payroll History</h1>

      {batches.length === 0 ? (
        <EmptyState icon={<BookOpen className="w-8 h-8" />} title="No payroll batches yet" subtitle="Run payroll to create your first batch" />
      ) : (
        <div className="rounded-2xl overflow-hidden dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b dark:border-white/8 border-gray-100">
                  {['Company', 'Status', 'Batch Ref', 'Period', 'Uploaded', 'Rides', 'Partner Paid', 'Driver Cost', 'Profit', 'Withheld', 'Payout', ''].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {batches.map((b, i) => {
                  const src = (b.company || '').toLowerCase()
                  const isFa = src.includes('first') || src.includes('fa')
                  const profit = b.profit || 0
                  return (
                    <motion.tr
                      key={b.id || i}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ delay: i * 0.03 }}
                      className="border-b last:border-0 dark:border-white/5 border-gray-50 dark:hover:bg-white/3 hover:bg-gray-50 transition-colors"
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
                      <td className="px-4 py-3 font-mono text-xs dark:text-white/60 text-gray-500">{b.batch_ref || '—'}</td>
                      <td className="px-4 py-3 dark:text-white/70 text-gray-600 whitespace-nowrap">{b.period || '—'}</td>
                      <td className="px-4 py-3 dark:text-white/50 text-gray-500 whitespace-nowrap text-xs">{formatDate(b.uploaded)}</td>
                      <td className="px-4 py-3 dark:text-white/70 text-gray-600">{b.rides || 0}</td>
                      <td className="px-4 py-3 dark:text-white/80 text-gray-700">{formatCurrency(b.partner_paid)}</td>
                      <td className="px-4 py-3 dark:text-white/80 text-gray-700">{formatCurrency(b.driver_cost)}</td>
                      <td className={`px-4 py-3 font-semibold ${profit >= 0 ? 'text-emerald-500' : 'text-red-400'}`}>{formatCurrency(profit)}</td>
                      <td className="px-4 py-3 text-amber-400">{formatCurrency(b.withheld)}</td>
                      <td className="px-4 py-3 dark:text-white/80 text-gray-700">{formatCurrency(b.driver_payout)}</td>
                      <td className="px-4 py-3">
                        <Link
                          href={b.status && b.status !== 'complete' && b.status !== 'Final'
                            ? `/payroll/workflow/${b.id}`
                            : `/payroll/history/${b.id}`
                          }
                          className="flex items-center gap-1 text-xs text-[#667eea] hover:text-[#7c93f0] transition-colors"
                        >
                          {b.status && b.status !== 'complete' && b.status !== 'Final' ? 'Continue' : 'View'} <ArrowRight className="w-3 h-3" />
                        </Link>
                      </td>
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
                  <td className="px-4 py-3 dark:text-white text-gray-800">{formatCurrency(totals.payout)}</td>
                  <td />
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
