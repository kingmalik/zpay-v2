'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  CheckCircle2, Send, FileSpreadsheet, AlertTriangle,
  ChevronRight, Users, DollarSign, Clock, ArrowUpDown, X, ChevronDown,
} from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import MomPaystubModal, { type PaystubDriverRef } from './MomPaystubModal'

// ── Types ───────────────────────────────────────────────────────────────────

interface BatchStatus {
  batch_id: number
  status: string
  week_label: string
  company: string
  driver_count: number
  stubs_sent: number
  stubs_failed: number
  paychex_exported_at: string | null
}

interface PayrollDriver {
  id: number
  name: string
  pay_code: string
  days: number
  net_pay: number
  carried_over: number
  pay_this_period: number
  status: string
}

interface PayrollPreview {
  drivers: PayrollDriver[]
  withheld: PayrollDriver[]
  totals: { days: number; net_pay: number; pay_this_period: number }
  stats: { driver_count: number; total_pay: number; withheld_amount: number; withheld_count: number }
}

type Step = 'review' | 'fork' | 'done'
type PathTaken = 'stubs_first' | 'paychex_first' | null

interface Props {
  batchId: number
  status: BatchStatus
  onRefresh: () => Promise<void>
}

// ── Main component ──────────────────────────────────────────────────────────

