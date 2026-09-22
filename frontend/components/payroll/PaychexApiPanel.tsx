'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertTriangle, CheckCircle2, ExternalLink, Send } from 'lucide-react'
import { toast } from 'sonner'
import { formatCurrency } from '@/lib/utils'
import { usePaychexApiPreview } from '@/hooks/usePaychexApiPreview'
import PaychexBotPanel from '@/components/payroll/PaychexBotPanel'

interface PaychexApiPanelProps {
  batchId: string | number
}

// Same proxy base as the preview fetch inside usePaychexApiPreview — keep
// this file's push call consistent with that hook's convention.
const PAYCHEX_API_BASE_PATH = '/api/data/paychex-api'
const PAYCHEX_FLEX_URL = 'https://myapps.paychex.com'

interface PaychexPushResultRow {
  person_id: string | number
  person: string
  amount: number
  status: 'staged' | 'failed'
  paycheck_id: string | null
  error: string | null
}

interface PaychexPushResponse {
  batch_id: string | number
  company: string
  staged: number
  failed: number
  total: number
  results: PaychexPushResultRow[]
}

interface PaychexPushErrorResponse {
  error?: string
  already_staged_person_ids?: Array<string | number>
}

type StagePhase = 'idle' | 'confirming' | 'staging' | 'done'

