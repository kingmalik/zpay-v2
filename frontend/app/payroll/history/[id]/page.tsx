'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, Download, FileSpreadsheet, Upload, ClipboardEdit, Clock, ChevronDown } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface CorrectionEntry {
  id: number
  person_id: number | null
  field: string
  old_value: string | null
  new_value: string | null
  reason: string | null
  corrected_by: string
  corrected_at: string
}

interface BatchResponse {
  batch?: {
    id?: number
    batch_ref?: string
    company?: string
    source?: string
    period_start?: string
    period_end?: string
    uploaded_at?: string
    week_label?: string
  }
  drivers?: {
    id?: number
    name?: string
    rides?: number
    net_pay?: number
    cost?: number
    profit?: number
  }[]
  totals?: { rides?: number; net_pay?: number; cost?: number; profit?: number }
}

function formatPeriod(start?: string, end?: string) {
  if (!start && !end) return '—'
  const fmt = (d: string) => new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  if (start && end) return `${fmt(start)} – ${fmt(end)}`
  return fmt(start || end || '')
}

export default function BatchDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [data, setData] = useState<BatchResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [corrections, setCorrections] = useState<CorrectionEntry[]>([])
  const [showCorrectionForm, setShowCorrectionForm] = useState(false)
  const [corrForm, setCorrForm] = useState({ field: '', old_value: '', new_value: '', reason: '' })
  const [savingCorr, setSavingCorr] = useState(false)
  const [paychexJob, setPaychexJob] = useState<{
    jobId: string | null
    status: 'idle' | 'pending' | 'running' | 'done' | 'failed' | 'mfa_required'
    progress: number
    total: number
    currentDriver: string
    message: string
    error: string | null
  }>({ jobId: null, status: 'idle', progress: 0, total: 0, currentDriver: '', message: '', error: null })

  useEffect(() => {
    api.get<BatchResponse>(`/api/data/payroll-history/${id}`).then(setData).catch(console.error).finally(() => setLoading(false))
    api.get<CorrectionEntry[]>(`/api/data/payroll-history/${id}/corrections`).then(setCorrections).catch(() => {})
  }, [id])

  useEffect(() => {
    if (!paychexJob.jobId || ['done', 'failed'].includes(paychexJob.status)) return
    const interval = setInterval(async () => {
      const res = await fetch(`/api/data/paychex-bot/status/${paychexJob.jobId}`, { credentials: 'include' })
      if (res.ok) {
        const d = await res.json()
        setPaychexJob(prev => ({ ...prev, status: d.status, progress: d.progress, total: d.total, currentDriver: d.current_driver, message: d.message, error: d.error }))
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [paychexJob.jobId, paychexJob.status])

  const handleSendToPaychex = async () => {
    setPaychexJob(prev => ({ ...prev, status: 'pending', message: 'Starting...' }))
    try {
      const res = await fetch(`/api/data/paychex-bot/push/${batch?.id}`, { method: 'POST', credentials: 'include', headers: { 'Accept': 'application/json' } })
      if (!res.ok) throw new Error('Failed to start Paychex bot')
      const d = await res.json()
      setPaychexJob(prev => ({ ...prev, jobId: d.job_id, total: d.total, status: 'pending' }))
    } catch (e: any) {
      setPaychexJob(prev => ({ ...prev, status: 'failed', error: e.message }))
    }
  }

  if (loading) return <LoadingSpinner fullPage />
  if (!data?.batch) return <div className="text-center py-16 dark:text-white/40 text-gray-400">Batch not found</div>

  const batch = data.batch
  const drivers = data.drivers || []
  const totals = data.totals || {}
  const src = (batch.source || batch.company || '').toLowerCase()
  const isFa = src.includes('first') || src.includes('acumen')
  const companyLabel = isFa ? 'FirstAlt' : 'EverDriven'

  return (
    <div className="max-w-6xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Link href="/payroll/history" className="p-2 rounded-xl dark:hover:bg-white/8 hover:bg-gray-100 transition-all dark:text-white/50 text-gray-500">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold dark:text-white text-gray-900">
              {batch.week_label ? `${batch.week_label} — ${companyLabel}` : `Batch #${batch.id}`}
            </h1>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant={isFa ? 'fa' : 'ed'}>{companyLabel}</Badge>
              {batch.week_label && <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-400">{batch.week_label}</span>}
              <span className="text-xs dark:text-white/40 text-gray-400">{formatPeriod(batch.period_start, batch.period_end)}</span>
              {batch.batch_ref && <span className="text-xs font-mono dark:text-white/30 text-gray-400">Ref: {batch.batch_ref}</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              try {
                const res = await fetch(`/api/v1/summary/export/excel?batch_id=${batch.id}&company=${encodeURIComponent(companyLabel)}`, { credentials: 'include' })
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
                const res = await fetch(`/api/v1/summary/export/paycheck-csv?payroll_batch_id=${batch.id}`, { credentials: 'include' })
                if (!res.ok) throw new Error('Download failed')
                const blob = await res.blob()
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                const cd = res.headers.get('content-disposition')
                a.download = cd?.match(/filename="?([^"]+)"?/)?.[1] || 'paychex.csv'
                document.body.appendChild(a)
                a.click()
                document.body.removeChild(a)
                setTimeout(() => URL.revokeObjectURL(url), 5000)
              } catch (e) { console.error(e) }
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium dark:bg-white/8 bg-gray-100 dark:text-white/70 text-gray-600 hover:dark:bg-white/12 hover:bg-gray-200 transition-all cursor-pointer"
          >
            <FileSpreadsheet className="w-4 h-4" />
            Paychex CSV
          </button>
          {paychexJob.status === 'idle' && (
            <button
              onClick={handleSendToPaychex}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-gradient-to-r from-indigo-500 to-cyan-500 text-white hover:opacity-90 transition-all cursor-pointer"
            >
              <Upload className="w-4 h-4" />
              Send to Paychex
            </button>
          )}
        </div>
      </div>

      {/* Paychex bot progress */}
      <AnimatePresence>
        {paychexJob.status !== 'idle' && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="p-4 rounded-2xl bg-gradient-to-r from-indigo-500/10 to-cyan-500/10 border dark:border-white/10 border-gray-200"
          >
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-semibold dark:text-white text-gray-900">
                {paychexJob.status === 'done' ? 'Entries Complete' :
                 paychexJob.status === 'failed' ? 'Bot Failed' :
                 paychexJob.status === 'mfa_required' ? 'MFA Required' :
                 'Sending to Paychex...'}
              </span>
              {paychexJob.status === 'done' && (
                <button onClick={() => setPaychexJob(prev => ({ ...prev, status: 'idle', jobId: null }))}
                  className="text-xs dark:text-white/50 text-gray-400 hover:dark:text-white/70 cursor-pointer">
                  Dismiss
                </button>
              )}
            </div>
            {paychexJob.status !== 'done' && paychexJob.status !== 'failed' && (
              <>
                <div className="w-full bg-gray-200 dark:bg-white/10 rounded-full h-2 mb-2">
                  <div
                    className="bg-gradient-to-r from-indigo-500 to-cyan-500 h-2 rounded-full transition-all duration-500"
                    style={{ width: `${paychexJob.total > 0 ? (paychexJob.progress / paychexJob.total) * 100 : 0}%` }}
                  />
                </div>
                <p className="text-xs dark:text-white/50 text-gray-500">
                  {paychexJob.currentDriver ? `Entering: ${paychexJob.currentDriver}` : paychexJob.message}
                  {paychexJob.total > 0 && ` (${paychexJob.progress}/${paychexJob.total})`}
                </p>
              </>
            )}
            {paychexJob.status === 'done' && (
              <p className="text-sm dark:text-green-400 text-green-600">
                ✓ {paychexJob.message || 'All entries filled. Log into Paychex to review and submit.'}
              </p>
            )}
            {paychexJob.status === 'mfa_required' && (
              <p className="text-sm dark:text-yellow-400 text-yellow-600">
                ⚠ MFA code sent to your phone — enter it in Paychex to continue
              </p>
            )}
            {paychexJob.status === 'failed' && (
              <div>
                <p className="text-sm dark:text-red-400 text-red-600">{paychexJob.error || 'Something went wrong'}</p>
                <button onClick={() => setPaychexJob({ jobId: null, status: 'idle', progress: 0, total: 0, currentDriver: '', message: '', error: null })}
                  className="mt-2 text-xs dark:text-white/50 text-gray-400 cursor-pointer">
                  Try again
                </button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="rounded-xl p-4 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
          <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Drivers</p>
          <p className="text-xl font-bold dark:text-white text-gray-900">{drivers.length}</p>
        </div>
        <div className="rounded-xl p-4 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
          <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Total Rides</p>
          <p className="text-xl font-bold dark:text-white text-gray-900">{totals.rides || 0}</p>
        </div>
        <div className="rounded-xl p-4 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
          <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Partner Paid</p>
          <p className="text-xl font-bold text-blue-500">{formatCurrency(totals.net_pay)}</p>
        </div>
        <div className="rounded-xl p-4 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
          <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Driver Cost</p>
          <p className="text-xl font-bold dark:text-white/80 text-gray-700">{formatCurrency(totals.cost)}</p>
        </div>
        <div className="rounded-xl p-4 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
          <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Profit</p>
          <p className={`text-xl font-bold ${(totals.profit || 0) >= 0 ? 'text-emerald-500' : 'text-red-400'}`}>{formatCurrency(totals.profit)}</p>
        </div>
      </div>

      {/* Drivers table */}
      <div className="rounded-2xl overflow-hidden dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b dark:border-white/8 border-gray-100 bg-gray-50/50 dark:bg-white/3">
              {['#', 'Driver', 'Rides', 'Partner Paid', 'Driver Pay', 'Profit'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {drivers.map((d, i) => (
              <tr key={d.id || i} className="border-b last:border-0 dark:border-white/5 border-gray-50 dark:hover:bg-white/3 hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3 text-xs dark:text-white/40 text-gray-400">{i + 1}</td>
                <td className="px-4 py-3 font-medium">
                  {d.id ? (
                    <Link href={`/payroll/history/${id}/driver/${d.id}`} className="dark:text-white text-gray-800 hover:text-[#667eea] dark:hover:text-[#7c93f0] transition-colors">
                      {d.name || '—'}
                    </Link>
                  ) : (
                    <span className="dark:text-white text-gray-800">{d.name || '—'}</span>
                  )}
                </td>
                <td className="px-4 py-3 dark:text-white/60 text-gray-600">{d.rides || 0}</td>
                <td className="px-4 py-3 dark:text-white/80 text-gray-700">{formatCurrency(d.net_pay)}</td>
                <td className="px-4 py-3 text-emerald-500 font-semibold">{formatCurrency(d.cost)}</td>
                <td className="px-4 py-3">
                  <span className={`font-semibold ${(d.profit || 0) >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                    {formatCurrency(d.profit)}
                  </span>
                </td>
              </tr>
            ))}
            {/* Totals */}
            <tr className="border-t-2 dark:border-white/20 border-gray-300 dark:bg-white/3 bg-gray-50 font-semibold">
              <td colSpan={2} className="px-4 py-3 dark:text-white/60 text-gray-600 text-sm">Totals</td>
              <td className="px-4 py-3 dark:text-white text-gray-800">{totals.rides || 0}</td>
              <td className="px-4 py-3 dark:text-white text-gray-800">{formatCurrency(totals.net_pay)}</td>
              <td className="px-4 py-3 text-emerald-500">{formatCurrency(totals.cost)}</td>
              <td className="px-4 py-3 text-emerald-500">{formatCurrency(totals.profit)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {/* Correction Log */}
      <div className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.02] bg-white overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b dark:border-white/8 border-gray-100">
          <div className="flex items-center gap-2">
            <ClipboardEdit className="w-4 h-4 dark:text-white/40 text-gray-400" />
            <h3 className="text-sm font-semibold dark:text-white text-gray-900">Correction Log</h3>
            {corrections.length > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full dark:bg-white/8 bg-gray-100 dark:text-white/50 text-gray-500">
                {corrections.length}
              </span>
            )}
          </div>
          <button
            onClick={() => setShowCorrectionForm(v => !v)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-200 border dark:border-white/10 border-gray-200 transition-all cursor-pointer"
          >
            <ClipboardEdit className="w-3 h-3" />
            Log Correction
            <ChevronDown className={`w-3 h-3 transition-transform ${showCorrectionForm ? 'rotate-180' : ''}`} />
          </button>
        </div>

        <AnimatePresence>
          {showCorrectionForm && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="p-5 border-b dark:border-white/8 border-gray-100 space-y-3 dark:bg-white/[0.02] bg-gray-50">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs dark:text-white/40 text-gray-500 mb-1">Field corrected</label>
                    <input
                      value={corrForm.field}
                      onChange={e => setCorrForm(p => ({ ...p, field: e.target.value }))}
                      placeholder="e.g. net_pay, z_rate"
                      className="w-full px-3 py-2 text-sm rounded-xl dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 focus:outline-none focus:border-[#667eea]/60"
                    />
                  </div>
                  <div>
                    <label className="block text-xs dark:text-white/40 text-gray-500 mb-1">Reason</label>
                    <input
                      value={corrForm.reason}
                      onChange={e => setCorrForm(p => ({ ...p, reason: e.target.value }))}
                      placeholder="Why was this corrected?"
                      className="w-full px-3 py-2 text-sm rounded-xl dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 focus:outline-none focus:border-[#667eea]/60"
                    />
                  </div>
                  <div>
                    <label className="block text-xs dark:text-white/40 text-gray-500 mb-1">Old value</label>
                    <input
                      value={corrForm.old_value}
                      onChange={e => setCorrForm(p => ({ ...p, old_value: e.target.value }))}
                      placeholder="Before"
                      className="w-full px-3 py-2 text-sm rounded-xl dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 focus:outline-none focus:border-[#667eea]/60"
                    />
                  </div>
                  <div>
                    <label className="block text-xs dark:text-white/40 text-gray-500 mb-1">New value</label>
                    <input
                      value={corrForm.new_value}
                      onChange={e => setCorrForm(p => ({ ...p, new_value: e.target.value }))}
                      placeholder="After"
                      className="w-full px-3 py-2 text-sm rounded-xl dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 focus:outline-none focus:border-[#667eea]/60"
                    />
                  </div>
                </div>
                <button
                  disabled={!corrForm.field || savingCorr}
                  onClick={async () => {
                    setSavingCorr(true)
                    try {
                      await api.post(`/api/data/payroll-history/${id}/corrections`, corrForm)
                      const updated = await api.get<CorrectionEntry[]>(`/api/data/payroll-history/${id}/corrections`)
                      setCorrections(updated)
                      setCorrForm({ field: '', old_value: '', new_value: '', reason: '' })
                      setShowCorrectionForm(false)
                    } finally {
                      setSavingCorr(false)
                    }
                  }}
                  className="px-4 py-2 rounded-xl text-sm font-medium text-white disabled:opacity-50 cursor-pointer"
                  style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
                >
                  {savingCorr ? 'Saving...' : 'Save Correction'}
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {corrections.length === 0 ? (
          <p className="text-xs dark:text-white/25 text-gray-400 text-center py-6">No corrections logged for this batch.</p>
        ) : (
          <div className="divide-y dark:divide-white/5 divide-gray-50">
            {corrections.map(c => (
              <div key={c.id} className="flex items-start gap-3 px-5 py-3">
                <Clock className="w-3.5 h-3.5 dark:text-white/20 text-gray-300 flex-shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-medium dark:text-white/70 text-gray-700">{c.field}</span>
                    {c.old_value && c.new_value && (
                      <span className="text-xs dark:text-white/40 text-gray-500">
                        <span className="line-through text-red-400">{c.old_value}</span>
                        {' → '}
                        <span className="text-emerald-400">{c.new_value}</span>
                      </span>
                    )}
                    {c.reason && <span className="text-xs dark:text-white/30 text-gray-400">· {c.reason}</span>}
                  </div>
                  <p className="text-[10px] dark:text-white/20 text-gray-400 mt-0.5">
                    {c.corrected_by} · {new Date(c.corrected_at).toLocaleString()}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