export default function MomPayrollWorkflow({ batchId, status, onRefresh }: Props) {
  const [step, setStep] = useState<Step>(() => {
    // Determine starting step from current batch status
    if (status.status === 'payroll_review') return 'review'
    if (status.status === 'stubs_sending' || status.status === 'export_ready') return 'fork'
    if (status.status === 'complete') return 'done'
    return 'review'
  })
  const [preview, setPreview] = useState<PayrollPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(true)
  const [approving, setApproving] = useState(false)

  // Track what mom has completed in this session (persisted via status fields)
  const stubsDone = status.stubs_sent > 0
  const paychexDone = !!status.paychex_exported_at
  const bothDone = stubsDone && paychexDone

  const [pathTaken, setPathTaken] = useState<PathTaken>(null)

  // Paystub drill-down state
  const [paystubDriver, setPaystubDriver] = useState<PaystubDriverRef | null>(null)
  const [withheldOpen, setWithheldOpen] = useState(false)

  // Send stubs state
  const [stubsConfirm, setStubsConfirm] = useState(false)
  const [stubsSending, setStubsSending] = useState(false)
  const [stubsResult, setStubsResult] = useState<{ sent: number; failed: number } | null>(
    stubsDone ? { sent: status.stubs_sent, failed: status.stubs_failed } : null
  )

  // Paychex state
  const [paychexDownloading, setPaychexDownloading] = useState(false)
  const [paychexDoneLocal, setPaychexDoneLocal] = useState(paychexDone)
  const [reconfirm, setReconfirm] = useState<'stubs' | 'paychex' | null>(null)

  // Load driver preview
  useEffect(() => {
    api.get<PayrollPreview>(`/api/data/workflow/${batchId}/payroll-preview`)
      .then(setPreview)
      .catch(() => {})
      .finally(() => setPreviewLoading(false))
  }, [batchId])

  // Sync step when status changes
  useEffect(() => {
    if (status.status === 'complete') setStep('done')
    else if (status.status === 'stubs_sending' || status.status === 'export_ready') setStep('fork')
  }, [status.status])

  async function handleApprove() {
    setApproving(true)
    try {
      await api.post(`/api/data/workflow/${batchId}/advance`)
      await onRefresh()
      setStep('fork')
    } catch (e) {
      const toast = (await import('sonner')).toast
      toast.error('Could not approve', { description: e instanceof Error ? e.message : undefined })
    } finally {
      setApproving(false)
    }
  }

  async function sendStubs() {
    setStubsSending(true)
    setStubsConfirm(false)
    try {
      const res = await api.post<{ ok: boolean; sent: number; failed: number }>(
        `/api/data/workflow/${batchId}/send-stubs`
      )
      setStubsResult({ sent: res.sent, failed: res.failed })
      const toast = (await import('sonner')).toast
      if (res.failed > 0) {
        toast.warning(`Stubs sent: ${res.sent} delivered, ${res.failed} failed`)
      } else {
        toast.success(`Pay stubs sent to ${res.sent} driver${res.sent !== 1 ? 's' : ''}`)
      }
      await onRefresh()
      if (pathTaken === 'paychex_first') {
        // Both done — try to advance to complete
        try { await api.post(`/api/data/workflow/${batchId}/advance`) } catch {}
        await onRefresh()
        setStep('done')
      }
    } catch (e) {
      const toast = (await import('sonner')).toast
      toast.error('Failed to send stubs', { description: e instanceof Error ? e.message : undefined })
    } finally {
      setStubsSending(false)
      setReconfirm(null)
    }
  }

  async function downloadPaychex() {
    setPaychexDownloading(true)
    try {
      const url = `/api/v1/summary/export/paycheck-csv?payroll_batch_id=${batchId}`
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
      setPaychexDoneLocal(true)
      const toast = (await import('sonner')).toast
      toast.success('Paychex CSV downloaded')
      await onRefresh()
      if (pathTaken === 'stubs_first') {
        // Both done — try to advance to complete
        try { await api.post(`/api/data/workflow/${batchId}/advance`) } catch {}
        await onRefresh()
        setStep('done')
      }
    } catch (e) {
      const toast = (await import('sonner')).toast
      toast.error('CSV download failed', { description: e instanceof Error ? e.message : undefined })
    } finally {
      setPaychexDownloading(false)
      setReconfirm(null)
    }
  }

  const effectiveStubsDone = stubsResult !== null || stubsDone
  const effectivePaychexDone = paychexDoneLocal || paychexDone

  return (
    <div className="max-w-2xl mx-auto space-y-6 py-4">

      {/* Progress dots */}
      <div className="flex items-center justify-center gap-3 mb-2">
        {(['review', 'fork', 'done'] as Step[]).map((s, i) => (
          <div key={s} className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all duration-300 ${
              step === s
                ? 'bg-[#667eea] text-white shadow-lg shadow-[#667eea]/30'
                : (s === 'done' || (s === 'fork' && step === 'done') || (s === 'review' && step !== 'review'))
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                  : 'bg-white/8 text-white/30 border border-white/10'
            }`}>
              {(s === 'review' && step !== 'review') || (s === 'fork' && step === 'done')
                ? <CheckCircle2 className="w-4 h-4" />
                : i + 1}
            </div>
            {i < 2 && (
              <div className={`w-12 h-px transition-all duration-300 ${
                (i === 0 && step !== 'review') || (i === 1 && step === 'done')
                  ? 'bg-emerald-500/40' : 'bg-white/10'
              }`} />
            )}
          </div>
        ))}
      </div>

      {/* Step labels */}
      <div className="flex justify-around text-xs text-white/40 -mt-2">
        <span className={step === 'review' ? 'text-[#667eea] font-medium' : effectiveStubsDone ? 'text-emerald-400' : ''}>Review Amounts</span>
        <span className={step === 'fork' ? 'text-[#667eea] font-medium' : step === 'done' ? 'text-emerald-400' : ''}>Send & Export</span>
        <span className={step === 'done' ? 'text-emerald-400 font-medium' : ''}>Done</span>
      </div>

      <AnimatePresence mode="wait">

        {/* ── STEP 1: Review amounts ─────────────────────────────────────── */}
        {step === 'review' && (
          <motion.div
            key="review"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -16 }}
            transition={{ duration: 0.22 }}
          >
            <div className="rounded-2xl dark:bg-white/[0.04] border dark:border-white/[0.08] bg-white border-gray-200 overflow-hidden">
              <div className="px-5 py-4 border-b dark:border-white/[0.08] border-gray-100">
                <h2 className="text-lg font-semibold dark:text-white text-gray-900">Step 1 — Review amounts</h2>
                <p className="text-sm dark:text-white/50 text-gray-500 mt-0.5">
                  Look over each driver. When you&apos;re satisfied with the numbers, tap Approve.
                </p>
              </div>

              {previewLoading ? (
                <div className="px-5 py-8 text-center dark:text-white/30 text-gray-400 text-sm">Loading...</div>
              ) : preview ? (
                <div>
                  {/* Stats row */}
                  <div className="grid grid-cols-3 divide-x dark:divide-white/[0.08] divide-gray-100">
                    <div className="px-5 py-3">
                      <p className="text-xs dark:text-white/40 text-gray-400 flex items-center gap-1.5"><Users className="w-3.5 h-3.5" />Drivers</p>
                      <p className="text-xl font-bold dark:text-white text-gray-900 mt-0.5">{preview.stats.driver_count}</p>
                    </div>
                    <div className="px-5 py-3">
                      <p className="text-xs dark:text-white/40 text-gray-400 flex items-center gap-1.5"><DollarSign className="w-3.5 h-3.5" />Total Pay</p>
                      <p className="text-xl font-bold text-emerald-400 mt-0.5">{formatCurrency(preview.stats.total_pay)}</p>
                    </div>
                    <div className="px-5 py-3">
                      <p className="text-xs text-amber-400/70 flex items-center gap-1.5"><Clock className="w-3.5 h-3.5" />Carried Over</p>
                      <p className="text-xl font-bold text-amber-400 mt-0.5">{preview.stats.withheld_count}</p>
                    </div>
                  </div>

                  {/* Driver table */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-t dark:border-white/[0.08] border-gray-100">
                          {['Driver', 'Days', 'Earned', 'Carried', 'Pays Out'].map(h => (
                            <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider dark:text-white/40 text-gray-400">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.drivers.map((d, i) => (
                          <motion.tr
                            key={d.id}
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            transition={{ delay: i * 0.015 }}
                            onClick={() => setPaystubDriver({ ...d, status: 'paid' })}
                            className="border-t dark:border-white/[0.06] border-gray-50 dark:hover:bg-white/[0.03] hover:bg-gray-50 transition-colors cursor-pointer"
                          >
                            <td className="px-4 py-2.5 font-medium dark:text-white text-gray-800">{d.name}</td>
                            <td className="px-4 py-2.5 dark:text-white/60 text-gray-500">{d.days}</td>
                            <td className="px-4 py-2.5 dark:text-white/70 text-gray-700">{formatCurrency(d.net_pay)}</td>
                            <td className="px-4 py-2.5 text-amber-500">{d.carried_over ? formatCurrency(d.carried_over) : '—'}</td>
                            <td className="px-4 py-2.5 text-emerald-500 font-semibold">{formatCurrency(d.pay_this_period)}</td>
                          </motion.tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Withheld collapsible section */}
                  {preview.withheld.length > 0 && (
                    <div className="mx-4 mb-4">
                      <button
                        onClick={() => setWithheldOpen(o => !o)}
                        className="w-full rounded-xl bg-amber-500/8 border border-amber-500/20 px-4 py-3 flex items-center justify-between text-left transition-colors hover:bg-amber-500/12"
                      >
                        <div className="flex items-center gap-2">
                          <ArrowUpDown className="w-4 h-4 text-amber-400" />
                          <span className="text-sm text-amber-400 font-medium">
                            {preview.withheld.length} driver{preview.withheld.length !== 1 ? 's' : ''} carried to next week
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-amber-400/60">
                            {formatCurrency(preview.withheld.reduce((s, w) => s + (w.pay_this_period || w.net_pay + w.carried_over), 0))} total
                          </span>
                          <motion.div
                            animate={{ rotate: withheldOpen ? 180 : 0 }}
                            transition={{ duration: 0.18 }}
                          >
                            <ChevronDown className="w-4 h-4 text-amber-400/70" />
                          </motion.div>
                        </div>
                      </button>

                      <AnimatePresence>
                        {withheldOpen && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.2 }}
                            className="overflow-hidden"
                          >
                            <div className="mt-1 rounded-xl border dark:border-white/[0.07] border-amber-200/40 overflow-hidden">
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="border-b dark:border-white/[0.07] border-gray-100">
                                    {['Driver', 'Days', 'This week', 'Prior', 'Balance'].map(h => (
                                      <th key={h} className="px-3 py-2 text-left font-semibold uppercase tracking-wider dark:text-white/35 text-gray-400">{h}</th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {preview.withheld.map((w, i) => (
                                    <motion.tr
                                      key={w.id}
                                      initial={{ opacity: 0 }}
                                      animate={{ opacity: 1 }}
                                      transition={{ delay: i * 0.02 }}
                                      onClick={() => setPaystubDriver({ ...w, status: 'withheld' })}
                                      className="border-t dark:border-white/[0.05] border-gray-50 dark:hover:bg-white/[0.03] hover:bg-amber-50/30 transition-colors cursor-pointer"
                                    >
                                      <td className="px-3 py-2 font-medium dark:text-white/80 text-gray-800">{w.name}</td>
                                      <td className="px-3 py-2 dark:text-white/50 text-gray-500">{w.days}</td>
                                      <td className="px-3 py-2 dark:text-white/60 text-gray-600">{formatCurrency(w.net_pay)}</td>
                                      <td className="px-3 py-2 text-amber-500/80">{w.carried_over ? formatCurrency(w.carried_over) : '—'}</td>
                                      <td className="px-3 py-2 text-amber-400 font-semibold">
                                        {formatCurrency(w.pay_this_period || (w.net_pay + w.carried_over))}
                                      </td>
                                    </motion.tr>
                                  ))}
                                </tbody>
                              </table>
                              <div className="px-3 py-2 border-t dark:border-white/[0.07] border-gray-100 dark:bg-white/[0.01]">
                                <p className="text-[10px] dark:text-amber-400/50 text-amber-600/60">
                                  Click a row to see ride-by-ride breakdown. Tap row in main table to do the same for paying drivers.
                                </p>
                              </div>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  )}
                </div>
              ) : (
                <div className="px-5 py-8 text-center dark:text-white/30 text-gray-400 text-sm">Could not load driver data.</div>
              )}

              <div className="px-5 py-4 border-t dark:border-white/[0.08] border-gray-100 flex justify-end">
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={handleApprove}
                  disabled={approving || previewLoading}
                  className="flex items-center gap-2.5 px-7 py-3 rounded-xl text-white font-semibold text-sm disabled:opacity-60 transition-opacity"
                  style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
                >
                  {approving ? 'Approving...' : 'Amounts look good — Approve'}
                  {!approving && <ChevronRight className="w-4 h-4" />}
                </motion.button>
              </div>
            </div>
          </motion.div>
        )}

        {/* ── STEP 2: Fork ──────────────────────────────────────────────── */}
        {step === 'fork' && (
          <motion.div
            key="fork"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -16 }}
            transition={{ duration: 0.22 }}
            className="space-y-4"
          >
            <div className="text-center mb-6">
              <h2 className="text-lg font-semibold dark:text-white text-gray-900">Step 2 — What do you want to do first?</h2>
              <p className="text-sm dark:text-white/50 text-gray-500 mt-1">Both need to happen. Do them in whichever order works for you.</p>
            </div>

            {/* Still-to-do banner */}
            {!effectiveStubsDone && !effectivePaychexDone ? null : (
              <div className={`flex items-center gap-2.5 rounded-xl px-4 py-3 border text-sm font-medium ${
                effectiveStubsDone && effectivePaychexDone
                  ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400'
                  : 'bg-amber-500/10 border-amber-500/25 text-amber-400'
              }`}>
                {effectiveStubsDone && effectivePaychexDone ? (
                  <><CheckCircle2 className="w-4 h-4 flex-shrink-0" /> Both steps complete! Batch is closing out.</>
                ) : (
                  <>
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                    Still to do:{' '}
                    {!effectiveStubsDone && 'Send pay stubs'}
                    {!effectiveStubsDone && !effectivePaychexDone && ' and '}
                    {!effectivePaychexDone && 'Download Paychex CSV'}
                  </>
                )}
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">

              {/* Card A: Send Stubs First */}
              <ForkCard
                icon={<Send className="w-6 h-6" />}
                iconColor="text-emerald-400"
                iconBg="bg-emerald-500/15"
                title="Send pay stubs first"
                body="Drivers will see what they earned today. Paychex can happen later."
                buttonLabel={stubsSending ? 'Sending…' : effectiveStubsDone ? 'Resend Stubs' : 'Send Stubs'}
                buttonStyle="emerald"
                done={effectiveStubsDone}
                doneLabel={`Sent to ${stubsResult?.sent ?? status.stubs_sent} drivers`}
                disabled={stubsSending}
                isReconfirm={effectiveStubsDone}
                onConfirmClick={() => {
                  if (effectiveStubsDone) {
                    setReconfirm('stubs')
                  } else {
                    setPathTaken(pt => pt ?? 'stubs_first')
                    setStubsConfirm(true)
                  }
                }}
              />

              {/* Card B: Paychex First */}
              <ForkCard
                icon={<FileSpreadsheet className="w-6 h-6" />}
                iconColor="text-[#667eea]"
                iconBg="bg-[#667eea]/15"
                title="Enter Paychex first"
                body="Export the CSV, upload to Paychex Flex, then come back and send stubs."
                buttonLabel={paychexDownloading ? 'Downloading…' : effectivePaychexDone ? 'Re-download CSV' : 'Download Paychex CSV'}
                buttonStyle="indigo"
                done={effectivePaychexDone}
                doneLabel="CSV downloaded"
                disabled={paychexDownloading}
                isReconfirm={effectivePaychexDone}
                onConfirmClick={() => {
                  if (effectivePaychexDone) {
                    setReconfirm('paychex')
                  } else {
                    setPathTaken(pt => pt ?? 'paychex_first')
                    downloadPaychex()
                  }
                }}
              />
            </div>
          </motion.div>
        )}

        {/* ── STEP 3: Done ──────────────────────────────────────────────── */}
        {step === 'done' && (
          <motion.div
            key="done"
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.3, type: 'spring', stiffness: 200, damping: 20 }}
            className="text-center py-12"
          >
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: 0.1, type: 'spring', stiffness: 260, damping: 18 }}
              className="w-20 h-20 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center mx-auto mb-6"
            >
              <CheckCircle2 className="w-10 h-10 text-emerald-400" />
            </motion.div>
            <h2 className="text-2xl font-bold dark:text-white text-gray-900 mb-2">Payroll complete!</h2>
            <p className="dark:text-white/50 text-gray-500 text-sm mb-6">
              {status.week_label || 'This batch'} is closed. Stubs were sent and Paychex was exported.
            </p>
            <a
              href="/payroll/workflow"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-medium text-white transition-all"
              style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
            >
              Back to all batches
            </a>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Send stubs confirm modal */}
      <AnimatePresence>
        {(stubsConfirm || reconfirm === 'stubs') && (
          <ConfirmModal
            icon={<Send className="w-5 h-5 text-emerald-400" />}
            iconBg="bg-emerald-500/15"
            title={reconfirm === 'stubs' ? 'Resend pay stubs?' : 'Send pay stubs'}
            subtitle={reconfirm === 'stubs'
              ? `Stubs were already sent to ${stubsResult?.sent ?? status.stubs_sent} drivers. This will resend to anyone who hasn't received one.`
              : `This will text ${preview?.stats.driver_count ?? status.driver_count} drivers their pay for ${status.week_label || 'this period'}.`
            }
            isWarning={reconfirm === 'stubs'}
            confirmLabel={reconfirm === 'stubs' ? 'Yes, resend' : 'Yes, send stubs'}
            confirmStyle="emerald"
            onConfirm={sendStubs}
            onCancel={() => { setStubsConfirm(false); setReconfirm(null) }}
          />
        )}
      </AnimatePresence>

      {/* Paychex re-download confirm modal */}
      <AnimatePresence>
        {reconfirm === 'paychex' && (
          <ConfirmModal
            icon={<FileSpreadsheet className="w-5 h-5 text-[#667eea]" />}
            iconBg="bg-[#667eea]/15"
            title="Download again?"
            subtitle="You already downloaded the Paychex CSV. Downloading again is fine — just make sure you use the latest file in Paychex Flex."
            isWarning
            confirmLabel="Download again"
            confirmStyle="indigo"
            onConfirm={downloadPaychex}
            onCancel={() => setReconfirm(null)}
          />
        )}
      </AnimatePresence>

      {/* Paystub drill-down modal */}
      <MomPaystubModal
        batchId={batchId}
        driver={paystubDriver}
        onClose={() => setPaystubDriver(null)}
      />
    </div>
  )
}

