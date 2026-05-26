'use client'

/**
 * RemoveRideDialog — per-row admin control on the paystub UI.
 *
 * Soft-deletes a single ride from driver payout without touching revenue.
 * Requires a free-text reason (≤200 chars). The ride stays in the DB with
 * removed_at set; it shows as struck-through with a "Removed" badge so the
 * audit trail is visible to any admin reviewing the stub.
 *
 * Backend: PATCH /api/data/rides/{ride_id}/remove (admin-gated)
 *          PATCH /api/data/rides/{ride_id}/restore
 */

import { useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertTriangle, Loader2, Trash2, RotateCcw, X } from 'lucide-react'
import { api } from '@/lib/api'

interface RemoveRideDialogProps {
  rideId: number
  serviceName: string
  zRate: number
  /** Whether this ride is already soft-deleted */
  isRemoved: boolean
  removedReason?: string | null
  onDone: (rideId: number, removed: boolean) => void
}

// ── Tiny currency helper (avoids importing the global formatCurrency here) ────
function fmt(n: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
  }).format(n)
}

// ── Dialog ────────────────────────────────────────────────────────────────────

interface DialogProps {
  open: boolean
  onClose: () => void
  children: React.ReactNode
}

function Dialog({ open, onClose, children }: DialogProps) {
  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
          />
          {/* Panel */}
          <motion.div
            key="panel"
            initial={{ opacity: 0, scale: 0.95, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 8 }}
            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
            className="fixed inset-x-0 top-[20%] z-50 mx-auto max-w-md px-4"
          >
            <div className="rounded-2xl border border-white/10 bg-[#0e1117] shadow-2xl overflow-hidden">
              {children}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function RemoveRideButton({
  rideId,
  serviceName,
  zRate,
  isRemoved,
  removedReason,
  onDone,
}: RemoveRideDialogProps) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  function handleOpen() {
    setReason('')
    setError(null)
    setOpen(true)
    // Focus textarea on next frame
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  function handleClose() {
    if (busy) return
    setOpen(false)
  }

  async function handleRemove() {
    const trimmed = reason.trim()
    if (!trimmed) { setError('Reason is required.'); return }
    if (trimmed.length > 200) { setError('Reason must be 200 characters or fewer.'); return }
    setBusy(true)
    setError(null)
    try {
      await api.patch(`/api/data/rides/${rideId}/remove`, { reason: trimmed })
      setOpen(false)
      onDone(rideId, true)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Request failed'
      setError(msg)
    } finally {
      setBusy(false)
    }
  }

  async function handleRestore() {
    setBusy(true)
    setError(null)
    try {
      await api.patch(`/api/data/rides/${rideId}/restore`, {})
      setOpen(false)
      onDone(rideId, false)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Request failed'
      setError(msg)
    } finally {
      setBusy(false)
    }
  }

  if (isRemoved) {
    return (
      <>
        <button
          onClick={handleOpen}
          title={`Restore ride (removed: ${removedReason || '—'})`}
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 transition-all cursor-pointer"
        >
          <RotateCcw className="w-2.5 h-2.5" />
          Restore
        </button>

        <Dialog open={open} onClose={handleClose}>
          <div className="px-5 pt-5 pb-4">
            <div className="flex items-start gap-3 mb-4">
              <div className="flex-shrink-0 w-9 h-9 rounded-xl bg-amber-500/15 flex items-center justify-center">
                <RotateCcw className="w-4 h-4 text-amber-400" />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-sm font-bold text-white">Restore Ride</h2>
                <p className="text-xs text-white/50 mt-0.5 truncate">{serviceName}</p>
              </div>
              <button onClick={handleClose} className="text-white/30 hover:text-white/60 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            <p className="text-xs text-white/60 mb-1">
              This ride was removed with reason:
            </p>
            <p className="text-xs font-medium text-amber-400 mb-4 bg-amber-500/10 rounded-lg px-3 py-2 border border-amber-500/20">
              {removedReason || '—'}
            </p>
            <p className="text-xs text-white/50 mb-4">
              Restoring it will add <span className="text-white font-semibold">{fmt(zRate)}</span> back to this driver&apos;s payout. Confirm only if the driver was not already paid for this ride.
            </p>

            {error && (
              <p className="text-xs text-red-400 mb-3 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                {error}
              </p>
            )}
          </div>

          <div className="px-5 pb-5 flex gap-2">
            <button
              onClick={handleClose}
              disabled={busy}
              className="flex-1 px-3 py-2 rounded-xl text-sm font-semibold text-white/50 hover:text-white/80 hover:bg-white/5 transition-all disabled:opacity-40 cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={handleRestore}
              disabled={busy}
              className="flex-1 px-3 py-2 rounded-xl text-sm font-semibold bg-amber-500 hover:bg-amber-600 text-white transition-all disabled:opacity-50 flex items-center justify-center gap-2 cursor-pointer"
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
              {busy ? 'Restoring…' : 'Restore Ride'}
            </button>
          </div>
        </Dialog>
      </>
    )
  }

  // Active ride — show remove button
  return (
    <>
      <button
        onClick={handleOpen}
        title="Remove this ride from driver payout"
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold text-red-400/60 hover:bg-red-500/10 hover:text-red-400 transition-all cursor-pointer opacity-0 group-hover:opacity-100"
      >
        <Trash2 className="w-2.5 h-2.5" />
        Remove
      </button>

      <Dialog open={open} onClose={handleClose}>
        <div className="px-5 pt-5 pb-4">
          <div className="flex items-start gap-3 mb-4">
            <div className="flex-shrink-0 w-9 h-9 rounded-xl bg-red-500/15 flex items-center justify-center">
              <AlertTriangle className="w-4 h-4 text-red-400" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-sm font-bold text-white">Remove Ride from Payout</h2>
              <p className="text-xs text-white/50 mt-0.5 truncate">{serviceName}</p>
            </div>
            <button onClick={handleClose} className="text-white/30 hover:text-white/60 transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* What this does + what it does NOT do */}
          <div className="bg-white/4 rounded-xl border border-white/8 px-3 py-3 mb-4 space-y-1.5">
            <p className="text-[11px] font-semibold text-white/70">What happens:</p>
            <ul className="text-[11px] text-white/50 space-y-1 list-disc list-inside">
              <li>Driver will NOT be paid <span className="text-white font-semibold">{fmt(zRate)}</span> for this line</li>
              <li>Revenue numbers are untouched — the ride stays in Z-Pay</li>
              <li>Removed rides show struck-through on this page (audit trail)</li>
              <li>Driver&apos;s emailed pay stub will NOT include this line</li>
            </ul>
          </div>

          <div className="mb-4">
            <label className="block text-xs font-semibold text-white/60 mb-1.5">
              Reason <span className="text-red-400">*</span>
            </label>
            <textarea
              ref={inputRef}
              value={reason}
              onChange={e => setReason(e.target.value)}
              onKeyDown={e => { if (e.key === 'Escape') handleClose() }}
              maxLength={200}
              rows={2}
              placeholder="e.g. Already paid in W17 payroll"
              className="w-full px-3 py-2 rounded-xl text-sm border border-white/15 bg-white/5 text-white placeholder-white/25 focus:outline-none focus:border-[#667eea]/60 focus:ring-1 focus:ring-[#667eea]/20 resize-none transition-all"
            />
            <p className="text-[10px] text-white/30 mt-1 text-right">{reason.length}/200</p>
          </div>

          {error && (
            <p className="text-xs text-red-400 mb-3 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
              {error}
            </p>
          )}
        </div>

        <div className="px-5 pb-5 flex gap-2">
          <button
            onClick={handleClose}
            disabled={busy}
            className="flex-1 px-3 py-2 rounded-xl text-sm font-semibold text-white/50 hover:text-white/80 hover:bg-white/5 transition-all disabled:opacity-40 cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={handleRemove}
            disabled={busy || !reason.trim()}
            className="flex-1 px-3 py-2 rounded-xl text-sm font-semibold bg-red-500 hover:bg-red-600 text-white transition-all disabled:opacity-50 flex items-center justify-center gap-2 cursor-pointer"
          >
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
            {busy ? 'Removing…' : 'Remove Ride'}
          </button>
        </div>
      </Dialog>
    </>
  )
}
