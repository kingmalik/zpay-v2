'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  DollarSign, Download, Mail, Check, AlertTriangle, RefreshCw,
  ChevronLeft, Send, SkipForward, RotateCcw, FileSpreadsheet,
  Users, Package, Pencil, Save, Loader2, Eye, X,
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
  email: string
  days: number
  net_pay: number
  carried_over: number
  pay_this_period: number
  status: string
  withheld_amount: number
  force_pay_override?: boolean
  manual_withhold_note?: string | null
}

interface LateCancelRide {
  driver: string
  route: string
  z_rate: number
  net_pay: number
  ratio: number
}

interface NetPayChangeRide {
  route: string
  current_pay: number
  historical_avg: number
  change_pct: number
}

interface AffectedPerson {
  person_id: number
  name: string
  paycheck_code?: string
  email?: string
}

interface NegativeMarginDetail {
  service_name: string
  z_rate: number
  net_pay: number
  count: number
}

interface PayrollWarning {
  severity: 'warning' | 'error' | 'info'
  title: string
  description: string
  type: string
  count?: number
  rides?: LateCancelRide[] | NetPayChangeRide[]
  affected?: AffectedPerson[] | NegativeMarginDetail[]
}

interface PayrollPreview {
  drivers: PayrollDriver[]
  withheld: PayrollDriver[]
  totals: { days: number; net_pay: number; pay_this_period: number }
  warnings: PayrollWarning[]
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
              ? `${new Date(status.period_start + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })} – ${new Date(status.period_end + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`
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
              onRefresh={refreshStatus}
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

// ── Late cancellation detail (expandable) ──────────────────────────────────

function LateCancellationDetail({ rides }: { rides: LateCancelRide[] }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-amber-300/70 hover:text-amber-300 transition-colors underline underline-offset-2"
      >
        {expanded ? 'Hide details' : `Show ${rides.length} affected rides`}
      </button>
      {expanded && (
        <div className="mt-2 rounded-lg overflow-hidden bg-black/20 border border-white/5">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-white/40 uppercase">
                <th className="px-3 py-1.5">Driver</th>
                <th className="px-3 py-1.5">Route</th>
                <th className="px-3 py-1.5 text-right">Rate</th>
                <th className="px-3 py-1.5 text-right">Paid</th>
                <th className="px-3 py-1.5 text-right">Ratio</th>
              </tr>
            </thead>
            <tbody>
              {rides.map((r, i) => (
                <tr key={i} className="border-t border-white/5">
                  <td className="px-3 py-1.5 text-white/70">{r.driver}</td>
                  <td className="px-3 py-1.5 text-white/50 truncate max-w-[200px]">{r.route}</td>
                  <td className="px-3 py-1.5 text-right text-white/50">{formatCurrency(r.z_rate)}</td>
                  <td className="px-3 py-1.5 text-right text-amber-400">{formatCurrency(r.net_pay)}</td>
                  <td className="px-3 py-1.5 text-right text-white/40">{Math.round(r.ratio * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function NetPayChangeDetail({ rides }: { rides: NetPayChangeRide[] }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-blue-300/70 hover:text-blue-300 transition-colors underline underline-offset-2"
      >
        {expanded ? 'Hide details' : `Show ${rides.length} affected routes`}
      </button>
      {expanded && (
        <div className="mt-2 rounded-lg overflow-hidden bg-black/20 border border-white/5">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-white/40 uppercase">
                <th className="px-3 py-1.5">Route</th>
                <th className="px-3 py-1.5 text-right">Avg (Hist)</th>
                <th className="px-3 py-1.5 text-right">Current</th>
                <th className="px-3 py-1.5 text-right">Change</th>
              </tr>
            </thead>
            <tbody>
              {rides.map((r, i) => (
                <tr key={i} className="border-t border-white/5">
                  <td className="px-3 py-1.5 text-white/70 truncate max-w-[220px]">{r.route}</td>
                  <td className="px-3 py-1.5 text-right text-white/50">{formatCurrency(r.historical_avg)}</td>
                  <td className="px-3 py-1.5 text-right text-white/70">{formatCurrency(r.current_pay)}</td>
                  <td className={`px-3 py-1.5 text-right font-medium ${r.change_pct > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {r.change_pct > 0 ? '+' : ''}{r.change_pct}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Manual withhold button ────────────────────────────────────────────────────

function ManualWithholdButton({
  batchId, driver, onSaved,
}: {
  batchId: number
  driver: PayrollDriver
  onSaved: () => void
}) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)

  async function withhold() {
    setSaving(true)
    try {
      await api.post(`/api/data/workflow/${batchId}/manual-withhold/${driver.id}`, { note })
      onSaved()
      setOpen(false)
      setNote('')
    } finally { setSaving(false) }
  }

  async function release() {
    setSaving(true)
    try {
      await api.delete(`/api/data/workflow/${batchId}/manual-withhold/${driver.id}`)
      onSaved()
    } finally { setSaving(false) }
  }

  if (driver.manual_withhold_note != null) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-amber-400 font-semibold">Withheld</span>
        {driver.manual_withhold_note && (
          <span className="text-[10px] text-white/40 italic truncate max-w-[120px]" title={driver.manual_withhold_note}>
            "{driver.manual_withhold_note}"
          </span>
        )}
        <button onClick={release} disabled={saving} className="text-[10px] text-white/30 hover:text-red-400 transition-colors ml-1">
          Release
        </button>
      </div>
    )
  }

  if (open) {
    return (
      <div className="flex items-center gap-1">
        <input
          type="text"
          value={note}
          onChange={e => setNote(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') withhold(); if (e.key === 'Escape') setOpen(false) }}
          placeholder="Reason (optional)"
          autoFocus
          className="w-36 px-2 py-1 rounded text-xs text-white bg-white/10 border border-white/20 focus:border-amber-400 focus:outline-none"
        />
        <button onClick={withhold} disabled={saving} className="px-2 py-1 rounded text-xs bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 transition-colors disabled:opacity-50">
          {saving ? '...' : 'Withhold'}
        </button>
        <button onClick={() => setOpen(false)} className="text-xs text-white/30 hover:text-white/60">✕</button>
      </div>
    )
  }

  return (
    <button
      onClick={() => setOpen(true)}
      className="text-[10px] text-white/20 hover:text-amber-400 transition-colors"
      title="Manually withhold this driver's pay"
    >
      Withhold
    </button>
  )
}

// ── Click-to-edit cell ────────────────────────────────────────────────────────

function ClickToEdit({
  value, placeholder, inputType = 'text', onSave,
}: {
  value: string
  placeholder: string
  inputType?: string
  onSave: (val: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(value)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  // Keep in sync if parent data refreshes
  useEffect(() => { if (!editing) setVal(value) }, [value, editing])

  async function commit() {
    if (val.trim() === value) { setEditing(false); return }
    setSaving(true)
    try {
      await onSave(val.trim())
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
      setEditing(false)
    }
  }

  if (editing) {
    return (
      <input
        autoFocus
        type={inputType}
        value={val}
        onChange={e => setVal(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
        className="w-full px-2 py-1 rounded-lg text-xs text-white bg-white/10 border border-[#667eea] focus:outline-none"
      />
    )
  }

  return (
    <button
      onClick={() => setEditing(true)}
      className={`text-xs px-1 py-0.5 rounded hover:bg-white/10 transition-colors text-left w-full group ${saved ? 'text-emerald-400' : val ? 'text-white/70' : 'text-white/25 italic'}`}
    >
      {saved ? '✓ Saved' : val || placeholder}
      {!saved && <Pencil className="w-2.5 h-2.5 inline ml-1 opacity-0 group-hover:opacity-60 transition-opacity" />}
      {saving && <Loader2 className="w-2.5 h-2.5 inline ml-1 animate-spin" />}
    </button>
  )
}

// ── Inline editors for warnings ─────────────────────────────────────────────

function InlinePayCodeEditor({
  batchId, affected, onSaved,
}: {
  batchId: number
  affected: AffectedPerson[]
  onSaved: () => void
}) {
  const [values, setValues] = useState<Record<number, string>>(() => {
    const m: Record<number, string> = {}
    affected.forEach(p => { m[p.person_id] = p.paycheck_code || '' })
    return m
  })
  const [saving, setSaving] = useState<number | null>(null)
  const [saved, setSaved] = useState<Set<number>>(new Set())
  const [skipped, setSkipped] = useState<Set<number>>(new Set())
  const [errors, setErrors] = useState<Record<number, string>>({})

  async function save(personId: number) {
    const code = values[personId]?.trim()
    if (!code) return
    setSaving(personId)
    setErrors(prev => { const e = { ...prev }; delete e[personId]; return e })
    try {
      await api.patch(`/api/data/workflow/${batchId}/update-person/${personId}`, { paycheck_code: code })
      setSaved(prev => new Set(prev).add(personId))
      onSaved()
    } catch (e) {
      setErrors(prev => ({ ...prev, [personId]: 'Save failed' }))
    } finally {
      setSaving(null)
    }
  }

  const visible = affected.filter(p => !skipped.has(p.person_id))
  if (visible.length === 0) return <p className="mt-2 text-xs text-white/40 italic">All skipped — you can still approve payroll.</p>

  return (
    <div className="mt-3 space-y-2">
      {visible.map(p => (
        <div key={p.person_id} className="flex items-center gap-2 bg-black/20 rounded-lg px-3 py-2">
          <span className="text-sm text-white/80 flex-1 min-w-0 truncate">{p.name}</span>
          {saved.has(p.person_id) ? (
            <span className="text-sm text-emerald-400 inline-flex items-center gap-1.5 font-medium">
              <Check className="w-4 h-4" /> Saved
            </span>
          ) : (
            <>
              {errors[p.person_id] && (
                <span className="text-xs text-red-400">{errors[p.person_id]}</span>
              )}
              <input
                type="text"
                value={values[p.person_id] || ''}
                onChange={e => setValues(prev => ({ ...prev, [p.person_id]: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && save(p.person_id)}
                placeholder="Paychex code"
                className="w-32 px-2.5 py-1.5 rounded-lg text-sm text-white bg-white/10 border border-white/20 focus:border-amber-400 focus:outline-none"
              />
              <button
                onClick={() => save(p.person_id)}
                disabled={saving === p.person_id || !values[p.person_id]?.trim()}
                className="px-3 py-1.5 rounded-lg text-sm font-medium bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 disabled:opacity-40 transition-colors inline-flex items-center gap-1.5"
              >
                {saving === p.person_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                Save
              </button>
              <button
                onClick={() => setSkipped(prev => new Set(prev).add(p.person_id))}
                className="px-2 py-1.5 rounded-lg text-xs text-white/30 hover:text-white/60 transition-colors"
              >
                Skip
              </button>
            </>
          )}
        </div>
      ))}
    </div>
  )
}

function InlineEmailEditor({
  batchId, affected, onSaved,
}: {
  batchId: number
  affected: AffectedPerson[]
  onSaved: () => void
}) {
  const [values, setValues] = useState<Record<number, string>>(() => {
    const m: Record<number, string> = {}
    affected.forEach(p => { m[p.person_id] = p.email || '' })
    return m
  })
  const [saving, setSaving] = useState<number | null>(null)
  const [saved, setSaved] = useState<Set<number>>(new Set())
  const [errors, setErrors] = useState<Record<number, string>>({})

  async function save(personId: number) {
    const email = values[personId]?.trim()
    if (!email) return
    setSaving(personId)
    setErrors(prev => { const e = { ...prev }; delete e[personId]; return e })
    try {
      await api.patch(`/api/data/workflow/${batchId}/update-person/${personId}`, { email })
      setSaved(prev => new Set(prev).add(personId))
      onSaved()
    } catch (e) {
      setErrors(prev => ({ ...prev, [personId]: 'Save failed' }))
    } finally {
      setSaving(null)
    }
  }

  return (
    <div className="mt-3 space-y-2">
      {affected.map(p => (
        <div key={p.person_id} className="flex items-center gap-2 bg-black/20 rounded-lg px-3 py-2">
          <span className="text-sm text-white/80 flex-1 min-w-0 truncate">{p.name}</span>
          {saved.has(p.person_id) ? (
            <span className="text-sm text-emerald-400 inline-flex items-center gap-1.5 font-medium">
              <Check className="w-4 h-4" /> Saved
            </span>
          ) : (
            <>
              {errors[p.person_id] && (
                <span className="text-xs text-red-400">{errors[p.person_id]}</span>
              )}
              <input
                type="email"
                value={values[p.person_id] || ''}
                onChange={e => setValues(prev => ({ ...prev, [p.person_id]: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && save(p.person_id)}
                placeholder="email@example.com"
                className="w-48 px-2.5 py-1.5 rounded-lg text-sm text-white bg-white/10 border border-white/20 focus:border-blue-400 focus:outline-none"
              />
              <button
                onClick={() => save(p.person_id)}
                disabled={saving === p.person_id || !values[p.person_id]?.trim()}
                className="px-3 py-1.5 rounded-lg text-sm font-medium bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 disabled:opacity-40 transition-colors inline-flex items-center gap-1.5"
              >
                {saving === p.person_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                Save
              </button>
            </>
          )}
        </div>
      ))}
    </div>
  )
}

function InlineRateEditor({
  batchId, affected, onSaved,
}: {
  batchId: number
  affected: NegativeMarginDetail[]
  onSaved: () => void
}) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const m: Record<string, string> = {}
    affected.forEach(r => { m[r.service_name] = r.z_rate.toString() })
    return m
  })
  const [saving, setSaving] = useState<string | null>(null)
  const [saved, setSaved] = useState<Set<string>>(new Set())
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [errors, setErrors] = useState<Record<string, string>>({})

  async function save(serviceName: string) {
    const rate = parseFloat(values[serviceName] || '')
    if (isNaN(rate) || rate < 0) return
    setSaving(serviceName)
    setErrors(prev => { const e = { ...prev }; delete e[serviceName]; return e })
    try {
      await api.patch(`/api/data/workflow/${batchId}/update-ride-rate`, {
        service_name: serviceName,
        z_rate: rate,
      })
      setSaved(prev => new Set(prev).add(serviceName))
      onSaved()
    } catch (e) {
      setErrors(prev => ({ ...prev, [serviceName]: 'Save failed' }))
    } finally {
      setSaving(null)
    }
  }

  return (
    <div className="mt-3 rounded-lg overflow-hidden bg-black/20 border border-white/10">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-white/40 text-xs uppercase border-b border-white/10">
            <th className="px-3 py-2">Route</th>
            <th className="px-3 py-2 text-right">Rides</th>
            <th className="px-3 py-2 text-right">Co. Rate</th>
            <th className="px-3 py-2 text-right">Driver Rate</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {affected.filter(r => !dismissed.has(r.service_name)).map((r, i) => (
            <tr key={i} className="border-t border-white/5">
              <td className="px-3 py-2 text-white/80 max-w-[200px] truncate">{r.service_name}</td>
              <td className="px-3 py-2 text-right text-white/50">{r.count}</td>
              <td className="px-3 py-2 text-right text-white/50">{formatCurrency(r.net_pay)}</td>
              <td className="px-3 py-2 text-right">
                {saved.has(r.service_name) ? (
                  <span className="text-emerald-400 inline-flex items-center gap-1 font-medium">
                    <Check className="w-3.5 h-3.5" /> {formatCurrency(parseFloat(values[r.service_name] || '0'))}
                  </span>
                ) : (
                  <div className="inline-flex items-center gap-1">
                    <span className="text-white/40">$</span>
                    <input
                      type="number"
                      step="1"
                      min="0"
                      value={values[r.service_name] || ''}
                      onChange={e => setValues(prev => ({ ...prev, [r.service_name]: e.target.value }))}
                      onKeyDown={e => e.key === 'Enter' && save(r.service_name)}
                      className="w-20 px-2 py-1 rounded-lg text-sm text-white bg-white/10 border border-white/20 focus:border-amber-400 focus:outline-none text-right"
                    />
                    {errors[r.service_name] && (
                      <span className="text-xs text-red-400 ml-1">{errors[r.service_name]}</span>
                    )}
                  </div>
                )}
              </td>
              <td className="px-3 py-2 text-right">
                {!saved.has(r.service_name) && (
                  <div className="inline-flex items-center gap-2">
                    <button
                      onClick={() => save(r.service_name)}
                      disabled={saving === r.service_name || !values[r.service_name]}
                      className="px-3 py-1 rounded-lg text-sm font-medium bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 disabled:opacity-40 transition-colors inline-flex items-center gap-1.5"
                    >
                      {saving === r.service_name ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                      Save
                    </button>
                    <button
                      onClick={() => setDismissed(prev => new Set(prev).add(r.service_name))}
                      className="px-2 py-1 rounded-lg text-xs text-white/30 hover:text-white/60 transition-colors whitespace-nowrap"
                      title="This rate is intentional — dismiss warning"
                    >
                      This is correct
                    </button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Step 2: Payroll Review ──────────────────────────────────────────────────

function PayrollReviewStep({
  batchId, status, onAdvance, advancing, onRefresh,
}: {
  batchId: number
  status: BatchStatus
  onAdvance: (force?: boolean) => void
  advancing: boolean
  onRefresh: () => Promise<void>
}) {
  const [data, setData] = useState<PayrollPreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [showConfirm, setShowConfirm] = useState(false)

  const reloadPreview = useCallback(() => {
    return api.get<PayrollPreview>(`/api/data/workflow/${batchId}/payroll-preview`)
      .then(setData)
      .catch(console.error)
  }, [batchId])

  useEffect(() => {
    reloadPreview().finally(() => setLoading(false))
  }, [reloadPreview])

  async function handleInlineRefresh() {
    await reloadPreview()
    await onRefresh()
  }

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
            <AlertCard
              key={i}
              severity={w.severity}
              title={w.title}
              description={w.description}
              action={
                w.type === 'missing_pay_code' && w.affected?.length ? (
                  <InlinePayCodeEditor
                    batchId={batchId}
                    affected={w.affected as AffectedPerson[]}
                    onSaved={handleInlineRefresh}
                  />
                ) : w.type === 'missing_email' && w.affected?.length ? (
                  <InlineEmailEditor
                    batchId={batchId}
                    affected={w.affected as AffectedPerson[]}
                    onSaved={handleInlineRefresh}
                  />
                ) : w.type === 'negative_margin' && w.affected?.length ? (
                  <InlineRateEditor
                    batchId={batchId}
                    affected={w.affected as NegativeMarginDetail[]}
                    onSaved={handleInlineRefresh}
                  />
                ) : w.type === 'late_cancellation' && w.rides?.length ? (
                  <LateCancellationDetail rides={w.rides as LateCancelRide[]} />
                ) : w.type === 'net_pay_change' && w.rides?.length ? (
                  <NetPayChangeDetail rides={w.rides as NetPayChangeRide[]} />
                ) : undefined
              }
            />
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
                <th className="px-4 py-2.5">Code</th>
                <th className="px-4 py-2.5">Email</th>
                <th className="px-4 py-2.5 text-right">Days</th>
                <th className="px-4 py-2.5 text-right">Partner Pay</th>
                <th className="px-4 py-2.5 text-right">Carried</th>
                <th className="px-4 py-2.5 text-right">Driver Pay</th>
                <th className="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {drivers.map(d => (
                <tr key={d.id} className="border-t border-white/5 hover:bg-white/5 transition-colors">
                  <td className="px-4 py-2">
                    <a
                      href={`/payroll/history/${batchId}/driver/${d.id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-white hover:text-[#667eea] hover:underline transition-colors"
                    >
                      {d.name}
                    </a>
                  </td>
                  <td className="px-4 py-2">
                    <ClickToEdit
                      value={d.pay_code || ''}
                      placeholder="Add code"
                      onSave={val => api.patch(`/api/data/workflow/${batchId}/update-person/${d.id}`, { paycheck_code: val }).then(handleInlineRefresh)}
                    />
                  </td>
                  <td className="px-4 py-2">
                    <ClickToEdit
                      value={d.email || ''}
                      placeholder="Add email"
                      inputType="email"
                      onSave={val => api.patch(`/api/data/workflow/${batchId}/update-person/${d.id}`, { email: val }).then(handleInlineRefresh)}
                    />
                  </td>
                  <td className="px-4 py-2 text-right text-white/60">{d.days}</td>
                  <td className="px-4 py-2 text-right text-white/60">{formatCurrency(d.net_pay)}</td>
                  <td className="px-4 py-2 text-right text-white/60">{d.carried_over ? formatCurrency(d.carried_over) : '—'}</td>
                  <td className="px-4 py-2 text-right text-emerald-400 font-medium">{formatCurrency(d.pay_this_period)}</td>
                  <td className="px-4 py-2">
                    <ManualWithholdButton batchId={batchId} driver={d} onSaved={handleInlineRefresh} />
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-white/20 font-bold">
                <td className="px-4 py-2.5 text-white" colSpan={3}>TOTALS</td>
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
                  <th className="px-4 py-2.5 text-right">Partner Pay</th>
                  <th className="px-4 py-2.5 text-right">Carried</th>
                  <th className="px-4 py-2.5 text-right">Balance</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {withheld.map(d => (
                  <tr key={d.id} className="border-t border-white/5">
                    <td className="px-4 py-2 text-white">
                      {d.name}
                      {d.force_pay_override && <span className="ml-2 text-[10px] text-emerald-400 font-semibold uppercase">Force pay</span>}
                      {d.manual_withhold_note != null && (
                        <span className="ml-2 text-[10px] text-amber-400 font-semibold uppercase">Manual hold</span>
                      )}
                      {d.manual_withhold_note && (
                        <span className="ml-1 text-[10px] text-white/30 italic">"{d.manual_withhold_note}"</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right text-white/60">{formatCurrency(d.net_pay)}</td>
                    <td className="px-4 py-2 text-right text-white/60">{d.carried_over ? formatCurrency(d.carried_over) : '—'}</td>
                    <td className="px-4 py-2 text-right text-amber-400">{formatCurrency(d.withheld_amount)}</td>
                    <td className="px-4 py-2 text-right">
                      {d.force_pay_override ? (
                        <button
                          onClick={() => api.delete(`/api/data/workflow/${batchId}/override-withheld/${d.id}`).then(handleInlineRefresh)}
                          className="text-xs text-white/30 hover:text-red-400 transition-colors"
                        >
                          Undo
                        </button>
                      ) : (
                        <button
                          onClick={() => api.post(`/api/data/workflow/${batchId}/override-withheld/${d.id}`, {}).then(handleInlineRefresh)}
                          className="px-2.5 py-1 rounded-lg text-xs font-medium bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors"
                        >
                          Force pay
                        </button>
                      )}
                      {d.manual_withhold_note != null && (
                        <button
                          onClick={() => api.delete(`/api/data/workflow/${batchId}/manual-withhold/${d.id}`).then(handleInlineRefresh)}
                          className="ml-1 text-xs text-amber-400 hover:text-white/60 transition-colors"
                        >
                          Release hold
                        </button>
                      )}
                    </td>
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

interface EmailPreview { subject: string; body_html: string; driver_name: string; email: string }

function EmailPreviewModal({ preview, onClose }: { preview: EmailPreview; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl bg-[#1a1a2e] border border-white/10 shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
          <div>
            <p className="text-xs text-white/40 mb-0.5">To: {preview.email}</p>
            <p className="text-sm font-semibold text-white">{preview.subject}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/10 text-white/50 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto bg-white">
          <iframe
            srcDoc={preview.body_html}
            title="Email Preview"
            className="w-full min-h-[500px] border-0"
            sandbox="allow-same-origin"
          />
        </div>
      </div>
    </div>
  )
}

interface EmailTemplate { subject: string; body: string }

function EmailTemplateModal({
  batchId, onClose,
}: { batchId: number; onClose: () => void }) {
  const [tmpl, setTmpl] = useState<EmailTemplate | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.get<EmailTemplate>(`/api/data/workflow/${batchId}/email-template`).then(setTmpl).catch(console.error)
  }, [batchId])

  async function save() {
    if (!tmpl) return
    setSaving(true)
    try {
      await api.post(`/api/data/workflow/${batchId}/email-template`, tmpl)
      setSaved(true)
      setTimeout(() => { setSaved(false); onClose() }, 1000)
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl flex flex-col rounded-2xl bg-[#1a1a2e] border border-white/10 shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
          <div>
            <p className="text-sm font-semibold text-white">Edit Paystub Email</p>
            <p className="text-xs text-white/40 mt-0.5">This sets the email body for all drivers in this batch. Use <span className="font-mono bg-white/10 px-1 rounded">[First Name]</span>, <span className="font-mono bg-white/10 px-1 rounded">[Total Pay]</span>, <span className="font-mono bg-white/10 px-1 rounded">[Ride Count]</span></p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/10 text-white/50 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
        {!tmpl ? (
          <div className="p-8 text-center text-white/40 text-sm">Loading...</div>
        ) : (
          <div className="p-5 space-y-4">
            <div>
              <label className="text-xs text-white/40 uppercase tracking-wide mb-1.5 block">Subject</label>
              <input
                type="text"
                value={tmpl.subject}
                onChange={e => setTmpl({ ...tmpl, subject: e.target.value })}
                className="w-full px-3 py-2 rounded-lg text-sm border border-white/20 bg-white/5 text-white focus:outline-none focus:border-[#667eea]"
              />
            </div>
            <div>
              <label className="text-xs text-white/40 uppercase tracking-wide mb-1.5 block">Email Body</label>
              <textarea
                value={tmpl.body}
                onChange={e => setTmpl({ ...tmpl, body: e.target.value })}
                rows={10}
                className="w-full px-3 py-2 rounded-lg text-sm border border-white/20 bg-white/5 text-white focus:outline-none focus:border-[#667eea] font-mono resize-y"
              />
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-white/50 hover:text-white border border-white/20 hover:border-white/40 transition-colors">
                Cancel
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-[#667eea] text-white hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
              >
                {saved ? '✓ Saved' : saving ? 'Saving...' : 'Save Template'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function InlineStubEmailEditor({
  batchId, driver, onSaved,
}: {
  batchId: number
  driver: StubDriver
  onSaved: (personId: number, newEmail: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(driver.email || '')
  const [saving, setSaving] = useState(false)

  async function save() {
    const trimmed = val.trim()
    if (!trimmed) return
    setSaving(true)
    try {
      await api.patch(`/api/data/workflow/${batchId}/update-person/${driver.person_id}`, { email: trimmed })
      onSaved(driver.person_id, trimmed)
      setEditing(false)
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  if (!editing) {
    return (
      <button
        onClick={() => { setEditing(true); setVal(driver.email || '') }}
        className="flex items-center gap-1 text-xs text-white/50 hover:text-white/80 transition-colors group"
        title="Click to edit email"
      >
        <span>{driver.email || '—'}</span>
        <Pencil className="w-2.5 h-2.5 opacity-0 group-hover:opacity-60 transition-opacity" />
      </button>
    )
  }

  return (
    <div className="flex items-center gap-1">
      <input
        type="email"
        value={val}
        onChange={e => setVal(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false) }}
        autoFocus
        className="w-44 px-1.5 py-0.5 rounded text-xs border border-white/20 bg-white/5 text-white focus:outline-none focus:border-[#667eea]"
      />
      <button onClick={save} disabled={saving} className="text-emerald-400 hover:text-emerald-300 disabled:opacity-50">
        {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
      </button>
      <button onClick={() => setEditing(false)} className="text-white/30 hover:text-white/60">
        <X className="w-3 h-3" />
      </button>
    </div>
  )
}

interface SendProgress {
  current: number
  total: number
  currentDriver: string
  sent: number
  failed: number
  noEmail: number
}

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
  const [sendProgress, setSendProgress] = useState<SendProgress | null>(null)
  const [sendResult, setSendResult] = useState<{ sent: number; failed: number } | null>(null)
  const [retrying, setRetrying] = useState<number | null>(null)
  const [preview, setPreview] = useState<EmailPreview | null>(null)
  const [loadingPreview, setLoadingPreview] = useState<number | null>(null)
  const [showTemplateEditor, setShowTemplateEditor] = useState(false)

  const fetchStatus = useCallback(() => {
    return api.get<StubsStatus>(`/api/data/workflow/${batchId}/stubs-status`)
      .then(setData)
      .catch(console.error)
  }, [batchId])

  useEffect(() => {
    fetchStatus().finally(() => setLoading(false))
  }, [fetchStatus])

  async function sendAll() {
    if (!data) return
    setSending(true)
    setSendResult(null)

    const pendingDrivers = data.drivers.filter(d => d.status === 'pending' || d.status === 'failed')
    const total = pendingDrivers.length
    const prog: SendProgress = { current: 0, total, currentDriver: '', sent: 0, failed: 0, noEmail: 0 }
    setSendProgress({ ...prog })

    for (let i = 0; i < pendingDrivers.length; i++) {
      const driver = pendingDrivers[i]
      prog.current = i + 1
      prog.currentDriver = driver.name
      setSendProgress({ ...prog })

      try {
        const res = await api.post<{ ok: boolean; status: string; name: string; error?: string }>(
          `/api/data/workflow/${batchId}/send-stub/${driver.person_id}`
        )
        const st = (res.status === 'sent' || res.status === 'already_sent') ? 'sent' : res.status === 'no_email' ? 'no_email' : 'failed'
        if (st === 'sent') prog.sent++
        else if (st === 'no_email') prog.noEmail++
        else prog.failed++

        setData(prev => {
          if (!prev) return prev
          return {
            ...prev,
            drivers: prev.drivers.map(d => d.person_id === driver.person_id ? { ...d, status: st as any } : d),
            counts: {
              sent: prev.counts.sent + (st === 'sent' ? 1 : 0),
              failed: prev.counts.failed + (st === 'failed' ? 1 : 0) - (driver.status === 'failed' && st !== 'failed' ? 1 : 0),
              no_email: prev.counts.no_email + (st === 'no_email' ? 1 : 0),
              pending: prev.counts.pending - (driver.status === 'pending' ? 1 : 0),
            },
          }
        })
      } catch {
        prog.failed++
        setData(prev => {
          if (!prev) return prev
          return {
            ...prev,
            drivers: prev.drivers.map(d => d.person_id === driver.person_id ? { ...d, status: 'failed' } : d),
            counts: { ...prev.counts, failed: prev.counts.failed + 1, pending: prev.counts.pending - (driver.status === 'pending' ? 1 : 0) },
          }
        })
      }
      setSendProgress({ ...prog })
    }

    setSendResult({ sent: prog.sent, failed: prog.failed })
    setTimeout(() => setSendProgress(null), 2000)
    await fetchStatus()
    await onRefresh()
    setSending(false)
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

  async function showPreview(personId: number) {
    setLoadingPreview(personId)
    try {
      const p = await api.get<EmailPreview>(`/api/data/workflow/${batchId}/preview-stub/${personId}`)
      setPreview(p)
    } catch (e) { console.error(e) }
    finally { setLoadingPreview(null) }
  }

  function handleEmailSaved(personId: number, newEmail: string) {
    if (!data) return
    setData({
      ...data,
      drivers: data.drivers.map(d =>
        d.person_id === personId
          ? { ...d, email: newEmail, status: d.status === 'no_email' ? 'pending' : d.status }
          : d
      ),
      counts: {
        ...data.counts,
        no_email: data.drivers.filter(d => d.person_id !== personId && d.status === 'no_email').length,
        pending: data.drivers.filter(d => d.person_id === personId ? true : d.status === 'pending').length,
      },
    })
  }

  if (loading) return <LoadingSpinner />
  if (!data) return null

  const { drivers, counts } = data
  const allDone = counts.pending === 0 && counts.failed === 0
  const progress = data.total > 0 ? Math.round(((counts.sent + counts.no_email) / data.total) * 100) : 0
  const sendPct = sendProgress ? Math.round((sendProgress.current / sendProgress.total) * 100) : 0

  return (
    <div>
      {preview && <EmailPreviewModal preview={preview} onClose={() => setPreview(null)} />}
      {showTemplateEditor && <EmailTemplateModal batchId={batchId} onClose={() => setShowTemplateEditor(false)} />}

      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Send Paystubs</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowTemplateEditor(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-white/50 hover:text-white border border-white/20 hover:border-white/40 transition-colors"
          >
            <Pencil className="w-3 h-3" /> Edit Email
          </button>
          <Badge variant="success">{counts.sent} sent</Badge>
          {counts.failed > 0 && <Badge variant="danger">{counts.failed} failed</Badge>}
          {counts.no_email > 0 && <Badge variant="default">{counts.no_email} no email</Badge>}
          {counts.pending > 0 && <Badge variant="warning">{counts.pending} pending</Badge>}
        </div>
      </div>

      {/* Sending progress card */}
      <AnimatePresence>
        {sendProgress && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="mb-5 rounded-xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.03] bg-white p-4"
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 text-[#667eea] animate-spin" />
                <span className="text-sm font-medium dark:text-white text-gray-900">Sending emails...</span>
              </div>
              <span className="text-sm dark:text-white/60 text-gray-500">{sendProgress.current} / {sendProgress.total}</span>
            </div>
            <div className="w-full h-2.5 dark:bg-white/10 bg-gray-200 rounded-full overflow-hidden mb-3">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${sendPct}%` }}
                transition={{ duration: 0.3 }}
                className="h-full rounded-full bg-gradient-to-r from-[#667eea] to-[#06b6d4] transition-all duration-300"
              />
            </div>
            {sendProgress.currentDriver && (
              <p className="text-sm dark:text-white/60 text-gray-500 mb-2 truncate">
                <Mail className="w-3.5 h-3.5 inline mr-1.5 -mt-0.5" />
                {sendProgress.current <= sendProgress.total ? 'Sending to' : 'Finished with'}{' '}
                <span className="dark:text-white/80 text-gray-700 font-medium">{sendProgress.currentDriver}</span>
              </p>
            )}
            <div className="flex items-center gap-4 text-xs">
              {sendProgress.sent > 0 && (
                <span className="flex items-center gap-1 text-emerald-400"><Check className="w-3 h-3" /> {sendProgress.sent} sent</span>
              )}
              {sendProgress.failed > 0 && (
                <span className="flex items-center gap-1 text-red-400"><AlertTriangle className="w-3 h-3" /> {sendProgress.failed} failed</span>
              )}
              {sendProgress.noEmail > 0 && (
                <span className="flex items-center gap-1 dark:text-white/40 text-gray-400"><X className="w-3 h-3" /> {sendProgress.noEmail} no email</span>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Overall progress bar (when not actively sending) */}
      {!sendProgress && (
        <div className="w-full h-2 rounded-full dark:bg-white/10 bg-gray-200 mb-4 overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.5 }}
            className="h-full rounded-full bg-gradient-to-r from-[#667eea] to-[#06b6d4]"
          />
        </div>
      )}

      {/* Send result feedback */}
      {sendResult && !sendProgress && (
        <div className={`mb-4 px-4 py-2.5 rounded-xl text-sm font-medium ${
          sendResult.failed === -1 ? 'bg-red-500/15 text-red-400' :
          sendResult.failed > 0 ? 'bg-amber-500/15 text-amber-400' :
          'bg-emerald-500/15 text-emerald-400'
        }`}>
          {sendResult.failed === -1
            ? 'Send failed — check backend connection'
            : `Sent ${sendResult.sent}${sendResult.failed > 0 ? ` · ${sendResult.failed} failed (check email addresses)` : ''}`}
        </div>
      )}

      {/* Send All / Retry All buttons */}
      {(counts.pending > 0 || counts.failed > 0) && !sending && (
        <div className="text-center mb-4 flex items-center justify-center gap-3">
          {counts.pending > 0 && (
            <button
              onClick={sendAll}
              disabled={sending}
              className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors disabled:opacity-50 inline-flex items-center gap-2"
            >
              <Send className="w-4 h-4" />
              {`Send All Paystubs (${counts.pending})`}
            </button>
          )}
          {counts.failed > 0 && (
            <button
              onClick={sendAll}
              disabled={sending}
              className="px-6 py-2.5 rounded-xl bg-red-500/20 text-red-300 font-medium hover:bg-red-500/30 transition-colors disabled:opacity-50 inline-flex items-center gap-2 border border-red-500/30"
            >
              <RotateCcw className="w-4 h-4" />
              {`Retry All Failed (${counts.failed})`}
            </button>
          )}
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
                <th className="px-4 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {drivers.map(d => {
                const isCurrentlySending = sending && sendProgress?.currentDriver === d.name && sendProgress.current <= sendProgress.total
                return (
                  <tr
                    key={d.person_id}
                    className={`border-t border-white/5 transition-colors duration-300 ${isCurrentlySending ? 'dark:bg-[#667eea]/10 bg-blue-50' : ''}`}
                  >
                    <td className="px-4 py-2 text-white text-sm">
                      <span className="flex items-center gap-2">
                        {isCurrentlySending && <Loader2 className="w-3 h-3 text-[#667eea] animate-spin flex-shrink-0" />}
                        {d.name}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      {d.status === 'sent' ? (
                        <span className="text-xs text-white/40">{d.email || '—'}</span>
                      ) : (
                        <InlineStubEmailEditor batchId={batchId} driver={d} onSaved={handleEmailSaved} />
                      )}
                    </td>
                    <td className="px-4 py-2">
                      {d.status === 'sent' && <Badge variant="success">Sent</Badge>}
                      {d.status === 'failed' && <Badge variant="danger">Failed</Badge>}
                      {d.status === 'no_email' && <Badge variant="default">No Email</Badge>}
                      {d.status === 'pending' && !isCurrentlySending && <Badge variant="warning">Pending</Badge>}
                      {isCurrentlySending && <span className="text-xs text-[#667eea] font-medium">Sending...</span>}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex items-center gap-2 justify-end">
                        {d.status !== 'sent' && !sending && (
                          <button
                            onClick={() => showPreview(d.person_id)}
                            disabled={loadingPreview === d.person_id}
                            className="text-xs text-white/40 hover:text-white/70 transition-colors inline-flex items-center gap-1"
                            title="Preview email"
                          >
                            {loadingPreview === d.person_id
                              ? <Loader2 className="w-3 h-3 animate-spin" />
                              : <Eye className="w-3 h-3" />}
                          </button>
                        )}
                        {d.status === 'failed' && !sending && (
                          <button
                            onClick={() => retryOne(d.person_id)}
                            disabled={retrying === d.person_id}
                            className="text-xs text-[#667eea] hover:underline inline-flex items-center gap-1"
                          >
                            <RefreshCw className={`w-3 h-3 ${retrying === d.person_id ? 'animate-spin' : ''}`} />
                            Retry
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Complete button */}
      {allDone && !sending && (
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
      {!allDone && counts.pending === 0 && counts.failed > 0 && !sending && (
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
          onClick={() => router.push(`/payroll/workflow/${status.batch_id}/summary`)}
          className="px-4 py-2 rounded-lg text-sm font-medium bg-[#667eea] text-white hover:bg-[#5a6fd6] transition-colors"
        >
          View Summary & Download
        </button>
      </div>
    </div>
  )
}