// ── Fork Card ────────────────────────────────────────────────────────────────

interface ForkCardProps {
  icon: React.ReactNode
  iconColor: string
  iconBg: string
  title: string
  body: string
  buttonLabel: string
  buttonStyle: 'emerald' | 'indigo'
  done: boolean
  doneLabel: string
  disabled: boolean
  isReconfirm: boolean
  onConfirmClick: () => void
}

function ForkCard({
  icon, iconColor, iconBg, title, body,
  buttonLabel, buttonStyle, done, doneLabel,
  disabled, isReconfirm, onConfirmClick,
}: ForkCardProps) {
  const gradient = buttonStyle === 'emerald'
    ? 'linear-gradient(135deg, #22c55e, #16a34a)'
    : 'linear-gradient(135deg, #667eea, #4f46e5)'

  return (
    <motion.div
      whileHover={{ y: -2 }}
      transition={{ duration: 0.18 }}
      className={`relative rounded-2xl border p-5 flex flex-col gap-4 transition-all duration-200 ${
        done
          ? 'dark:bg-white/[0.04] dark:border-white/[0.12] bg-gray-50 border-gray-200'
          : 'dark:bg-white/[0.06] dark:border-white/[0.12] bg-white border-gray-200 dark:hover:border-white/25 hover:border-gray-300 dark:hover:shadow-lg dark:hover:shadow-black/20'
      }`}
    >
      {/* Done badge */}
      {done && (
        <div className="absolute top-3 right-3 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/25">
          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
          <span className="text-[11px] font-semibold text-emerald-400">{doneLabel}</span>
        </div>
      )}

      <div className={`w-11 h-11 rounded-xl ${iconBg} flex items-center justify-center flex-shrink-0`}>
        <span className={iconColor}>{icon}</span>
      </div>

      <div className="flex-1">
        <h3 className="font-semibold dark:text-white text-gray-900 mb-1">{title}</h3>
        <p className="text-sm dark:text-white/50 text-gray-500 leading-relaxed">{body}</p>
      </div>

      <motion.button
        whileHover={{ scale: disabled ? 1 : 1.02 }}
        whileTap={{ scale: disabled ? 1 : 0.97 }}
        onClick={onConfirmClick}
        disabled={disabled}
        className={`w-full py-2.5 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 transition-opacity disabled:opacity-60 ${
          isReconfirm ? 'opacity-70 hover:opacity-90' : ''
        }`}
        style={{ background: gradient }}
      >
        {buttonLabel}
        {!disabled && <ChevronRight className="w-4 h-4" />}
      </motion.button>
    </motion.div>
  )
}

