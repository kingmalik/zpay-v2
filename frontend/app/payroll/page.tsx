'use client'

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Play, Download, CheckSquare, Users, DollarSign, Calendar } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import StatCard from '@/components/ui/StatCard'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import EmptyState from '@/components/ui/EmptyState'

interface DriverPayroll {
  id?: string | number
  name?: string
  pay_code?: string
  days?: number
  net_pay?: number
  carried_over?: number
  pay_this_period?: number
  status?: string
  override?: boolean
  withheld?: boolean
}

interface PayrollSummary {
  company?: string
  period?: string
  periods?: string[]
  drivers?: DriverPayroll[]
  withheld?: DriverPayroll[]
  stats?: { driver_count?: number; total_pay?: number; withheld_amount?: number }
}

export default function PayrollPage() {
  const [data, setData] = useState<PayrollSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [company, setCompany] = useState('all')

  function companyParam(c: string) {
    if (c === 'fa') return '?company=fa'
    if (c === 'ed') return '?company=ed'
    return ''
  }

  useEffect(() => {
    setLoading(true)
    api.get<PayrollSummary>(`/api/data/summary${companyParam(company)}`).then(setData).catch(console.error).finally(() => setLoading(false))
  }, [company])

  async function runPayroll() {
    setRunning(true)
    try {
      await api.post('/summary/run')
      const d = await api.get<PayrollSummary>(`/api/data/summary${companyParam(company)}`)
      setData(d)
    } catch (e) { console.error(e) }
    finally { setRunning(false) }
  }

  if (loading) return <LoadingSpinner fullPage />

  const allDrivers = data?.drivers || []
  const withheld = data?.withheld || []
  const stats = data?.stats || {}

  const totals = allDrivers.reduce((acc: { days: number; net_pay: number; carried: number; period: number }, d) => ({
    days: acc.days + (d.days || 0),
    net_pay: acc.net_pay + (d.net_pay || 0),
    carried: acc.carried + (d.carried_over || 0),
    period: acc.period + (d.pay_this_period || 0),
  }), { days: 0, net_pay: 0, carried: 0, period: 0 })

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Payroll Summary</h1>
        <div className="flex items-center gap-2">
          <a
            href="/api/v1/summary/export/excel"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium dark:bg-white/8 bg-gray-100 dark:text-white/70 text-gray-600 hover:dark:bg-white/12 hover:bg-gray-200 transition-all"
          >
            <Download className="w-4 h-4" />
            Export
          </a>
          <button
            onClick={runPayroll}
            disabled={running}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all cursor-pointer disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
          >
            <Play className="w-4 h-4" />
            {running ? 'Running...' : 'Run Payroll'}
          </button>
        </div>
      </div>

      {/* Company + period filters */}
      <div className="flex flex-wrap gap-3">
        <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
          {[['all', 'All'], ['fa', 'FirstAlt'], ['ed', 'EverDriven']].map(([v, l]) => (
            <button key={v} onClick={() => setCompany(v)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all cursor-pointer ${company === v ? 'bg-[#667eea] text-white' : 'dark:text-white/50 text-gray-500'}`}>
              {l}
            </button>
          ))}
        </div>
        {data?.period && (
          <div className="px-3 py-1.5 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white/60 text-gray-600 flex items-center gap-2">
            <Calendar className="w-4 h-4" />
            {data.period}
          </div>
        )}
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Drivers" value={stats.driver_count || allDrivers.length} icon={<Users className="w-4 h-4" />} index={0} />
        <StatCard label="Total Pay" value={formatCurrency(stats.total_pay || totals.net_pay)} icon={<DollarSign className="w-4 h-4" />} color="success" index={1} />
        <StatCard label="Withheld" value={formatCurrency(stats.withheld_amount || 0)} color="warning" index={2} />
        <StatCard label="Period" value={data?.period || '—'} index={3} />
      </div>

      {/* Drivers table */}
      {allDrivers.length === 0 ? (
        <EmptyState title="No payroll data" subtitle="Run payroll to generate results" action={{ label: 'Run Payroll', onClick: runPayroll }} />
      ) : (
        <div className="rounded-2xl overflow-hidden dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b dark:border-white/8 border-gray-100">
                  {['#', 'Name', 'Pay Code', 'Days', 'Net Pay', 'Carried Over', 'Pay This Period', 'Status', 'Override'].map(h => (
                    <th key={h} className="px-4 py-3 text-left font-medium dark:text-white/50 text-gray-400 whitespace-nowrap text-xs">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {allDrivers.map((driver, i) => (
                  <motion.tr
                    key={driver.id || i}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.02 }}
                    className="border-b last:border-0 dark:border-white/5 border-gray-50 dark:hover:bg-white/3 hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-3 dark:text-white/40 text-gray-400 text-xs">{i + 1}</td>
                    <td className="px-4 py-3 font-medium dark:text-white text-gray-800">{driver.name || '—'}</td>
                    <td className="px-4 py-3 dark:text-white/60 text-gray-600 font-mono text-xs">{driver.pay_code || '—'}</td>
                    <td className="px-4 py-3 dark:text-white/60 text-gray-600">{driver.days || 0}</td>
                    <td className="px-4 py-3 dark:text-white/80 text-gray-700">{formatCurrency(driver.net_pay)}</td>
                    <td className="px-4 py-3 text-amber-500">{driver.carried_over ? formatCurrency(driver.carried_over) : '—'}</td>
                    <td className="px-4 py-3 text-emerald-500 font-semibold">{formatCurrency(driver.pay_this_period)}</td>
                    <td className="px-4 py-3">
                      {driver.status ? (
                        <Badge variant={driver.status.toLowerCase().includes('paid') ? 'success' : driver.status.toLowerCase().includes('with') ? 'warning' : 'default'}>
                          {driver.status}
                        </Badge>
                      ) : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <input type="checkbox" defaultChecked={driver.override} className="rounded accent-[#667eea]" />
                    </td>
                  </motion.tr>
                ))}
                {/* Totals row */}
                <tr className="border-t-2 dark:border-white/20 border-gray-300 dark:bg-white/3 bg-gray-50 font-semibold">
                  <td colSpan={3} className="px-4 py-3 dark:text-white/60 text-gray-600 text-sm">Totals</td>
                  <td className="px-4 py-3 dark:text-white text-gray-800">{totals.days}</td>
                  <td className="px-4 py-3 dark:text-white text-gray-800">{formatCurrency(totals.net_pay)}</td>
                  <td className="px-4 py-3 text-amber-500">{formatCurrency(totals.carried)}</td>
                  <td className="px-4 py-3 text-emerald-500">{formatCurrency(totals.period)}</td>
                  <td colSpan={2} />
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Withheld section */}
      {withheld.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-amber-400 uppercase tracking-wide mb-3">Withheld ({withheld.length})</h2>
          <div className="rounded-2xl overflow-hidden border-2 border-amber-500/30 bg-amber-500/5">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-amber-500/20">
                  {['Name', 'Pay Code', 'Days', 'Amount Withheld', 'Reason'].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-medium text-amber-400/60">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {withheld.map((d, i) => (
                  <tr key={d.id || i} className="border-b last:border-0 border-amber-500/10">
                    <td className="px-4 py-2.5 dark:text-white/80 text-gray-700">{d.name}</td>
                    <td className="px-4 py-2.5 font-mono text-xs dark:text-white/50 text-gray-500">{d.pay_code}</td>
                    <td className="px-4 py-2.5 dark:text-white/60 text-gray-600">{d.days}</td>
                    <td className="px-4 py-2.5 text-amber-400">{formatCurrency(d.net_pay)}</td>
                    <td className="px-4 py-2.5 text-xs dark:text-white/40 text-gray-400">{d.status || 'Withheld'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
