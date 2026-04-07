'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  DollarSign, Download, Mail, Check, AlertTriangle, RefreshCw,
  ChevronLeft, Send, SkipForward, RotateCcw, FileSpreadsheet,
  Users, Package, Pencil,
} from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import WorkflowStepper from '@/components/ui/WorkflowStepper'
import AlertCard from '@/components/ui/AlertCard'
import Badge from '@/components/ui/Badge'
import StatCard from '@/components/ui/StatCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

// ── Types ──────────────────────────────────────────────────────────────────

interface BatchStatus {
  batch_id: number
  source: string
  company: string
  company_raw: string
  status: string
  week_label: string
  period_start: string | null
  period_end: string | null
  rides: number
  revenue: number
  cost: number
  margin: number
  unpriced_rides: number
  driver_count: number
  stubs_sent: number
  stubs_failed: number
  next_stage: string | null
  blockers: string[]
  stage_index: number
  stages: string[]
  paychex_exported_at: string | null
}

interface RateGroup {
  service_name: string
  count: number
  total_net_pay: number
  drivers: string[]
  suggested_rate: number | null
  service_id: number | null
}

interface RatesCheck {
  total_unpriced: number
  groups: RateGroup[]
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
  withheld_amount: number
}

interface PayrollPreview {
  drivers: PayrollDriver[]
  withheld: PayrollDriver[]
  totals: { days: number; net_pay: number; pay_this_period: number }
  warnings: { severity: 'warning' | 'error' | 'info'; title: string; description: string; type: string; count?: number }[]
  stats: { driver_count: number; total_pay: number; withheld_amount: number; withheld_count: number }
}

interface StubDriver {
  person_id: number
  name: string
  email: string | null
  status: 'sent' | 'failed' | 'no_email' | 'pending'
  error: string | null
  sent_at: string | null
}

interface StubsStatus {
  drivers: StubDriver[]
  counts: { sent: number; failed: number; no_email: number; pending: number }
  total: number
}

// ── Step labels ─────────────────────────────────────────────────────────────

const STEP_LABELS = ['Rates', 'Review', 'Export', 'Stubs', 'Done']
const STAGE_TO_STEP: Record<string, number> = {
  uploaded: 0,
  rates_review: 0,
  payroll_review: 1,
  approved: 2,
  export_ready: 2,
  stubs_sending: 3,
  complete: 4,
}

// ── Main component ──────────────────────────────────────────────────────────

