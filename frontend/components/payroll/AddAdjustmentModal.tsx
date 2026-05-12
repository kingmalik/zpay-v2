'use client'

import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, PlusCircle, AlertTriangle, Loader2, Route } from 'lucide-react'
import { api } from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface RouteOption {
  z_rate_service_id: number
  service_name: string
  default_rate: number
  last_miles: number
  last_ride_date: string | null
}

interface AddRideResponse {
  ok: boolean
  ride_id: number
  warning?: string
}

interface Person {
  id: number
  name: string
  /** Paychex code for FA/Acumen batches */
  paycheck_code?: string | null
  /** Paychex code for Maz/EverDriven batches */
  paycheck_code_maz?: string | null
}

// When the modal is used from the workflow page, batch + driver are pre-filled.
// When used from the global /rides page, the caller passes requireBatchAndDriverSelection
// and supplies lists to pick from.
interface BatchOption {
  id: number
  label: string
  source: string
  company: string
}

interface DriverOption {
  id: number
  name: string
  paycheck_code?: string | null
  paycheck_code_maz?: string | null
}

export interface AddAdjustmentModalProps {
  open: boolean
  onClose: () => void
  onSaved: () => void

  // Pre-filled when launched from the workflow page
  batchId?: number
  batchSource?: string   // 'firstalt' | 'maz'
  batchCompanyIsMaz?: boolean  // true for EverDriven/Maz batches
  person?: Person

  // Global /rides usage — lets operator pick batch + driver
  requireBatchAndDriverSelection?: boolean
  availableBatches?: BatchOption[]
  availableDrivers?: DriverOption[]

  // Refinement J: existing rides for this driver in this batch (workflow page only).
  // When provided, freeform reason is checked for duplicates.
  existingRides?: { service_name: string; z_rate: number }[]
}

type Mode = 'freeform' | 'route'

interface FormState {
  reason: string
  driver_pay: string
  date: string
  pickup_time: string
  miles: string
  notes: string
}

const TODAY = new Date().toISOString().split('T')[0]

