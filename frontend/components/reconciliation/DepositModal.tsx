'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Landmark, ShieldAlert, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'

export interface ReconBatchRow {
  batch_id?: number
  week?: string
  source?: string
  company?: string
  revenue?: number
  deposited?: number
  payment_status?: string
}

interface PartnerPayment {
  partner_payment_id: number
  deposit_date: string | null
  amount: number
}

interface DepositModalProps {
  batch: ReconBatchRow
  mode: 'record' | 'dispute'
  onClose: () => void
  onSaved: () => void
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

export default function DepositModal({ batch, mode, onClose, onSaved }: DepositModalProps) {
  const outstanding = Math.max((batch.revenue || 0) - (batch.deposited || 0), 0)
  const [amount, setAmount] = useState(outstanding > 0 ? outstanding.toFixed(2) : '')
  const [depositDate, setDepositDate] = useState(todayIso())
  const [memo, setMemo] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submitRecord() {
    const parsed = parseFloat(amount)
    if (!parsed || parsed <= 0) {
      setError('Enter the deposit amount')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await api.post('/api/data/partner-payments/create', {
        source: batch.source,
        amount: parsed,
        deposit_date: depositDate,
        payroll_batch_id: batch.batch_id,
        memo: memo.trim() || undefined,
      })
      onSaved()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to record deposit')
      setSaving(false)
    }
  }

  async function submitDispute() {
    if (!note.trim()) {
      setError('Cite the written dispute — email subject + date')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const res = await api.get<{ payments: PartnerPayment[] }>(
        `/api/data/partner-payments?batch_id=${batch.batch_id}`
      )
      const latest = (res.payments || [])[0]
      if (!latest) {
        setError('No deposit recorded for this batch — record the deposit first')
        setSaving(false)
        return
      }
      await api.post(`/api/data/partner-payments/${latest.partner_payment_id}/dispute`, {
        note: note.trim(),
      })
      onSaved()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to mark disputed')
      setSaving(false)
    }
  }

  const isRecord = mode === 'record'

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      >
        <motion.div
          className="w-full max-w-md rounded-2xl p-6 dark:bg-[#16161d] bg-white border dark:border-white/10 border-gray-200 shadow-2xl"
          initial={{ opacity: 0, scale: 0.96, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 12 }}
          onClick={e => e.stopPropagation()}
        >
          <div className="flex items-start justify-between mb-4">
            <div className="flex items-center gap-2.5">
              {isRecord
                ? <Landmark className="w-5 h-5 text-emerald-400" />
                : <ShieldAlert className="w-5 h-5 text-red-400" />}
              <div>
                <h2 className="text-base font-semibold dark:text-white text-gray-900">
                  {isRecord ? 'Record partner deposit' : 'Mark shortfall disputed'}
                </h2>
                <p className="text-xs dark:text-white/40 text-gray-400">
                  {batch.company || batch.source} · week {batch.week} · expected {formatCurrency(batch.revenue)}
                </p>
              </div>
            </div>
            <button onClick={onClose} className="p-1 rounded-lg dark:hover:bg-white/10 hover:bg-gray-100">
              <X className="w-4 h-4 dark:text-white/50 text-gray-400" />
            </button>
          </div>

          {isRecord ? (
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Amount deposited</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={amount}
                  onChange={e => setAmount(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                />
              </div>
              <div>
                <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Deposit date (bank posting date)</label>
                <input
                  type="date"
                  value={depositDate}
                  onChange={e => setDepositDate(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                />
                <p className="text-[11px] mt-1 dark:text-white/35 text-gray-400">
                  The 14-day dispute window starts on this date — use the real bank date.
                </p>
              </div>
              <div>
                <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Memo (optional)</label>
                <input
                  type="text"
                  value={memo}
                  onChange={e => setMemo(e.target.value)}
                  placeholder="e.g. split of $5,200 ACH covering 2 weeks"
                  className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                />
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-xs dark:text-white/50 text-gray-500 leading-relaxed">
                FA TPA §6b: shortfall claims are <span className="font-semibold text-red-400">waived 14 days after payment</span> unless
                disputed in writing. Only mark this after the written dispute (email) is actually sent.
              </p>
              <div>
                <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Where the written dispute lives</label>
                <input
                  type="text"
                  value={note}
                  onChange={e => setNote(e.target.value)}
                  placeholder='e.g. Email to FA billing 7/9 "W25 underpayment $132"'
                  className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                />
              </div>
            </div>
          )}

          {error && (
            <p className="mt-3 text-xs text-red-400">{error}</p>
          )}

          <div className="flex justify-end gap-2 mt-5">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-sm dark:text-white/60 text-gray-500 dark:hover:bg-white/5 hover:bg-gray-100"
            >
              Cancel
            </button>
            <button
              onClick={isRecord ? submitRecord : submitDispute}
              disabled={saving}
              className={`px-4 py-2 rounded-xl text-sm font-medium text-white flex items-center gap-2 disabled:opacity-50 ${
                isRecord ? 'bg-emerald-600 hover:bg-emerald-500' : 'bg-red-600 hover:bg-red-500'
              }`}
            >
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {isRecord ? 'Record deposit' : 'Mark disputed'}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