// ── Confirm Modal ────────────────────────────────────────────────────────────

interface ConfirmModalProps {
  icon: React.ReactNode
  iconBg: string
  title: string
  subtitle: string
  isWarning: boolean
  confirmLabel: string
  confirmStyle: 'emerald' | 'indigo'
  onConfirm: () => void
  onCancel: () => void
}

function ConfirmModal({ icon, iconBg, title, subtitle, isWarning, confirmLabel, confirmStyle, onConfirm, onCancel }: ConfirmModalProps) {
  const gradient = confirmStyle === 'emerald'
    ? 'linear-gradient(135deg, #22c55e, #16a34a)'
    : 'linear-gradient(135deg, #667eea, #4f46e5)'

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={e => { if (e.target === e.currentTarget) onCancel() }}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0, y: 8 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.95, opacity: 0, y: 8 }}
        transition={{ type: 'spring', stiffness: 300, damping: 25 }}
        className="w-full max-w-sm rounded-2xl dark:bg-[#0f0f14] bg-white border dark:border-white/10 border-gray-200 shadow-2xl p-6"
      >
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-xl ${iconBg} flex items-center justify-center flex-shrink-0`}>
              {icon}
            </div>
            <h3 className="text-base font-semibold dark:text-white text-gray-900">{title}</h3>
          </div>
          <button onClick={onCancel} className="dark:text-white/30 text-gray-400 hover:text-gray-600 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {isWarning && (
          <div className="flex items-start gap-2 rounded-xl bg-amber-500/10 border border-amber-500/25 px-3 py-2.5 mb-4">
            <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-amber-400">{subtitle}</p>
          </div>
        )}
        {!isWarning && (
          <p className="text-sm dark:text-white/60 text-gray-500 mb-4">{subtitle}</p>
        )}

        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium dark:bg-white/8 bg-gray-100 dark:text-white/70 text-gray-600 hover:dark:bg-white/12 hover:bg-gray-200 transition-colors"
          >
            Cancel
          </button>
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.97 }}
            onClick={onConfirm}
            className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium text-white flex items-center justify-center gap-1.5"
            style={{ background: gradient }}
          >
            {confirmLabel}
          </motion.button>
        </div>
      </motion.div>
    </motion.div>
  )
}