const EMPTY_FORM: FormState = {
  reason: '',
  driver_pay: '',
  date: TODAY,
  pickup_time: '',
  miles: '0',
  notes: '',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatCurrency(v: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(v)
}

function inputCls(extra = '') {
  return `w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60 ${extra}`
}

function labelCls() {
  return 'block text-xs font-medium dark:text-white/60 text-gray-500 mb-1'
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function AddAdjustmentModal({
  open,
  onClose,
  onSaved,
  batchId: propBatchId,
  batchSource: propBatchSource,
  batchCompanyIsMaz: propBatchCompanyIsMaz,
  person: propPerson,
  requireBatchAndDriverSelection = false,
  availableBatches = [],
  availableDrivers = [],
  existingRides,
}: AddAdjustmentModalProps) {
  const [mode, setMode] = useState<Mode>('freeform')
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [selectedRouteId, setSelectedRouteId] = useState<number | null>(null)
  const [routes, setRoutes] = useState<RouteOption[]>([])
  const [routeSearch, setRouteSearch] = useState('')   // Refinement D
  const [routesLoading, setRoutesLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [saveWarning, setSaveWarning] = useState('')

  // Selection state for global /rides mode
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null)
  const [selectedDriverId, setSelectedDriverId] = useState<number | null>(null)

  // Derived effective values
  const effectiveBatchId = requireBatchAndDriverSelection ? selectedBatchId : (propBatchId ?? null)
  const effectiveDriver: Person | null = requireBatchAndDriverSelection
    ? (availableDrivers.find(d => d.id === selectedDriverId) ?? null)
    : (propPerson ?? null)

  const effectiveBatchIsMaz: boolean = requireBatchAndDriverSelection
    ? (() => {
        const b = availableBatches.find(b => b.id === selectedBatchId)
        return b ? isMazBatch(b.source, b.company) : false
      })()
    : (propBatchCompanyIsMaz ?? false)

  // Reset on open
  useEffect(() => {
    if (open) {
      setMode('freeform')
      setForm(EMPTY_FORM)
      setSelectedRouteId(null)
      setRoutes([])
      setRouteSearch('')
      setError('')
      setSaveWarning('')
      setSelectedBatchId(null)
      setSelectedDriverId(null)
    }
  }, [open])

  // Fetch routes when switching to Route tab (only when batchId is known)
  useEffect(() => {
    if (mode !== 'route' || !effectiveBatchId) return
    if (routes.length > 0) return  // cached
    setRoutesLoading(true)
    api
      .get<RouteOption[]>(`/api/data/workflow/${effectiveBatchId}/routes`)
      .then(setRoutes)
      .catch(() => setRoutes([]))
      .finally(() => setRoutesLoading(false))
  }, [mode, effectiveBatchId, routes.length])

  // Clear cached routes when batch changes in global mode
  useEffect(() => {
    setRoutes([])
    setSelectedRouteId(null)
  }, [effectiveBatchId])

  // Paychex-code preflight check
  const missingPaychexCode: boolean = !!effectiveDriver && (
    effectiveBatchIsMaz
      ? !effectiveDriver.paycheck_code_maz
      : !effectiveDriver.paycheck_code
  )

  function handleRouteSelect(idStr: string) {
    const id = parseInt(idStr)
    setSelectedRouteId(id)
    const r = routes.find(r => r.z_rate_service_id === id)
    if (!r) return
    setForm(f => ({
      ...f,
      miles: r.last_miles.toString(),
      driver_pay: r.default_rate.toString(),
    }))
  }

  function patch(field: keyof FormState, value: string) {
    setForm(f => ({ ...f, [field]: value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaveWarning('')

    // Validation
    if (!effectiveBatchId) {
      setError('Select a batch first.')
      return
    }
    if (!effectiveDriver) {
      setError('Select a driver first.')
      return
    }
    if (!form.reason.trim()) {
      setError('Reason is required for the audit trail.')
      return
    }
    const amount = parseFloat(form.driver_pay)
    if (isNaN(amount) || amount === 0) {
      setError('Amount must be non-zero (use a negative value to reduce pay).')
      return
    }
    if (!form.date) {
      setError('Date is required.')
      return
    }

    setSubmitting(true)
    try {
      const selectedRoute = mode === 'route' && selectedRouteId
        ? routes.find(r => r.z_rate_service_id === selectedRouteId)
        : null

      const body: Record<string, unknown> = {
        payroll_batch_id: effectiveBatchId,
        person_id: effectiveDriver.id,
        service_name: mode === 'route' && selectedRoute
          ? selectedRoute.service_name
          : form.reason.trim(),
        date: form.date,
        driver_pay: amount,
        miles: parseFloat(form.miles || '0'),
        notes: form.notes.trim() || undefined,
        reason: form.reason.trim(),
        mode,
      }

      if (mode === 'route' && selectedRoute) {
        body.z_rate_service_id = selectedRoute.z_rate_service_id
        // override_rate is the edited driver_pay when it differs from default_rate
        if (amount !== selectedRoute.default_rate) {
          body.override_rate = amount
        }
      }

      if (form.pickup_time) {
        body.pickup_time = form.pickup_time
      }

      const resp = await api.post<AddRideResponse>('/api/data/rides', body)

      if (resp.warning) {
        setSaveWarning(resp.warning)
      }

      onSaved()
      onClose()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save. Try again.'
      // Try to surface the backend detail for 409/400
      try {
        const parsed = JSON.parse(msg)
        setError(parsed.detail ?? parsed.error ?? msg)
      } catch {
        setError(msg)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const firstReasonRef = useRef<HTMLInputElement>(null)

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
        >
          <motion.div
            className="w-full max-w-md dark:bg-[#1a1a2e] bg-white rounded-2xl shadow-2xl border dark:border-white/10 border-gray-200 overflow-hidden"
            initial={{ opacity: 0, y: 16, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.97 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b dark:border-white/10 border-gray-100">
              <div className="flex items-center gap-2">
                <PlusCircle className="w-4 h-4 text-[#667eea]" />
                <h2 className="text-base font-semibold dark:text-white text-gray-900">
                  Add Adjustment
                </h2>
                {effectiveDriver && (
                  <span className="text-sm dark:text-white/40 text-gray-400">
                    — {effectiveDriver.name}
                  </span>
                )}
              </div>
              <button
                onClick={onClose}
                className="dark:text-white/40 text-gray-400 hover:dark:text-white/70 hover:text-gray-600 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Batch + Driver pickers (global /rides mode) */}
            {requireBatchAndDriverSelection && (
              <div className="px-6 pt-5 pb-0 space-y-3">
                <div>
                  <label className={labelCls()}>Batch</label>
                  <select
                    value={selectedBatchId ?? ''}
                    onChange={e => setSelectedBatchId(e.target.value ? parseInt(e.target.value) : null)}
                    className={inputCls()}
                  >
                    <option value="">Select batch…</option>
                    {availableBatches.map(b => (
                      <option key={b.id} value={b.id}>{b.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={labelCls()}>Driver</label>
                  <select
                    value={selectedDriverId ?? ''}
                    onChange={e => setSelectedDriverId(e.target.value ? parseInt(e.target.value) : null)}
                    className={inputCls()}
                  >
                    <option value="">Select driver…</option>
                    {availableDrivers.map(d => (
                      <option key={d.id} value={d.id}>{d.name}</option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            {/* Mode tabs */}
            <div className="flex gap-0 px-6 pt-4">
              {(['freeform', 'route'] as Mode[]).map(m => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={`
                    flex-1 py-2 text-sm font-medium border-b-2 transition-colors
                    ${mode === m
                      ? 'border-[#667eea] dark:text-white text-gray-900'
                      : 'border-transparent dark:text-white/40 text-gray-400 hover:dark:text-white/60 hover:text-gray-600'}
                  `}
                >
                  {m === 'freeform' ? 'Free-form' : 'Route'}
                </button>
              ))}
            </div>

            <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
              {/* Route picker (route mode only) */}
              {mode === 'route' && (
                <div>
                  <label className={labelCls()}>Route</label>
                  {!effectiveBatchId ? (
                    <p className="text-xs dark:text-white/40 text-gray-400 italic">
                      Select a batch first to load routes.
                    </p>
                  ) : routesLoading ? (
                    <div className="flex items-center gap-2 text-xs dark:text-white/40 text-gray-400">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading routes…
                    </div>
                  ) : routes.length === 0 ? (
                    <p className="text-xs dark:text-white/40 text-gray-400 italic">
                      No routes found for this batch.
                    </p>
                  ) : (
                    <div className="space-y-1.5">
                      {/* Refinement D — typeahead filter */}
                      <input
                        type="text"
                        value={routeSearch}
                        onChange={e => setRouteSearch(e.target.value)}
                        placeholder="Filter routes…"
                        className={inputCls()}
                      />
                      <select
                        value={selectedRouteId ?? ''}
                        onChange={e => handleRouteSelect(e.target.value)}
                        className={inputCls()}
                        size={Math.min(6, routes.filter(r =>
                          !routeSearch || r.service_name.toLowerCase().includes(routeSearch.toLowerCase())
                        ).length + 1)}
                      >
                        <option value="">Pick a route…</option>
                        {routes
                          .filter(r =>
                            !routeSearch ||
                            r.service_name.toLowerCase().includes(routeSearch.toLowerCase())
                          )
                          .map(r => (
                            <option key={r.z_rate_service_id} value={r.z_rate_service_id}>
                              {r.service_name} ({formatCurrency(r.default_rate)}, last {r.last_miles} mi)
                            </option>
                          ))}
                      </select>
                    </div>
                  )}
                </div>
              )}

              {/* Reason — always required */}
              <div>
                <label className={labelCls()}>
                  Reason <span className="text-red-400">*</span>
                </label>
                <input
                  ref={firstReasonRef}
                  type="text"
                  value={form.reason}
                  onChange={e => patch('reason', e.target.value)}
                  placeholder={mode === 'route' ? 'e.g. Makeup trip — missed Mon' : 'e.g. Bonus for perfect week'}
                  required
                  maxLength={200}
                  className={inputCls()}
                />
                {/* Refinement G — char counter + hint */}
                <div className="mt-1 space-y-0.5">
                  <p className="text-[10px] dark:text-white/30 text-gray-400 text-right">
                    {form.reason.length} / 200
                  </p>
                  <p className="text-[10px] dark:text-white/30 text-gray-400 italic">
                    Drivers see the first 42 characters on their stub PDF. Keep the most important info up front.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                {/* Amount */}
                <div>
                  <label className={labelCls()}>
                    Amount ($) <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    value={form.driver_pay}
                    onChange={e => patch('driver_pay', e.target.value)}
                    placeholder="0.00 or -50.00"
                    required
                    className={inputCls()}
                  />
                </div>

                {/* Miles */}
                <div>
                  <label className={labelCls()}>Miles</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    value={form.miles}
                    onChange={e => patch('miles', e.target.value)}
                    placeholder="0"
                    className={inputCls()}
                  />
                </div>

                {/* Date */}
                <div>
                  <label className={labelCls()}>Date <span className="text-red-400">*</span></label>
                  <input
                    type="date"
                    value={form.date}
                    onChange={e => patch('date', e.target.value)}
                    required
                    className={inputCls()}
                  />
                </div>

                {/* Pickup time */}
                <div>
                  <label className={labelCls()}>Pickup Time</label>
                  <input
                    type="time"
                    value={form.pickup_time}
                    onChange={e => patch('pickup_time', e.target.value)}
                    className={inputCls()}
                  />
                </div>
              </div>

              {/* Notes */}
              <div>
                <label className={labelCls()}>Notes</label>
                <input
                  type="text"
                  value={form.notes}
                  onChange={e => patch('notes', e.target.value)}
                  placeholder="Optional internal note"
                  className={inputCls()}
                />
              </div>

              {/* Paychex code warning */}
              {missingPaychexCode && effectiveDriver && (
                <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-500/10 border border-amber-500/30">
                  <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <p className="text-xs text-amber-300 leading-relaxed">
                    This driver has no Paychex Worker ID for this company. Saving will add the
                    line to their workflow total, but it will <strong>NOT</strong> export to
                    Paychex. Add a Paychex code first or pay them outside the system.
                  </p>
                </div>
              )}

              {/* Post-save backend warning (surfaced before next close) */}
              {saveWarning && (
                <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-500/10 border border-amber-500/30">
                  <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <p className="text-xs text-amber-300">{saveWarning}</p>
                </div>
              )}

              {/* Refinement J — duplicate-trip heuristic warning (freeform + existingRides only) */}
              {mode === 'freeform' && existingRides && form.reason.trim().length > 0 && (() => {
                const q = form.reason.trim().toLowerCase()
                const match = existingRides.find(r =>
                  r.service_name.toLowerCase().includes(q) || q.includes(r.service_name.toLowerCase())
                )
                return match ? (
                  <div className="flex items-start gap-2 p-3 rounded-xl bg-yellow-500/10 border border-yellow-500/30">
                    <span className="text-yellow-400 text-sm shrink-0">⚠</span>
                    <p className="text-xs text-yellow-300 leading-relaxed">
                      This driver already has a ride called &ldquo;{match.service_name}&rdquo; in this batch. Are you sure this isn&apos;t a duplicate?
                    </p>
                  </div>
                ) : null
              })()}

              {/* Error */}
              {error && (
                <p className="text-red-400 text-xs">{error}</p>
              )}

              {/* Actions */}
              <div className="flex gap-3 pt-1">
                <button
                  type="button"
                  onClick={onClose}
                  className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium dark:bg-white/5 bg-gray-100 dark:text-white/70 text-gray-600 hover:opacity-80 transition-opacity"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-[#667eea] hover:bg-[#5a6fd8] text-white transition-colors disabled:opacity-50 inline-flex items-center justify-center gap-2"
                >
                  {submitting
                    ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</>
                    : 'Add Adjustment'}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// ── Small inline button wired for the workflow driver tables ──────────────────

export interface AddAdjustmentButtonProps {
  batchId: number
  batchSource: string
  batchCompanyIsMaz: boolean
  driver: {
    id: number
    name: string
    pay_code?: string | null
    paycheck_code_maz?: string | null
  }
  existingRides?: { service_name: string; z_rate: number }[]
  onSaved: () => void
}

export function AddAdjustmentButton({
  batchId,
  batchSource,
  batchCompanyIsMaz,
  driver,
  existingRides,
  onSaved,
}: AddAdjustmentButtonProps) {
  const [open, setOpen] = useState(false)

  const person: Person = {
    id: driver.id,
    name: driver.name,
    paycheck_code: driver.pay_code ?? null,
    paycheck_code_maz: driver.paycheck_code_maz ?? null,
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-semibold border dark:border-white/15 border-gray-200 dark:bg-white/5 bg-white dark:text-white/80 text-gray-700 hover:dark:bg-white/10 hover:bg-gray-50 hover:dark:border-white/25 hover:border-gray-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#667eea]/60 active:scale-[0.97] transition-all"
        title="Add manual pay adjustment for this driver"
      >
        <span className="text-[#667eea] font-bold leading-none">+</span>
        Adjust
      </button>

      <AddAdjustmentModal
        open={open}
        onClose={() => setOpen(false)}
        onSaved={() => { onSaved(); setOpen(false) }}
        batchId={batchId}
        batchSource={batchSource}
        batchCompanyIsMaz={batchCompanyIsMaz}
        person={person}
        existingRides={existingRides}
      />
    </>
  )
}

// ── View/delete adjustments for a driver ─────────────────────────────────────

interface ManualRide {
  id: number
  service_name: string
  date: string
  driver_pay: number
  reason?: string
  notes?: string
}

export interface ViewAdjustmentsButtonProps {
  batchId: number
  driver: { id: number; name: string }
  onDeleted: () => void
}

export function ViewAdjustmentsButton({
  batchId,
  driver,
  onDeleted,
}: ViewAdjustmentsButtonProps) {
  const [open, setOpen] = useState(false)
  const [rides, setRides] = useState<ManualRide[]>([])
  const [loading, setLoading] = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)

  function load() {
    setLoading(true)
    api
      .get<ManualRide[]>(`/api/data/rides?batch_id=${batchId}&person_id=${driver.id}&source=manual`)
      .then(setRides)
      .catch(() => setRides([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (open) load()
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleDelete(rideId: number) {
    setDeleting(rideId)
    try {
      await api.delete(`/api/data/rides/${rideId}`)
      setRides(prev => prev.filter(r => r.id !== rideId))
      onDeleted()
    } catch {
      // silent — ride is still visible
    } finally {
      setDeleting(null)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-semibold border dark:border-white/15 border-gray-200 dark:bg-white/5 bg-white dark:text-white/80 text-gray-700 hover:dark:bg-white/10 hover:bg-gray-50 hover:dark:border-white/25 hover:border-gray-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 active:scale-[0.97] transition-all"
        title="View manual adjustments"
      >
        Adjustments
      </button>
    )
  }

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={(e) => { if (e.target === e.currentTarget) setOpen(false) }}
      >
        <motion.div
          className="w-full max-w-sm dark:bg-[#1a1a2e] bg-white rounded-2xl shadow-2xl border dark:border-white/10 border-gray-200 overflow-hidden"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 8 }}
          transition={{ duration: 0.18 }}
        >
          <div className="flex items-center justify-between px-5 py-3.5 border-b dark:border-white/10 border-gray-100">
            <div>
              <p className="text-sm font-semibold dark:text-white text-gray-900">
                Manual Adjustments
              </p>
              <p className="text-xs dark:text-white/40 text-gray-400">{driver.name}</p>
            </div>
            <button onClick={() => setOpen(false)} className="dark:text-white/40 text-gray-400 hover:dark:text-white/70 transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="px-5 py-4 min-h-[80px]">
            {loading ? (
              <div className="flex items-center gap-2 text-xs dark:text-white/40 text-gray-400">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
              </div>
            ) : rides.length === 0 ? (
              <p className="text-xs dark:text-white/40 text-gray-400 italic">
                No manual adjustments for this driver in this batch.
              </p>
            ) : (
              <div className="space-y-2">
                {rides.map(r => (
                  <div key={r.id} className="flex items-center justify-between gap-3 p-2.5 rounded-lg dark:bg-white/5 bg-gray-50">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs dark:text-white text-gray-800 truncate font-medium">
                        {r.service_name}
                      </p>
                      {r.reason && r.reason !== r.service_name && (
                        <p className="text-[10px] dark:text-white/40 text-gray-400 truncate">{r.reason}</p>
                      )}
                      <p className="text-[10px] dark:text-white/30 text-gray-400">
                        {r.date} · {formatCurrency(r.driver_pay)}
                      </p>
                    </div>
                    <button
                      onClick={() => handleDelete(r.id)}
                      disabled={deleting === r.id}
                      className="text-[10px] text-white/20 hover:text-red-400 transition-colors disabled:opacity-40 shrink-0"
                      title="Delete this adjustment"
                    >
                      {deleting === r.id ? <Loader2 className="w-3 h-3 animate-spin" /> : '✕'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="px-5 pb-4">
            <button
              onClick={() => setOpen(false)}
              className="w-full px-4 py-2 rounded-xl text-sm font-medium dark:bg-white/5 bg-gray-100 dark:text-white/70 text-gray-600 hover:opacity-80 transition-opacity"
            >
              Close
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}

// ── Utility ───────────────────────────────────────────────────────────────────

function isMazBatch(source: string, company: string): boolean {
  const s = source.toLowerCase()
  const c = company.toLowerCase()
  return s === 'maz' || c.includes('maz') || c.includes('ever')
}
