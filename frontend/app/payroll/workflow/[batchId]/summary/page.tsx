'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, FileSpreadsheet, FileText, ArrowUpDown } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface BatchOption {
  id: string | number
  week_label: string
  company: string
  period: string
  status: string
}

interface SummaryDriver {
  person_id: number
  name: string
  pay_code?: string
  rides: number
  miles: number
  partner_paid: number
  driver_pay: number
  deduction: number
  withheld_amount: number
  paid_this_period: number
  is_withheld: boolean
}

interface BatchSummary {
  batch: {
    id: number
    company: string
    week_label: string
    period_start?: string
    period_end?: string
    batch_ref?: string
    source: string
  }
  totals: {
    rides: number
    miles: number
    partner_paid: number
    driver_cost: number
    withheld: number
    payout: number
    margin: number
  }
  drivers: SummaryDriver[]
}

function formatPeriod(start?: string, end?: string) {
  if (!start && !end) return '—'
  const fmt = (d: string) => new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  if (start && end) return `${fmt(start)} – ${fmt(end)}`
  return fmt(start || end || '')
}

export default function BatchSummaryPage() {
  const { batchId } = useParams<{ batchId: string }>()
  const router = useRouter()
  const [data, setData] = useState<BatchSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [downloading, setDownloading] = useState<'pdf' | 'excel' | null>(null)
  const [batches, setBatches] = useState<BatchOption[]>([])

  useEffect(() => {
    api.get<BatchOption[]>('/api/data/payroll-history').then(setBatches).catch(console.error)
  }, [])

  useEffect(() => {
    setLoading(true)
    setData(null)
    api.get<BatchSummary>(`/api/data/workflow/${batchId}/batch-summary`)
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [batchId])

  const [toggling, setToggling] = useState<number | null>(null)

  async function toggleWithheld(personId: number, makeWithheld: boolean) {
    setToggling(personId)
    try {
      await fetch(`/api/v1/api/data/workflow/${batchId}/set-withheld/${personId}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ withheld: makeWithheld }),
      })
      // Refresh the summary data
      const fresh = await api.get<BatchSummary>(`/api/data/workflow/${batchId}/batch-summary`)
      setData(fresh)
    } catch (e) {
      console.error(e)
    } finally {
      setToggling(null)
    }
  }

  async function download(type: 'pdf' | 'excel') {
    setDownloading(type)
    try {
      const ext = type === 'pdf' ? 'pdf' : 'xlsx'
      const endpoint = type === 'pdf' ? 'export-pdf' : 'export-excel'
      const res = await fetch(`/api/v1/api/data/workflow/${batchId}/${endpoint}`, { credentials: 'include' })
      if (!res.ok) throw new Error('Download failed')

      // Try to get filename from Content-Disposition header
      let filename = ''
      const disposition = res.headers.get('Content-Disposition')
      if (disposition) {
        const filenameMatch = disposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i)
        if (filenameMatch) {
          filename = decodeURIComponent(filenameMatch[1].trim())
        }
      }
      // Fallback: build a descriptive name from batch data
      if (!filename) {
        const currentBatch = batches.find(b => String(b.id) === batchId)
        if (currentBatch) {
          const company = (currentBatch.company || 'batch').toLowerCase().replace(/\s+/g, '_')
          const period = (currentBatch.period || '').replace(/\s+/g, '_').replace(/[/]/g, '-')
          filename = `${company}_${period}.${ext}`
        } else {
          filename = `payroll_batch_${batchId}.${ext}`
        }
      }

      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      setTimeout(() => URL.revokeObjectURL(url), 5000)
    } catch (e) {
      console.error(e)
    } finally {
      setDownloading(null)
    }
  }

  const { batch, totals, drivers } = data || { batch: null, totals: null, drivers: [] }
  const isFa = (batch?.source || '').includes('acumen')
  const paid = drivers.filter(d => !d.is_withheld)
  const withheld = drivers.filter(d => d.is_withheld)

  return (
    <div className="max-w-5xl mx-auto space-y-6 py-6">

      {/* Header */}
      <div className="flex items-start gap-3 flex-wrap">
        <button
          onClick={() => router.push('/payroll/history')}
          className="p-2 rounded-xl dark:hover:bg-white/8 hover:bg-gray-100 transition-all dark:text-white/50 text-gray-500 mt-0.5"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>

        {/* Week selector */}
        <div className="flex-1 min-w-[200px]">
          <select
            value={batchId}
            onChange={e => router.push(`/payroll/workflow/${e.target.value}/summary`)}
            className="w-full px-3 py-2 rounded-xl text-sm font-medium dark:bg-white/8 bg-gray-100 dark:text-white text-gray-900 border dark:border-white/10 border-gray-200 focus:outline-none focus:border-[#667eea] cursor-pointer"
          >
            {batches.map(b => (
              <option key={String(b.id)} value={String(b.id)}>
                {b.week_label} — {b.company} ({b.period})
              </option>
            ))}
          </select>
        </div>

        {/* Download buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => download('excel')}
            disabled={downloading !== null}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-all disabled:opacity-50"
          >
            <FileSpreadsheet className="w-4 h-4" />
            {downloading === 'excel' ? 'Downloading...' : 'Excel'}
          </button>
          <button
            onClick={() => download('pdf')}
            disabled={downloading !== null}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-all disabled:opacity-50"
          >
            <FileText className="w-4 h-4" />
            {downloading === 'pdf' ? 'Downloading...' : 'PDF'}
          </button>
        </div>
      </div>

      {loading && <LoadingSpinner />}

      {/* Totals cards */}
      {totals && <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Rides', value: String(totals.rides), color: 'dark:text-white text-gray-900' },
          { label: 'Partner Paid', value: formatCurrency(totals.partner_paid), color: 'text-blue-500' },
          { label: 'Driver Payout', value: formatCurrency(totals.payout), color: 'text-emerald-500' },
          { label: 'Margin', value: formatCurrency(totals.margin), color: totals.margin >= 0 ? 'text-emerald-500' : 'text-red-500' },
        ].map(c => (
          <div key={c.label} className="rounded-2xl p-4 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
            <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase tracking-wide mb-1">{c.label}</p>
            <p className={`text-xl font-bold ${c.color}`}>{c.value}</p>
          </div>
        ))}
      </div>}
      {totals && totals.withheld > 0 && (
        <div className="rounded-2xl p-4 bg-amber-500/10 border border-amber-500/20 flex items-center justify-between">
          <span className="text-sm text-amber-400 font-medium">{withheld.length} driver{withheld.length !== 1 ? 's' : ''} withheld this period</span>
          <span className="text-sm font-bold text-amber-400">{formatCurrency(totals.withheld)} carried forward</span>
        </div>
      )}

      {/* Paid drivers table */}
      <div className="rounded-2xl overflow-hidden bg-white dark:bg-white/3 border border-gray-200 dark:border-white/8">
        <div className="px-5 py-3 border-b border-gray-100 dark:border-white/8">
          <h3 className="text-sm font-semibold dark:text-white text-gray-900">Paid Drivers ({paid.length})</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b dark:border-white/8 border-gray-100 bg-gray-50/50 dark:bg-white/3">
                {['Driver', 'Pay Code', 'Rides', 'Miles', 'Partner Pays', 'Driver Pay', 'Carried In', 'Paid', ''].map(h => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {paid.map((d, i) => (
                <tr key={d.person_id} className="border-b last:border-0 dark:border-white/5 border-gray-50 dark:hover:bg-white/3 hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 dark:text-white text-gray-900 font-medium">{d.name}</td>
                  <td className="px-4 py-3 font-mono text-xs dark:text-white/40 text-gray-400">{d.pay_code || '—'}</td>
                  <td className="px-4 py-3 dark:text-white/70 text-gray-600">{d.rides}</td>
                  <td className="px-4 py-3 dark:text-white/60 text-gray-500 font-mono text-xs">{d.miles > 0 ? `${d.miles}mi` : '—'}</td>
                  <td className="px-4 py-3 dark:text-white/80 text-gray-700">{formatCurrency(d.partner_paid)}</td>
                  <td className="px-4 py-3 text-emerald-500 font-semibold">{formatCurrency(d.driver_pay)}</td>
                  <td className="px-4 py-3 text-xs dark:text-white/40 text-gray-400">{d.withheld_amount > 0 ? formatCurrency(d.withheld_amount) : '—'}</td>
                  <td className="px-4 py-3 text-emerald-500 font-bold">{formatCurrency(d.paid_this_period)}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => toggleWithheld(d.person_id, true)}
                      disabled={toggling === d.person_id}
                      title="Move to withheld"
                      className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-amber-400 bg-amber-500/10 hover:bg-amber-500/20 transition-colors disabled:opacity-40 cursor-pointer"
                    >
                      {toggling === d.person_id ? '…' : <><ArrowUpDown className="w-3 h-3" />Withhold</>}
                    </button>
                  </td>
                </tr>
              ))}
              {/* Totals row */}
              <tr className="border-t-2 dark:border-white/20 border-gray-200 dark:bg-white/3 bg-gray-50 font-semibold">
                <td colSpan={2} className="px-4 py-3 text-xs dark:text-white/50 text-gray-500">Totals</td>
                <td className="px-4 py-3 text-xs dark:text-white text-gray-800">{paid.reduce((s, d) => s + d.rides, 0)}</td>
                <td className="px-4 py-3 text-xs font-mono dark:text-white text-gray-800">{paid.reduce((s, d) => s + d.miles, 0).toFixed(1)}mi</td>
                <td className="px-4 py-3 text-xs dark:text-white text-gray-800">{formatCurrency(paid.reduce((s, d) => s + d.partner_paid, 0))}</td>
                <td className="px-4 py-3 text-xs text-emerald-500">{formatCurrency(paid.reduce((s, d) => s + d.driver_pay, 0))}</td>
                <td className="px-4 py-3 text-xs dark:text-white/40 text-gray-400">{formatCurrency(paid.reduce((s, d) => s + d.withheld_amount, 0))}</td>
                <td className="px-4 py-3 text-xs text-emerald-500">{formatCurrency(paid.reduce((s, d) => s + d.paid_this_period, 0))}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Withheld drivers */}
      {withheld.length > 0 && (
        <div className="rounded-2xl overflow-hidden bg-white dark:bg-white/3 border border-amber-500/20">
          <div className="px-5 py-3 border-b border-amber-500/20 bg-amber-500/5">
            <h3 className="text-sm font-semibold text-amber-400">Withheld — Carrying Forward ({withheld.length})</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b dark:border-white/8 border-gray-100">
                  {['Driver', 'Pay Code', 'Rides', 'Driver Pay', 'Balance Carrying Forward', ''].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {withheld.map(d => (
                  <tr key={d.person_id} className="border-b last:border-0 dark:border-white/5 border-gray-50">
                    <td className="px-4 py-3 dark:text-white text-gray-900 font-medium">{d.name}</td>
                    <td className="px-4 py-3 font-mono text-xs dark:text-white/40 text-gray-400">{d.pay_code || '—'}</td>
                    <td className="px-4 py-3 dark:text-white/70 text-gray-600">{d.rides}</td>
                    <td className="px-4 py-3 dark:text-white/70 text-gray-600">{formatCurrency(d.driver_pay)}</td>
                    <td className="px-4 py-3 text-amber-400 font-semibold">{formatCurrency(d.withheld_amount)}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => toggleWithheld(d.person_id, false)}
                        disabled={toggling === d.person_id}
                        title="Force pay this driver"
                        className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-emerald-400 bg-emerald-500/10 hover:bg-emerald-500/20 transition-colors disabled:opacity-40 cursor-pointer"
                      >
                        {toggling === d.person_id ? '…' : <><ArrowUpDown className="w-3 h-3" />Pay</>}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Nav buttons */}
      <div className="flex items-center justify-center gap-3 pb-4">
        <button
          onClick={() => router.push('/payroll/workflow')}
          className="px-4 py-2 rounded-xl text-sm dark:text-white/60 text-gray-600 border dark:border-white/20 border-gray-200 hover:dark:border-white/40 hover:border-gray-400 transition-colors"
        >
          New Payroll
        </button>
        <button
          onClick={() => router.push('/payroll/history')}
          className="px-4 py-2 rounded-xl text-sm font-medium bg-[#667eea] text-white hover:bg-[#5a6fd6] transition-colors"
        >
          View History
        </button>
      </div>
    </div>
  )
}
