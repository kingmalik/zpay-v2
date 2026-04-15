'use client'

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Play, Download, CheckSquare, Users, DollarSign, Calendar, Lock, FileSpreadsheet, ArrowUpDown } from 'lucide-react'
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
  periods?: {label: string; batch_id: number}[]
  batch_id?: number
  week_label?: string
  drivers?: DriverPayroll[]
  withheld?: DriverPayroll[]
  stats?: { driver_count?: number; total_pay?: number; withheld_amount?: number }
}

export default function PayrollPage() {
  const [data, setData] = useState<PayrollSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [finalizing, setFinalizing] = useState(false)
  const [company, setCompany] = useState('all')
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null)
  const [editingWithheld, setEditingWithheld] = useState(false)
  const [editingPaid, setEditingPaid] = useState(false)
  const [toggling, setToggling] = useState<string | number | null>(null)

  async function toggleWithheld(personId: string | number, makeWithheld: boolean) {
    const batchId = data?.batch_id
    if (!batchId) return
    setToggling(personId)
    try {
      await fetch(`/api/v1/api/data/workflow/${batchId}/set-withheld/${personId}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ withheld: makeWithheld }),
      })
      const fresh = await api.get<PayrollSummary>(`/api/data/summary${buildParams(company, selectedBatchId)}`)
      setData(fresh)
    } catch (e) { console.error(e) }
    finally { setToggling(null) }
  }

  function buildParams(c: string, batchId: number | null) {
    const params = new URLSearchParams()
    if (c === 'fa') params.set('company', 'fa')
    if (c === 'ed') params.set('company', 'ed')
    if (batchId) params.set('batch_id', String(batchId))
    const qs = params.toString()
    return qs ? `?${qs}` : ''  }

  useEffect(() => {
    setLoading(true)
    api.get<PayrollSummary>(`/api/data/summary${buildParams(company, selectedBatchId)}`).then(setData).catch(console.error).finally(() => setLoading(false))
  }, [company, selectedBatchId])

  async function runPayroll() {
    if (!data?.batch_id) return
    setRunning(true)
    try {
      await api.post('/summary/run', { batch_id: data.batch_id, company: company === 'all' ? null : company })
      const d = await api.get<PayrollSummary>(`/api/data/summary${buildParams(company, selectedBatchId)}`)
      setData(d)
    } catch (e) { console.error(e) }
    finally { setRunning(false) }
  }

  async function finalizeBatch() {
    if (!data?.batch_id) return
    setFinalizing(true)
    try {
      await api.post(`/upload/finalize?batch_id=${data.batch_id}`)
      const d = await api.get<PayrollSummary>(`/api/data/summary${buildParams(company, selectedBatchId)}`)
      setData(d)
    } catch (e) { console.error(e) }
    finally { setFinalizing(false) }
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
      {/* Workflow banner */}
      <a
        href="/payroll/workflow"
        className="block rounded-xl p-3 bg-[#667eea]/10 border border-[#667eea]/30 hover:bg-[#667eea]/15 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Play className="w-4 h-4 text-[#667eea]" />
          <span className="text-sm font-medium text-[#667eea]">
            Use the guided Payroll Workflow for step-by-step processing
          </span>
        </div>
      </a>

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">Payroll Summary</h1>
          {data?.period ? (
            <p className="text-sm dark:text-white/50 text-gray-500 mt-0.5">
              <span className="dark:text-white/30 text-gray-400 text-xs font-semibold uppercase tracking-wider mr-2">Payroll Period</span>
              {data.week_label || data.period}
            </p>
          ) : (
            <p className="text-sm dark:text-white/40 text-gray-400 mt-0.5">No period selected</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              try {
                const excelParams = new URLSearchParams()
                if (data?.batch_id) excelParams.set('batch_id', String(data.batch_id))
                if (company === 'fa') excelParams.set('company', 'FirstAlt')
                if (company === 'ed') excelParams.set('company', 'EverDriven')
                const res = await fetch(`/api/v1/summary/export/excel?${excelParams}`, { credentials: 'include' })
                if (!res.ok) throw new Error('Download failed')
                const blob = await res.blob()
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                const cd = res.headers.get('content-disposition')
                a.download = cd?.match(/filename="?([^"]+)"?/)?.[1] || 'payroll.xlsx'
                document.body.appendChild(a)
                a.click()
                document.body.removeChild(a)
                setTimeout(() => URL.revokeObjectURL(url), 5000)
              } catch (e) { console.error(e) }
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium dark:bg-white/8 bg-gray-100 dark:text-white/70 text-gray-600 hover:dark:bg-white/12 hover:bg-gray-200 transition-all cursor-pointer"
          >
            <Download className="w-4 h-4" />
            Excel
          </button>
          <button
            onClick={async () => {
              try {
                const url = `/api/v1/summary/export/paycheck-csv${data?.batch_id ? `?payroll_batch_id=${data.batch_id}` : ''}`
                const res = await fetch(url, { credentials: 'include' })
                if (!res.ok) throw new Error('Download failed')
                const blob = await res.blob()
                const blobUrl = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = blobUrl
                const cd = res.headers.get('content-disposition')
                a.download = cd?.match(/filename="?([^"]+)"?/)?.[1] || 'paychex.csv'
                document.body.appendChild(a)
                a.click()
                document.body.removeChild(a)
                setTimeout(() => URL.revokeObjectURL(blobUrl), 5000)
              } catch (e) { console.error(e) }
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium dark:bg-white/8 bg-gray-100 dark:text-white/70 text-gray-600 hover:dark:bg-white/12 hover:bg-gray-200 transition-all cursor-pointer"
          >
            <FileSpreadsheet className="w-4 h-4" />
            Paychex CSV
          </button>
          <button
            onClick={finalizeBatch}
            disabled={finalizing || !data?.batch_id}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium dark:bg-white/8 bg-gray-100 dark:text-white/70 text-gray-600 hover:dark:bg-white/12 hover:bg-gray-200 transition-all cursor-pointer disabled:opacity-60"
          >
            <Lock className="w-4 h-4" />
            {finalizing ? 'Finalizing...' : 'Finalize'}
          </button>
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
            <button key={v} onClick={() => { setCompany(v); setSelectedBatchId(null) }}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all cursor-pointer ${company === v ? 'bg-[#667eea] text-white' : 'dark:text-white/50 text-gray-500'}`}>
              {l}
            </button>
          ))}
        </div>
        <div className="relative flex items-center gap-2 px-3 py-1.5 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white/60 text-gray-600">
          <Calendar className="w-4 h-4 flex-shrink-0" />
          <select
            value={selectedBatchId ?? ''}
            onChange={(e) => setSelectedBatchId(e.target.value ? Number(e.target.value) : null)}
            className="bg-transparent outline-none cursor-pointer appearance-none pr-5 dark:text-white/60 text-gray-600 text-sm"
          >
            <option value="" className="dark:bg-gray-900 bg-white">All / Latest</option>
            {(data?.periods || []).map((p) => (
              <option key={p.batch_id} value={p.batch_id} className="dark:bg-gray-900 bg-white">
                {p.label}
              </option>
            ))}
          </select>
          <svg className="w-3 h-3 absolute right-3 pointer-events-none dark:text-white/40 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
        </div>
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
        <div className="rounded-xl overflow-hidden dark:bg-white/[0.04] dark:border dark:border-white/[0.08] bg-white border border-gray-200">
          <div className="px-4 py-2.5 border-b dark:border-white/[0.08] border-gray-100 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider dark:text-white/40 text-gray-400">Paid Drivers ({allDrivers.length})</span>
            <button onClick={() => setEditingPaid(v => !v)} className={`text-xs px-2 py-1 rounded-lg transition-colors cursor-pointer ${editingPaid ? 'bg-amber-500/20 text-amber-400' : 'dark:text-white/40 text-gray-400 hover:dark:text-white/60 hover:text-gray-600'}`}>
              {editingPaid ? 'Done' : 'Edit'}
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b dark:border-white/[0.08] border-gray-100">
                  {['#', 'Name', 'Pay Code', 'Days', 'Net Pay', 'Carried Over', 'Pay This Period', 'Status', ...(editingPaid ? [''] : [])].map((h, i) => (
                    <th key={i} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider dark:text-white/40 text-gray-400 whitespace-nowrap">{h}</th>
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
                    className="border-b last:border-0 dark:border-white/[0.06] border-gray-100 dark:hover:bg-white/[0.04] hover:bg-gray-50 transition-colors"
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
                    {editingPaid && (
                      <td className="px-4 py-3">
                        <button
                          onClick={() => driver.id != null && toggleWithheld(driver.id, true)}
                          disabled={toggling === driver.id}
                          className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-amber-400 bg-amber-500/10 hover:bg-amber-500/20 transition-colors disabled:opacity-40 cursor-pointer"
                        >
                          {toggling === driver.id ? '…' : <><ArrowUpDown className="w-3 h-3" />Withhold</>}
                        </button>
                      </td>
                    )}
                  </motion.tr>
                ))}
                {/* Totals row */}
                <tr className="border-t-2 dark:border-white/20 border-gray-300 dark:bg-white/3 bg-gray-50 font-semibold">
                  <td colSpan={3} className="px-4 py-3 dark:text-white/60 text-gray-600 text-sm">Totals</td>
                  <td className="px-4 py-3 dark:text-white text-gray-800">{totals.days}</td>
                  <td className="px-4 py-3 dark:text-white text-gray-800">{formatCurrency(totals.net_pay)}</td>
                  <td className="px-4 py-3 text-amber-500">{formatCurrency(totals.carried)}</td>
                  <td className="px-4 py-3 text-emerald-500">{formatCurrency(totals.period)}</td>
                  <td colSpan={editingPaid ? 2 : 1} />
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Withheld section */}
      {withheld.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-amber-400">Withheld ({withheld.length})</h2>
            <button onClick={() => setEditingWithheld(v => !v)} className={`text-xs px-2 py-1 rounded-lg transition-colors cursor-pointer ${editingWithheld ? 'bg-amber-500/20 text-amber-400' : 'text-amber-400/50 hover:text-amber-400'}`}>
              {editingWithheld ? 'Done' : 'Edit'}
            </button>
          </div>
          <div className="rounded-2xl overflow-hidden border-2 border-amber-500/30 bg-amber-500/5">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-amber-500/20">
                  {['Name', 'Pay Code', 'Days', 'Amount Withheld', 'Reason', ...(editingWithheld ? [''] : [])].map((h, i) => (
                    <th key={i} className="px-4 py-2.5 text-left text-xs font-medium text-amber-400/60">{h}</th>
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
                    {editingWithheld && (
                      <td className="px-4 py-2.5">
                        <button
                          onClick={() => d.id != null && toggleWithheld(d.id, false)}
                          disabled={toggling === d.id}
                          className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-emerald-400 bg-emerald-500/10 hover:bg-emerald-500/20 transition-colors disabled:opacity-40 cursor-pointer"
                        >
                          {toggling === d.id ? '…' : <><ArrowUpDown className="w-3 h-3" />Pay</>}
                        </button>
                      </td>
                    )}
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