export default function BatchWorkflowPage() {
  const params = useParams()
  const router = useRouter()
  const batchId = Number(params.batchId)

  const [status, setStatus] = useState<BatchStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [advancing, setAdvancing] = useState(false)

  const refreshStatus = useCallback(() => {
    return api.get<BatchStatus>(`/api/data/workflow/${batchId}/status`)
      .then(setStatus)
      .catch(console.error)
  }, [batchId])

  useEffect(() => {
    refreshStatus().finally(() => setLoading(false))
  }, [refreshStatus])

  async function handleAdvance(force = false, notes?: string) {
    setAdvancing(true)
    try {
      await api.post(`/api/data/workflow/${batchId}/advance`, { force, notes })
      await refreshStatus()
    } catch (e) {
      console.error(e)
      await refreshStatus()
    } finally {
      setAdvancing(false)
    }
  }

  async function handleReopen() {
    try {
      await api.post(`/api/data/workflow/${batchId}/reopen`)
      await refreshStatus()
    } catch (e) {
      console.error(e)
    }
  }

  if (loading || !status) return <LoadingSpinner fullPage />

  const currentStep = STAGE_TO_STEP[status.status] ?? 0

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => router.push('/payroll/workflow')}
          className="p-2 rounded-lg hover:bg-white/10 transition-colors"
        >
          <ChevronLeft className="w-5 h-5 text-white/60" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-white">
              {status.week_label ? `${status.week_label} — ` : ''}{status.company} Payroll
            </h1>
            <Badge variant={status.company === 'FirstAlt' ? 'fa' : 'ed'} dot>
              {status.company}
            </Badge>
          </div>
          <p className="text-sm text-white/50 mt-0.5">
            {status.period_start && status.period_end
              ? `${new Date(status.period_start + 'T00:00:00').toLocaleDateString()} – ${new Date(status.period_end + 'T00:00:00').toLocaleDateString()}`
              : 'No period set'}
            {' · '}{status.rides} rides · {status.driver_count} drivers
          </p>
        </div>
      </div>

      {/* Stepper */}
      <div className="mb-10 px-4">
        <WorkflowStepper steps={STEP_LABELS} currentStep={currentStep} />
      </div>

      {/* Step content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={status.status}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          transition={{ duration: 0.25 }}
        >
          {(status.status === 'uploaded' || status.status === 'rates_review') && (
            <RatesReviewStep
              batchId={batchId}
              status={status}
              onAdvance={handleAdvance}
              advancing={advancing}
              onRefresh={refreshStatus}
            />
          )}
          {status.status === 'payroll_review' && (
            <PayrollReviewStep
              batchId={batchId}
              status={status}
              onAdvance={handleAdvance}
              advancing={advancing}
            />
          )}
          {(status.status === 'approved' || status.status === 'export_ready') && (
            <ExportStep
              batchId={batchId}
              status={status}
              onAdvance={handleAdvance}
              advancing={advancing}
            />
          )}
          {status.status === 'stubs_sending' && (
            <StubsStep
              batchId={batchId}
              status={status}
              onAdvance={handleAdvance}
              advancing={advancing}
              onRefresh={refreshStatus}
            />
          )}
          {status.status === 'complete' && (
            <CompleteStep status={status} />
          )}
        </motion.div>
      </AnimatePresence>

      {/* Reopen button for approved/export_ready */}
      {(status.status === 'approved' || status.status === 'export_ready') && (
        <div className="mt-6 text-center">
          <button
            onClick={handleReopen}
            className="text-sm text-white/40 hover:text-white/60 transition-colors inline-flex items-center gap-1"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Reopen for review
          </button>
        </div>
      )}
    </div>
  )
}

// ── Step 1: Rates Review ────────────────────────────────────────────────────

