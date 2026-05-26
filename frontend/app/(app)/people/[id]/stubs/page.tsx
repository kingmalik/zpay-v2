'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowLeft, FileText, Download, Send, RefreshCw, Eye, Loader2, Check, X, AlertCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

// ── Types ─────────────────────────────────────────────────────────────────────

interface StubEntry {
  paystub_id: number
  batch_id: number
  batch_label: string
  generated_at: string | null
  sent_at: string | null
  recipient_email: string | null
  total_pay: number | null
  ride_count: number | null
  status: 'sent' | 'preview'
  regenerated_from_data: boolean
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// ── Re-email dialog ───────────────────────────────────────────────────────────

function ReEmailDialog({
  stub,
  onClose,
  onDone,
}: {
  stub: StubEntry
  onClose: () => void
  onDone: () => void
}) {
  const [email, setEmail] = useState(stub.recipient_email || '')
  const [sending, setSending] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')

  async function handleSend() {
    setSending(true)
    setError('')
    try {
      await api.post(`/api/paystubs/${stub.paystub_id}/email`, {
        to: email.trim() || undefined,
      })
      setDone(true)
      setTimeout(() => { onDone(); onClose() }, 1400)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Send failed')
    } finally {
      setSending(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="dark:bg-[#0f1729] bg-white rounded-2xl border dark:border-white/10 border-gray-200 p-6 w-full max-w-md shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold dark:text-white text-gray-900">
            Re-send Pay Stub
          </h3>
          <button onClick={onClose} className="p-1.5 rounded-lg dark:hover:bg-white/10 hover:bg-gray-100 transition-colors cursor-pointer">
            <X className="w-4 h-4 dark:text-white/50 text-gray-500" />
          </button>
        </div>

        <p className="text-sm dark:text-white/60 text-gray-500 mb-4">
          <span className="font-medium dark:text-white text-gray-800">{stub.batch_label}</span>
          {stub.total_pay !== null && (
            <span className="ml-2 text-emerald-500 font-semibold">{formatCurrency(stub.total_pay)}</span>
          )}
        </p>

        <label className="block text-xs font-medium dark:text-white/50 text-gray-500 mb-1.5">
          Send to (leave blank to use email on file)
        </label>
        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder={stub.recipient_email || 'driver@email.com'}
          className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 placeholder-gray-400 dark:placeholder-white/30 focus:outline-none focus:border-[#667eea]/60 transition-all mb-4"
        />

        {error && (
          <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-sm font-medium dark:text-white/50 text-gray-500 dark:hover:bg-white/5 hover:bg-gray-100 transition-all cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={handleSend}
            disabled={sending || done}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold bg-emerald-500 hover:bg-emerald-600 disabled:opacity-60 text-white transition-all cursor-pointer"
          >
            {done ? (
              <><Check className="w-4 h-4" /> Sent!</>
            ) : sending ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Sending…</>
            ) : (
              <><Send className="w-4 h-4" /> Send</>
            )}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function DriverStubsPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()

  const [stubs, setStubs] = useState<StubEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [reemailStub, setReemailStub] = useState<StubEntry | null>(null)
  const [regenerating, setRegenerating] = useState<number | null>(null)
  const [regenDone, setRegenDone] = useState<number | null>(null)

  // Minimal driver info for the header (re-use what we already have from people list)
  const [driverName, setDriverName] = useState<string>('')

  const fetchStubs = useCallback(() => {
    setLoading(true)
    api.get<StubEntry[]>(`/api/paystubs/person/${id}`)
      .then(data => { setStubs(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [id])

  useEffect(() => { fetchStubs() }, [fetchStubs])

  // Also fetch driver name for the header
  useEffect(() => {
    api.get<{ name?: string }>(`/api/data/people/${id}`)
      .then(d => { if (d.name) setDriverName(d.name) })
      .catch(() => {})
  }, [id])

  async function handleRegenerate(stub: StubEntry) {
    setRegenerating(stub.paystub_id)
    try {
      await api.post('/api/paystubs/regenerate', {
        person_id: parseInt(id),
        batch_id: stub.batch_id,
      })
      setRegenDone(stub.paystub_id)
      setTimeout(() => setRegenDone(null), 2000)
      fetchStubs()
    } catch (e) {
      console.error('Regenerate failed', e)
      import('sonner').then(m => m.toast.error('Could not regenerate paystub'))
    } finally {
      setRegenerating(null)
    }
  }

  function handleBack() {
    if (window.history.length > 1) router.back()
    else router.push('/people')
  }

  const BACKEND = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

  if (loading) return <LoadingSpinner fullPage />

  return (
    <>
      <div className="max-w-4xl mx-auto py-6 space-y-5">
        {/* Header */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleBack}
            className="p-2 rounded-xl dark:hover:bg-white/8 hover:bg-gray-100 transition-all dark:text-white/50 text-gray-500 cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="flex-1">
            <h1 className="text-2xl font-bold dark:text-white text-gray-900">
              {driverName || `Driver ${id}`} — Pay Stubs
            </h1>
            <p className="text-sm dark:text-white/40 text-gray-400 mt-0.5">
              {stubs.length} stub{stubs.length !== 1 ? 's' : ''} on file
            </p>
          </div>
          <Link
            href="/people"
            className="px-3 py-1.5 rounded-xl text-xs font-medium dark:text-white/50 text-gray-500 dark:hover:bg-white/5 hover:bg-gray-100 transition-all border dark:border-white/10 border-gray-200"
          >
            Back to People
          </Link>
        </div>

        {/* Table */}
        <div className="rounded-2xl overflow-hidden bg-white dark:bg-white/3 border border-gray-200 dark:border-white/8">
          {stubs.length === 0 ? (
            <div className="py-16 text-center">
              <FileText className="w-10 h-10 mx-auto mb-3 dark:text-white/20 text-gray-300" />
              <p className="text-sm dark:text-white/40 text-gray-400">
                No archived stubs yet.
              </p>
              <p className="text-xs dark:text-white/25 text-gray-400 mt-1">
                Stubs are saved automatically after each email send.
                Run the backfill script to import history.
              </p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b dark:border-white/8 border-gray-100 bg-gray-50/50 dark:bg-white/3">
                  {['Week', 'Generated', 'Sent To', 'Total', 'Rides', 'Actions'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400 first:rounded-tl-2xl last:rounded-tr-2xl">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stubs.map((stub, i) => (
                  <motion.tr
                    key={stub.paystub_id}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.04 }}
                    className="border-b last:border-0 dark:border-white/5 border-gray-50 dark:hover:bg-white/3 hover:bg-gray-50 transition-colors"
                  >
                    {/* Week */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold dark:text-white text-gray-900 text-sm">
                          {stub.batch_label}
                        </span>
                        {stub.regenerated_from_data && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-amber-500/10 text-amber-500 border border-amber-500/20 font-medium">
                            rebuilt
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Generated */}
                    <td className="px-4 py-3 text-xs dark:text-white/50 text-gray-500 whitespace-nowrap">
                      {fmtDate(stub.generated_at)}
                    </td>

                    {/* Sent To */}
                    <td className="px-4 py-3">
                      {stub.sent_at ? (
                        <div>
                          <p className="text-xs dark:text-white/70 text-gray-600 truncate max-w-[180px]">
                            {stub.recipient_email || '—'}
                          </p>
                          <p className="text-[10px] dark:text-white/30 text-gray-400 mt-0.5">
                            {fmtDate(stub.sent_at)}
                          </p>
                        </div>
                      ) : (
                        <span className="text-xs dark:text-white/30 text-gray-400 italic">Never sent</span>
                      )}
                    </td>

                    {/* Total */}
                    <td className="px-4 py-3">
                      <span className="text-sm font-semibold text-emerald-500">
                        {stub.total_pay !== null ? formatCurrency(stub.total_pay) : '—'}
                      </span>
                    </td>

                    {/* Rides */}
                    <td className="px-4 py-3 text-xs dark:text-white/60 text-gray-500">
                      {stub.ride_count ?? '—'}
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {/* View inline */}
                        <a
                          href={`${BACKEND}/api/paystubs/${stub.paystub_id}/pdf`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold dark:bg-white/5 bg-gray-100 dark:text-white/70 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-200 transition-all border dark:border-white/10 border-gray-200"
                          title="View PDF"
                        >
                          <Eye className="w-3.5 h-3.5" />
                          View
                        </a>

                        {/* Download */}
                        <a
                          href={`${BACKEND}/api/paystubs/${stub.paystub_id}/pdf?download=1`}
                          download
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold dark:bg-white/5 bg-gray-100 dark:text-white/70 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-200 transition-all border dark:border-white/10 border-gray-200"
                          title="Download PDF"
                        >
                          <Download className="w-3.5 h-3.5" />
                          Download
                        </a>

                        {/* Re-email */}
                        <button
                          onClick={() => setReemailStub(stub)}
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 dark:hover:bg-emerald-500/20 hover:bg-emerald-500/20 transition-all cursor-pointer"
                          title="Re-send this pay stub"
                        >
                          <Send className="w-3.5 h-3.5" />
                          Re-email
                        </button>

                        {/* Regenerate */}
                        <button
                          onClick={() => handleRegenerate(stub)}
                          disabled={regenerating === stub.paystub_id}
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 dark:hover:bg-blue-500/20 hover:bg-blue-500/20 transition-all disabled:opacity-50 cursor-pointer"
                          title="Rebuild PDF from current ride data"
                        >
                          {regenerating === stub.paystub_id ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : regenDone === stub.paystub_id ? (
                            <Check className="w-3.5 h-3.5" />
                          ) : (
                            <RefreshCw className="w-3.5 h-3.5" />
                          )}
                          Rebuild
                        </button>
                      </div>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Note about archive */}
        {stubs.length > 0 && (
          <p className="text-xs dark:text-white/30 text-gray-400 px-1">
            "Rebuilt" stubs were regenerated from current ride data and may differ slightly from the originally emailed version if rates were corrected after sending.
          </p>
        )}
      </div>

      {/* Re-email dialog */}
      <AnimatePresence>
        {reemailStub && (
          <ReEmailDialog
            stub={reemailStub}
            onClose={() => setReemailStub(null)}
            onDone={fetchStubs}
          />
        )}
      </AnimatePresence>
    </>
  )
}
