'use client'

import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertTriangle, Clock } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'

// ── Types ────────────────────────────────────────────────────────────────────

interface PaystubRide {
  ride_id: number
  date: string | null
  service_name: string
  miles: number
  net_pay: number
  z_rate: number
  deduction: number
  gross_pay: number
}

interface PaystubTotals {
  rides: number
  miles: number
  net_pay: number
  z_rate: number
  deduction: number
}

interface PaystubData {
  driver: {
    id: number
    name: string
    email: string
    phone: string
    pay_code: string | null
  }
  batch: {
    id: number
    company: string
    period_start: string | null
    period_end: string | null
  }
  rides: PaystubRide[]
  totals: PaystubTotals
}

export interface PaystubDriverRef {
  id: number
  name: string
  /** net_pay for this batch only */
  net_pay: number
  /** amount carried from previous batch */
  carried_over: number
  /** combined balance (net_pay + carried_over) */
  pay_this_period: number
  status: 'paid' | 'withheld'
  manual_withhold_note?: string | null
  days: number
}

interface Props {
  batchId: number
  driver: PaystubDriverRef | null
  onClose: () => void
}

// ── Component ────────────────────────────────────────────────────────────────

export default function MomPaystubModal({ batchId, driver, onClose }: Props) {
  const [data, setData] = useState<PaystubData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!driver) return
    setData(null)
    setError(null)
    setLoading(true)
    api
      .get<PaystubData>(`/api/data/payroll-history/${batchId}/driver/${driver.id}`)
      .then(setData)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [batchId, driver])

  const isWithheld = driver?.status === 'withheld'

  return (
    <AnimatePresence>
      {driver && (
        <motion.div
          key="paystub-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/65 backdrop-blur-sm p-0 sm:p-4"
          onClick={e => { if (e.target === e.currentTarget) onClose() }}
        >
          <motion.div
            key="paystub-panel"
            initial={{ y: 40, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 40, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 300, damping: 28 }}
            className="w-full max-w-lg rounded-t-2xl sm:rounded-2xl dark:bg-[#0f0f16] bg-white border dark:border-white/10 border-gray-200 shadow-2xl overflow-hidden flex flex-col max-h-[90dvh]"
          >
            {/* Header */}
            <div className="flex items-start justify-between px-5 pt-5 pb-4 border-b dark:border-white/[0.08] border-gray-100 flex-shrink-0">
              <div>
                <h3 className="text-base font-semibold dark:text-white text-gray-900">{driver.name}</h3>
                <p className="text-xs dark:text-white/40 text-gray-400 mt-0.5">
                  {driver.days} day{driver.days !== 1 ? 's' : ''} &middot;{' '}
                  {isWithheld
                    ? <span className="text-amber-400">Carried to next week</span>
                    : <span className="text-emerald-400">Paying out</span>
                  }
                </p>
              </div>
              <button
                onClick={onClose}
                className="dark:text-white/30 text-gray-400 hover:dark:text-white/60 hover:text-gray-600 transition-colors ml-4 mt-0.5"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Withheld banner */}
            {isWithheld && (
              <div className="mx-4 mt-4 flex-shrink-0 rounded-xl bg-amber-500/8 border border-amber-500/20 px-4 py-3">
                <p className="text-xs font-semibold text-amber-400 flex items-center gap-1.5 mb-0.5">
                  <Clock className="w-3.5 h-3.5" /> Carried to next week
                </p>
                {driver.manual_withhold_note ? (
                  <p className="text-xs text-amber-400/70">{driver.manual_withhold_note}</p>
                ) : (
                  <p className="text-xs text-amber-400/70">
                    Combined balance {formatCurrency(driver.pay_this_period || driver.net_pay + driver.carried_over)} is under $100 — will carry forward.
                  </p>
                )}
              </div>
            )}

            {/* Balance summary strip */}
            <div className="grid grid-cols-3 divide-x dark:divide-white/[0.07] divide-gray-100 flex-shrink-0 mt-3 mx-4 rounded-xl dark:bg-white/[0.03] bg-gray-50 overflow-hidden border dark:border-white/[0.07] border-gray-100">
              <div className="px-3 py-2.5">
                <p className="text-[10px] uppercase tracking-wider dark:text-white/35 text-gray-400">This week</p>
                <p className="text-sm font-semibold dark:text-white text-gray-900 mt-0.5">{formatCurrency(driver.net_pay)}</p>
              </div>
              <div className="px-3 py-2.5">
                <p className="text-[10px] uppercase tracking-wider text-amber-400/70">Carried in</p>
                <p className="text-sm font-semibold text-amber-400 mt-0.5">
                  {driver.carried_over ? formatCurrency(driver.carried_over) : '—'}
                </p>
              </div>
              <div className="px-3 py-2.5">
                <p className="text-[10px] uppercase tracking-wider dark:text-white/35 text-gray-400">
                  {isWithheld ? 'Carrying out' : 'Pays out'}
                </p>
                <p className={`text-sm font-semibold mt-0.5 ${isWithheld ? 'text-amber-400' : 'text-emerald-400'}`}>
                  {formatCurrency(driver.pay_this_period || (driver.net_pay + driver.carried_over))}
                </p>
              </div>
            </div>

            {/* Rides table */}
            <div className="flex-1 overflow-y-auto mt-3">
              {loading && (
                <div className="px-5 py-8 text-center dark:text-white/30 text-gray-400 text-sm">
                  Loading rides...
                </div>
              )}
              {error && (
                <div className="mx-4 mb-4 rounded-xl bg-red-500/8 border border-red-500/20 px-4 py-3 flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0" />
                  <p className="text-xs text-red-400">{error}</p>
                </div>
              )}
              {data && data.rides.length > 0 && (
                <div className="overflow-x-auto pb-4">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b dark:border-white/[0.07] border-gray-100">
                        {['Date', 'Route', 'Miles', 'Rate', 'Pay'].map(h => (
                          <th
                            key={h}
                            className="px-4 py-2 text-left font-semibold uppercase tracking-wider dark:text-white/35 text-gray-400"
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.rides.map(r => (
                        <tr
                          key={r.ride_id}
                          className="border-b dark:border-white/[0.05] border-gray-50 dark:hover:bg-white/[0.02] hover:bg-gray-50 transition-colors"
                        >
                          <td className="px-4 py-2 dark:text-white/50 text-gray-500 whitespace-nowrap">
                            {r.date ?? '—'}
                          </td>
                          <td className="px-4 py-2 dark:text-white/80 text-gray-700 max-w-[160px] truncate">
                            {r.service_name}
                          </td>
                          <td className="px-4 py-2 dark:text-white/50 text-gray-500">
                            {r.miles > 0 ? r.miles.toFixed(1) : '—'}
                          </td>
                          <td className="px-4 py-2 dark:text-white/50 text-gray-500">
                            {r.z_rate > 0 ? formatCurrency(r.z_rate) : '—'}
                          </td>
                          <td className="px-4 py-2 text-emerald-500 font-medium">
                            {formatCurrency(r.net_pay)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {data && data.rides.length === 0 && (
                <div className="px-5 py-6 text-center dark:text-white/30 text-gray-400 text-sm">
                  No rides found for this period.
                </div>
              )}
            </div>

            {/* Footer totals */}
            {data && data.rides.length > 0 && (
              <div className="border-t dark:border-white/[0.08] border-gray-100 px-5 py-3 flex items-center justify-between flex-shrink-0 dark:bg-white/[0.02] bg-gray-50">
                <p className="text-xs dark:text-white/40 text-gray-400">
                  {data.totals.rides} ride{data.totals.rides !== 1 ? 's' : ''} &middot; {data.totals.miles.toFixed(1)} mi
                </p>
                <p className="text-sm font-semibold dark:text-white text-gray-900">
                  {formatCurrency(data.totals.net_pay)}
                </p>
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