function RatesReviewStep({
  batchId, status, onAdvance, advancing, onRefresh,
}: {
  batchId: number
  status: BatchStatus
  onAdvance: (force?: boolean) => void
  advancing: boolean
  onRefresh: () => Promise<void>
}) {
  const [data, setData] = useState<RatesCheck | null>(null)
  const [loading, setLoading] = useState(true)
  const [rateInputs, setRateInputs] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)

  useEffect(() => {
    api.get<RatesCheck>(`/api/data/workflow/${batchId}/rates-check`)
      .then(d => {
        setData(d)
        // Pre-fill with suggested rates
        const inputs: Record<string, string> = {}
        d.groups.forEach(g => {
          if (g.suggested_rate) inputs[g.service_name] = g.suggested_rate.toString()
        })
        setRateInputs(inputs)
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [batchId])

  async function applyRate(serviceName: string, serviceId: number | null) {
    const rate = parseFloat(rateInputs[serviceName] || '0')
    if (!rate || rate <= 0) return

    setSaving(serviceName)
    try {
      if (serviceId) {
        // Update existing rate service
        await api.post(`/api/data/rates/${serviceId}/set`, { rate })
      } else {
        // Create new rate service via the workflow endpoint
        await api.post('/api/data/workflow/rates/create', {
          service_name: serviceName,
          source: status.source,
          company_name: status.company_raw,
          default_rate: rate,
        })
      }
      // Recalculate rides for this batch with the new rate
      await api.post(`/api/data/workflow/rates/apply-batch/${batchId}`)
      // Refresh
      const d = await api.get<RatesCheck>(`/api/data/workflow/${batchId}/rates-check`)
      setData(d)
      await onRefresh()
    } catch (e) {
      console.error(e)
    } finally {
      setSaving(null)
    }
  }

  if (loading) return <LoadingSpinner />

  const totalUnpriced = data?.total_unpriced || 0

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Rates Review</h2>
        <Badge variant={totalUnpriced === 0 ? 'success' : 'danger'} dot>
          {totalUnpriced === 0 ? 'All priced' : `${totalUnpriced} unpriced rides`}
        </Badge>
      </div>

      {totalUnpriced === 0 ? (
        <div className="text-center py-8">
          <Check className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
          <p className="text-white/70 mb-4">All rides have rates assigned.</p>
          <button
            onClick={() => onAdvance()}
            disabled={advancing}
            className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
          >
            {advancing ? 'Advancing...' : 'Continue to Payroll Review'}
          </button>
        </div>
      ) : (
        <>
          <div className="space-y-3 mb-6">
            {data?.groups.map(group => (
              <div
                key={group.service_name}
                className="rounded-xl p-4 dark:bg-white/5 dark:border dark:border-white/10"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">{group.service_name}</p>
                    <p className="text-xs text-white/40 mt-0.5">
                      {group.count} rides · {formatCurrency(group.total_net_pay)} company rate · {group.drivers.slice(0, 3).join(', ')}{group.drivers.length > 3 ? ` +${group.drivers.length - 3}` : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-white/40">$</span>
                    <input
                      type="number"
                      step="1"
                      min="0"
                      value={rateInputs[group.service_name] || ''}
                      onChange={e => setRateInputs(prev => ({ ...prev, [group.service_name]: e.target.value }))}
                      placeholder="Rate"
                      className="w-20 px-2 py-1.5 rounded-lg text-sm text-white bg-white/10 border border-white/20 focus:border-[#667eea] focus:outline-none text-right"
                    />
                    <button
                      onClick={() => applyRate(group.service_name, group.service_id)}
                      disabled={saving === group.service_name || !rateInputs[group.service_name]}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium bg-[#667eea] text-white hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
                    >
                      {saving === group.service_name ? '...' : 'Apply'}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-between">
            <button
              onClick={() => onAdvance(true)}
              disabled={advancing}
              className="text-sm text-white/40 hover:text-white/60 transition-colors inline-flex items-center gap-1"
            >
              <SkipForward className="w-3.5 h-3.5" />
              {advancing ? 'Advancing...' : 'Skip & continue anyway'}
            </button>
            <button
              onClick={() => onAdvance()}
              disabled={advancing || totalUnpriced > 0}
              className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
            >
              Continue to Payroll Review
            </button>
          </div>
        </>
      )}
    </div>
  )
}

// ── Step 2: Payroll Review ──────────────────────────────────────────────────

function PayrollReviewStep({
  batchId, status, onAdvance, advancing,
}: {
  batchId: number
  status: BatchStatus
  onAdvance: (force?: boolean) => void
  advancing: boolean
}) {
  const [data, setData] = useState<PayrollPreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [showConfirm, setShowConfirm] = useState(false)

  useEffect(() => {
    api.get<PayrollPreview>(`/api/data/workflow/${batchId}/payroll-preview`)
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [batchId])

  if (loading) return <LoadingSpinner />
  if (!data) return null

  const { drivers, withheld, totals, warnings, stats } = data

  return (
    <div>
      <h2 className="text-lg font-semibold text-white mb-4">Payroll Review</h2>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="space-y-2 mb-4">
          {warnings.map((w, i) => (
            <AlertCard key={i} severity={w.severity} title={w.title} description={w.description} />
          ))}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <StatCard label="Drivers" value={stats.driver_count} icon={<Users className="w-4 h-4" />} index={0} />
        <StatCard label="Total Payout" value={formatCurrency(stats.total_pay)} icon={<DollarSign className="w-4 h-4" />} color="success" index={1} />
        <StatCard label="Withheld" value={formatCurrency(stats.withheld_amount)} icon={<AlertTriangle className="w-4 h-4" />} color="warning" index={2} />
        <StatCard label="Under $100" value={stats.withheld_count} icon={<Package className="w-4 h-4" />} color="danger" index={3} />
      </div>

      {/* Paid drivers table */}
      <div className="rounded-xl overflow-hidden dark:bg-white/5 dark:border dark:border-white/10 mb-4">
        <div className="px-4 py-2.5 border-b border-white/10">
          <span className="text-sm font-medium text-white">Paid This Period ({drivers.length})</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-white/40 text-xs uppercase">
                <th className="px-4 py-2.5">Driver</th>
                <th className="px-4 py-2.5 text-right">Code</th>
                <th className="px-4 py-2.5 text-right">Days</th>
                <th className="px-4 py-2.5 text-right">Net Pay</th>
                <th className="px-4 py-2.5 text-right">Carried</th>
                <th className="px-4 py-2.5 text-right">Pay This Period</th>
              </tr>
            </thead>
            <tbody>
              {drivers.map(d => (
                <tr key={d.id} className="border-t border-white/5 hover:bg-white/5 transition-colors">
                  <td className="px-4 py-2 text-white">{d.name}</td>
                  <td className="px-4 py-2 text-right text-white/60">{d.pay_code || '—'}</td>
                  <td className="px-4 py-2 text-right text-white/60">{d.days}</td>
                  <td className="px-4 py-2 text-right text-white/60">{formatCurrency(d.net_pay)}</td>
                  <td className="px-4 py-2 text-right text-white/60">{d.carried_over ? formatCurrency(d.carried_over) : '—'}</td>
                  <td className="px-4 py-2 text-right text-emerald-400 font-medium">{formatCurrency(d.pay_this_period)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-white/20 font-bold">
                <td className="px-4 py-2.5 text-white" colSpan={2}>TOTALS</td>
                <td className="px-4 py-2.5 text-right text-white">{totals.days}</td>
                <td className="px-4 py-2.5 text-right text-white">{formatCurrency(totals.net_pay)}</td>
                <td className="px-4 py-2.5"></td>
                <td className="px-4 py-2.5 text-right text-emerald-400">{formatCurrency(totals.pay_this_period)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* Withheld section */}
      {withheld.length > 0 && (
        <div className="rounded-xl overflow-hidden dark:bg-white/5 dark:border dark:border-white/10 mb-6">
          <div className="px-4 py-2.5 border-b border-white/10">
            <span className="text-sm font-medium text-amber-400">Withheld — Under $100 ({withheld.length})</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-white/40 text-xs uppercase">
                  <th className="px-4 py-2.5">Driver</th>
                  <th className="px-4 py-2.5 text-right">Net Pay</th>
                  <th className="px-4 py-2.5 text-right">Carried</th>
                  <th className="px-4 py-2.5 text-right">Balance</th>
                </tr>
              </thead>
              <tbody>
                {withheld.map(d => (
                  <tr key={d.id} className="border-t border-white/5">
                    <td className="px-4 py-2 text-white">{d.name}</td>
                    <td className="px-4 py-2 text-right text-white/60">{formatCurrency(d.net_pay)}</td>
                    <td className="px-4 py-2 text-right text-white/60">{d.carried_over ? formatCurrency(d.carried_over) : '—'}</td>
                    <td className="px-4 py-2 text-right text-amber-400">{formatCurrency(d.withheld_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Approve */}
      {!showConfirm ? (
        <div className="text-center">
          <button
            onClick={() => setShowConfirm(true)}
            className="px-6 py-2.5 rounded-xl bg-emerald-600 text-white font-medium hover:bg-emerald-500 transition-colors"
          >
            Approve Payroll
          </button>
        </div>
      ) : (
        <div className="rounded-xl p-4 bg-emerald-500/10 border border-emerald-500/30 text-center">
          <p className="text-sm text-emerald-300 mb-3">
            This will lock the batch and commit withheld balances. Are you sure?
          </p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={() => setShowConfirm(false)}
              className="px-4 py-2 rounded-lg text-sm text-white/60 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => onAdvance()}
              disabled={advancing}
              className="px-6 py-2 rounded-lg text-sm font-medium bg-emerald-600 text-white hover:bg-emerald-500 transition-colors disabled:opacity-50"
            >
              {advancing ? 'Approving...' : 'Confirm & Approve'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Step 3: Paychex Export ──────────────────────────────────────────────────

function ExportStep({
  batchId, status, onAdvance, advancing,
}: {
  batchId: number
  status: BatchStatus
  onAdvance: (force?: boolean) => void
  advancing: boolean
}) {
  const isEverDriven = status.source === 'maz'
  const exported = !!status.paychex_exported_at

  async function downloadCSV() {
    // Trigger CSV download via the existing endpoint
    window.open(`/api/v1/summary/export/paycheck-csv?payroll_batch_id=${batchId}`, '_blank')
    // Wait a moment then refresh to pick up paychex_exported_at
    setTimeout(async () => {
      // Force a status refresh
      window.location.reload()
    }, 1500)
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-white mb-4">Paychex Export</h2>

      {isEverDriven ? (
        <div className="text-center py-8">
          <SkipForward className="w-12 h-12 text-blue-400 mx-auto mb-3" />
          <p className="text-white/70 mb-1">EverDriven batches don&apos;t use Paychex.</p>
          <p className="text-sm text-white/40 mb-4">Skip this step to continue to paystub sending.</p>
          <button
            onClick={() => onAdvance(true)}
            disabled={advancing}
            className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
          >
            {advancing ? 'Advancing...' : 'Skip to Paystubs'}
          </button>
        </div>
      ) : exported ? (
        <div className="text-center py-8">
          <Check className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
          <p className="text-white/70 mb-4">Paychex CSV has been downloaded.</p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={downloadCSV}
              className="px-4 py-2 rounded-lg text-sm text-white/60 hover:text-white border border-white/20 hover:border-white/40 transition-colors inline-flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Download Again
            </button>
            <button
              onClick={() => onAdvance()}
              disabled={advancing}
              className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
            >
              {advancing ? 'Advancing...' : 'Continue to Paystubs'}
            </button>
          </div>
        </div>
      ) : (
        <div className="text-center py-8">
          <FileSpreadsheet className="w-12 h-12 text-[#667eea] mx-auto mb-3" />
          <p className="text-white/70 mb-4">Download the Paychex CSV and enter amounts into Paychex Flex.</p>
          <button
            onClick={downloadCSV}
            className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors inline-flex items-center gap-2"
          >
            <Download className="w-4 h-4" />
            Download Paychex CSV
          </button>
        </div>
      )}
    </div>
  )
}

// ── Step 4: Paystub Sending ─────────────────────────────────────────────────

function StubsStep({
  batchId, status, onAdvance, advancing, onRefresh,
}: {
  batchId: number
  status: BatchStatus
  onAdvance: (force?: boolean) => void
  advancing: boolean
  onRefresh: () => Promise<void>
}) {
  const [data, setData] = useState<StubsStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [retrying, setRetrying] = useState<number | null>(null)

  const fetchStatus = useCallback(() => {
    return api.get<StubsStatus>(`/api/data/workflow/${batchId}/stubs-status`)
      .then(setData)
      .catch(console.error)
  }, [batchId])

  useEffect(() => {
    fetchStatus().finally(() => setLoading(false))
  }, [fetchStatus])

  async function sendAll() {
    setSending(true)
    try {
      await api.post(`/api/data/workflow/${batchId}/send-stubs`)
      await fetchStatus()
      await onRefresh()
    } catch (e) {
      console.error(e)
    } finally {
      setSending(false)
    }
  }

  async function retryOne(personId: number) {
    setRetrying(personId)
    try {
      await api.post(`/api/data/workflow/${batchId}/retry-stub/${personId}`)
      await fetchStatus()
    } catch (e) {
      console.error(e)
    } finally {
      setRetrying(null)
    }
  }

  if (loading) return <LoadingSpinner />
  if (!data) return null

  const { drivers, counts } = data
  const allDone = counts.pending === 0 && counts.failed === 0
  const progress = data.total > 0 ? Math.round(((counts.sent + counts.no_email) / data.total) * 100) : 0

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Send Paystubs</h2>
        <div className="flex items-center gap-2">
          <Badge variant="success">{counts.sent} sent</Badge>
          {counts.failed > 0 && <Badge variant="danger">{counts.failed} failed</Badge>}
          {counts.no_email > 0 && <Badge variant="default">{counts.no_email} no email</Badge>}
          {counts.pending > 0 && <Badge variant="warning">{counts.pending} pending</Badge>}
        </div>
      </div>

      {/* Progress bar */}
      <div className="w-full h-2 rounded-full bg-white/10 mb-4 overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.5 }}
          className="h-full rounded-full bg-emerald-500"
        />
      </div>

      {/* Send All button */}
      {counts.pending > 0 && (
        <div className="text-center mb-4">
          <button
            onClick={sendAll}
            disabled={sending}
            className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors disabled:opacity-50 inline-flex items-center gap-2"
          >
            <Send className="w-4 h-4" />
            {sending ? 'Sending...' : `Send All Paystubs (${counts.pending})`}
          </button>
        </div>
      )}

      {/* Driver list */}
      <div className="rounded-xl overflow-hidden dark:bg-white/5 dark:border dark:border-white/10 mb-6">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-white/40 text-xs uppercase">
                <th className="px-4 py-2.5">Driver</th>
                <th className="px-4 py-2.5">Email</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {drivers.map(d => (
                <tr key={d.person_id} className="border-t border-white/5">
                  <td className="px-4 py-2 text-white">{d.name}</td>
                  <td className="px-4 py-2 text-white/50 text-xs">{d.email || '—'}</td>
                  <td className="px-4 py-2">
                    {d.status === 'sent' && <Badge variant="success">Sent</Badge>}
                    {d.status === 'failed' && <Badge variant="danger">Failed</Badge>}
                    {d.status === 'no_email' && <Badge variant="default">No Email</Badge>}
                    {d.status === 'pending' && <Badge variant="warning">Pending</Badge>}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {d.status === 'failed' && (
                      <button
                        onClick={() => retryOne(d.person_id)}
                        disabled={retrying === d.person_id}
                        className="text-xs text-[#667eea] hover:underline inline-flex items-center gap-1"
                      >
                        <RefreshCw className={`w-3 h-3 ${retrying === d.person_id ? 'animate-spin' : ''}`} />
                        Retry
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Complete button */}
      {allDone && (
        <div className="text-center">
          <button
            onClick={() => onAdvance()}
            disabled={advancing}
            className="px-6 py-2.5 rounded-xl bg-emerald-600 text-white font-medium hover:bg-emerald-500 transition-colors disabled:opacity-50"
          >
            {advancing ? 'Completing...' : 'Complete Batch'}
          </button>
        </div>
      )}
      {!allDone && counts.pending === 0 && counts.failed > 0 && (
        <div className="text-center">
          <button
            onClick={() => onAdvance(true)}
            disabled={advancing}
            className="text-sm text-white/40 hover:text-white/60 transition-colors inline-flex items-center gap-1"
          >
            <SkipForward className="w-3.5 h-3.5" />
            {advancing ? 'Completing...' : 'Complete anyway (skip failures)'}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Step 5: Complete ────────────────────────────────────────────────────────

function CompleteStep({ status }: { status: BatchStatus }) {
  const router = useRouter()

  return (
    <div className="text-center py-12">
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: 'spring', stiffness: 300, damping: 20 }}
      >
        <Check className="w-16 h-16 text-emerald-400 mx-auto mb-4" />
      </motion.div>
      <h2 className="text-xl font-bold text-white mb-2">Batch Complete!</h2>
      <p className="text-white/50 mb-1">
        {status.company} · {status.rides} rides · {status.driver_count} drivers
      </p>
      <p className="text-emerald-400 font-medium mb-6">
        {formatCurrency(status.margin)} margin
      </p>
      <div className="flex items-center justify-center gap-3">
        <button
          onClick={() => router.push('/payroll/workflow')}
          className="px-4 py-2 rounded-lg text-sm text-white/60 hover:text-white border border-white/20 hover:border-white/40 transition-colors"
        >
          Back to Workflow
        </button>
        <button
          onClick={() => router.push('/payroll/history')}
          className="px-4 py-2 rounded-lg text-sm font-medium bg-[#667eea] text-white hover:bg-[#5a6fd6] transition-colors"
        >
          View History
        </button>
      </div>
    </div>
  )
}