export default function PaychexApiPanel({ batchId }: PaychexApiPanelProps) {
  const { preview, loading, error, disabled, refetch } = usePaychexApiPreview(batchId)
  const [skipUnmatched, setSkipUnmatched] = useState(false)
  const [phase, setPhase] = useState<StagePhase>('idle')
  const [pushResult, setPushResult] = useState<PaychexPushResponse | null>(null)
  const [pushError, setPushError] = useState<string | null>(null)
  const [alreadyStagedIds, setAlreadyStagedIds] = useState<Array<string | number> | null>(null)

  // API rail off server-side → the old browser bot is the only way to send.
  if (disabled) return <PaychexBotPanel batchId={batchId} />
  if (loading && !preview) {
    return (
      <p className="text-xs dark:text-white/50 text-gray-500">Checking Paychex…</p>
    )
  }

  if (error) {
    return (
      <div className="p-4 rounded-2xl border dark:border-red-500/20 border-red-200 dark:bg-red-500/[0.06] bg-red-50">
        <div className="flex items-center gap-2 text-sm text-red-500">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          Paychex API preview failed: {error}
        </div>
        <button onClick={refetch} className="mt-2 text-xs dark:text-white/50 text-gray-400 hover:underline cursor-pointer">
          Retry
        </button>
      </div>
    )
  }

  if (!preview) return null

  const hasUnmatched = preview.unmatched.length > 0
  const canStage =
    preview.pay_period !== null &&
    preview.component_ok &&
    preview.count > 0 &&
    (!hasUnmatched || skipUnmatched)

  async function handleStageClick() {
    if (phase === 'idle') {
      setPhase('confirming')
      return
    }
    setPhase('staging')
    setPushError(null)
    setAlreadyStagedIds(null)
    try {
      const res = await fetch(`${PAYCHEX_API_BASE_PATH}/push/${batchId}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ skip_unmatched: skipUnmatched }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.status >= 400 && res.status < 500) {
        const errData = data as PaychexPushErrorResponse
        setPushError(errData.error ?? 'Failed to stage in Paychex')
        setAlreadyStagedIds(errData.already_staged_person_ids ?? null)
        setPhase('idle')
        return
      }
      if (!res.ok) {
        throw new Error((data as PaychexPushErrorResponse).error ?? 'Failed to stage in Paychex')
      }
      const result = data as PaychexPushResponse
      setPushResult(result)
      setPhase('done')
      if (result.failed > 0) {
        toast.warning(`Staged ${result.staged}/${result.total} in Paychex — ${result.failed} failed`)
      } else {
        toast.success(`Staged ${result.staged} checks in Paychex`)
      }
    } catch (e: unknown) {
      setPushError(e instanceof Error ? e.message : 'Failed to stage in Paychex')
      setPhase('idle')
    }
  }

  return (
    <div className="p-4 rounded-2xl bg-gradient-to-r from-emerald-500/10 to-cyan-500/10 border dark:border-white/10 border-gray-200 space-y-3">
      <span className="text-sm font-semibold dark:text-white text-gray-900 block">
        Send to Paychex
      </span>
      <p className="text-xs dark:text-white/60 text-gray-500">
        Puts these amounts into Paychex as unsubmitted checks. Nobody gets paid until you review and submit inside Paychex.
      </p>

      {preview.pay_period ? (
        <p className="text-xs dark:text-white/60 text-gray-500">
          Pay period: {preview.pay_period.description || `${preview.pay_period.start_date} – ${preview.pay_period.end_date}`}
          {' · check date '}{preview.pay_period.check_date}
        </p>
      ) : (
        <div className="text-xs dark:text-amber-300 text-amber-600 space-y-1">
          <p className="flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            {preview.pay_period_error ?? 'No matching open pay period found'}
          </p>
          {preview.open_pay_periods.length > 0 && (
            <ul className="pl-5 list-disc dark:text-amber-300/70 text-amber-600/80">
              {preview.open_pay_periods.map(p => (
                <li key={p.pay_period_id}>
                  {p.description || `${p.start_date} – ${p.end_date}`} ({p.status}, check {p.check_date})
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className={`text-xs ${preview.component_ok ? 'dark:text-white/60 text-gray-500' : 'dark:text-amber-300 text-amber-600'}`}>
        {preview.component_ok
          ? `1099 component configured (${preview.component_id})`
          : 'No 1099 pay component configured — set PAYCHEX_API_1099_COMPONENT_ID'}
      </p>

      {preview.matched.length > 0 && (
        <div className="max-h-48 overflow-y-auto rounded-lg border dark:border-white/10 border-gray-200">
          <table className="w-full text-xs">
            <thead className="dark:bg-white/[0.04] bg-gray-50 sticky top-0">
              <tr>
                <th className="text-left px-2 py-1.5 font-medium dark:text-white/50 text-gray-500">Driver</th>
                <th className="text-left px-2 py-1.5 font-medium dark:text-white/50 text-gray-500">Paychex ID</th>
                <th className="text-right px-2 py-1.5 font-medium dark:text-white/50 text-gray-500">Amount</th>
              </tr>
            </thead>
            <tbody>
              {preview.matched.map(row => (
                <tr key={row.person_id} className="border-t dark:border-white/[0.06] border-gray-100">
                  <td className="px-2 py-1.5 dark:text-white/80 text-gray-700">{row.person}</td>
                  <td className="px-2 py-1.5 font-mono dark:text-white/50 text-gray-400">{row.worker_id}</td>
                  <td className="px-2 py-1.5 text-right dark:text-white/80 text-gray-700">{formatCurrency(row.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {hasUnmatched && (
        <div className="p-2.5 rounded-lg dark:bg-amber-500/[0.08] bg-amber-50 border dark:border-amber-500/20 border-amber-200 space-y-1.5">
          <p className="text-xs font-medium dark:text-amber-300 text-amber-700">
            {preview.unmatched.length} unmatched — not staged automatically
          </p>
          <ul className="text-xs dark:text-amber-300/80 text-amber-700/90 space-y-0.5">
            {preview.unmatched.map(row => (
              <li key={row.person_id}>{row.person}: {row.reason}</li>
            ))}
          </ul>
          <label className="flex items-center gap-2 text-xs dark:text-white/70 text-gray-600 pt-1 cursor-pointer">
            <input
              type="checkbox"
              checked={skipUnmatched}
              onChange={e => setSkipUnmatched(e.target.checked)}
              className="cursor-pointer"
            />
            Skip unmatched drivers and stage the rest
          </label>
        </div>
      )}

      <p className="text-xs dark:text-white/50 text-gray-500">
        {preview.count} drivers · {formatCurrency(preview.total_amount)} total
      </p>

      <AnimatePresence mode="wait">
        {phase !== 'done' && (
          <motion.div key="stage-action" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-2">
            {phase === 'confirming' ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={handleStageClick}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-gradient-to-r from-emerald-500 to-cyan-500 text-white hover:opacity-90 transition-all cursor-pointer"
                >
                  Yes, send {formatCurrency(preview.total_amount)} for {preview.count} drivers
                </button>
                <button
                  onClick={() => setPhase('idle')}
                  className="text-xs dark:text-white/50 text-gray-400 cursor-pointer"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={handleStageClick}
                disabled={!canStage || phase === 'staging'}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-gradient-to-r from-emerald-500 to-cyan-500 text-white hover:opacity-90 transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Send className="w-4 h-4" />
                {phase === 'staging' ? 'Sending…' : `Send ${preview.count} checks to Paychex`}
              </button>
            )}

            {pushError && (
              <div className="p-2.5 rounded-lg dark:bg-red-500/[0.08] bg-red-50 border dark:border-red-500/20 border-red-200">
                <p className="text-xs text-red-500">{pushError}</p>
                {alreadyStagedIds && alreadyStagedIds.length > 0 && (
                  <p className="text-xs dark:text-red-400/70 text-red-600/80 mt-1">
                    This batch was already staged ({alreadyStagedIds.length} drivers).
                  </p>
                )}
              </div>
            )}
          </motion.div>
        )}

        {phase === 'done' && pushResult && (
          <motion.div key="stage-done" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-2">
            <p className={`text-sm flex items-center gap-1.5 ${pushResult.failed === 0 ? 'text-emerald-500' : 'dark:text-amber-300 text-amber-600'}`}>
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              {pushResult.failed === 0
                ? `Sent to Paychex — ${pushResult.staged} checks`
                : `Sent to Paychex — ${pushResult.staged} of ${pushResult.total}, ${pushResult.failed} failed`}
            </p>
            <div className="p-3 rounded-lg dark:bg-white/[0.04] bg-white border dark:border-white/10 border-gray-200 space-y-1.5">
              <p className="text-xs font-medium dark:text-white text-gray-900">Now finish in Paychex:</p>
              <ol className="text-xs dark:text-white/70 text-gray-600 list-decimal pl-4 space-y-0.5">
                <li>Open Paychex Flex and go to Payroll Center.</li>
                <li>
                  Open the payroll
                  {preview.pay_period ? ` for ${preview.pay_period.description || `${preview.pay_period.start_date} – ${preview.pay_period.end_date}`} (check date ${preview.pay_period.check_date})` : ''}.
                </li>
                <li>Check every driver and amount against the list below.</li>
                <li>Submit the payroll in Paychex. Nothing is paid until you do.</li>
              </ol>
              <a
                href={PAYCHEX_FLEX_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 mt-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-gradient-to-r from-indigo-500 to-cyan-500 text-white hover:opacity-90 transition-all"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                Open Paychex Flex
              </a>
            </div>
            <div className="max-h-48 overflow-y-auto rounded-lg border dark:border-white/10 border-gray-200">
              <table className="w-full text-xs">
                <thead className="dark:bg-white/[0.04] bg-gray-50 sticky top-0">
                  <tr>
                    <th className="text-left px-2 py-1.5 font-medium dark:text-white/50 text-gray-500">Driver</th>
                    <th className="text-right px-2 py-1.5 font-medium dark:text-white/50 text-gray-500">Amount</th>
                    <th className="text-left px-2 py-1.5 font-medium dark:text-white/50 text-gray-500">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {pushResult.results.map(row => (
                    <tr key={row.person_id} className="border-t dark:border-white/[0.06] border-gray-100">
                      <td className="px-2 py-1.5 dark:text-white/80 text-gray-700">{row.person}</td>
                      <td className="px-2 py-1.5 text-right dark:text-white/80 text-gray-700">{formatCurrency(row.amount)}</td>
                      <td className={`px-2 py-1.5 ${row.status === 'staged' ? 'text-emerald-500' : 'text-red-500'}`}>
                        {row.status === 'staged' ? 'Staged' : `Failed${row.error ? `: ${row.error}` : ''}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
