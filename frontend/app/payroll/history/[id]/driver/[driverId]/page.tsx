'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, Phone, Mail, Check, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface RideDetail {
  ride_id: number
  date?: string
  service_name: string
  miles: number
  net_pay: number
  z_rate: number
  deduction: number
  gross_pay: number
  margin: number
}

interface PaystubData {
  driver: {
    id: number
    name: string
    email?: string
    phone?: string
    pay_code?: string
  }
  batch: {
    id: number
    company: string
    source: string
    period_start?: string
    period_end?: string
    batch_ref?: string
  }
  rides: RideDetail[]
  totals: {
    rides: number
    miles: number
    net_pay: number
    z_rate: number
    deduction: number
    margin: number
  }
}

function formatPeriod(start?: string, end?: string) {
  if (!start && !end) return '—'
  const fmt = (d: string) => new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  if (start && end) return `${fmt(start)} – ${fmt(end)}`
  return fmt(start || end || '')
}

// ── Inline editable rate cell ──

function EditableRate({ ride, onSaved }: { ride: RideDetail; onSaved: (rideId: number, newRate: number) => void }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(String(ride.z_rate || ''))
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  async function save() {
    const rate = parseFloat(val)
    if (isNaN(rate)) return
    setSaving(true)
    try {
      await api.post(`/api/data/rides/${ride.ride_id}/set-rate`, { rate })
      onSaved(ride.ride_id, rate)
      setSaved(true)
      setTimeout(() => { setSaved(false); setEditing(false) }, 1200)
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  if (!editing) {
    return (
      <button
        onClick={() => { setEditing(true); setVal(String(ride.z_rate || '')) }}
        className={`text-xs font-semibold cursor-pointer hover:underline transition-colors ${ride.z_rate > 0 ? 'text-emerald-500' : 'text-red-400'}`}
        title="Click to edit driver pay"
      >
        {formatCurrency(ride.z_rate)}
      </button>
    )
  }

  return (
    <div className="flex items-center gap-1">
      <span className="text-xs text-gray-400">$</span>
      <input
        type="number"
        step="0.01"
        value={val}
        onChange={e => setVal(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false) }}
        autoFocus
        className="w-20 px-1.5 py-1 rounded-lg text-xs font-mono border dark:border-white/20 border-gray-300 dark:bg-white/5 bg-white dark:text-white text-gray-800 focus:outline-none focus:border-[#667eea]"
      />
      <button
        onClick={save}
        disabled={saving}
        className="p-1 rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-all cursor-pointer disabled:opacity-50"
      >
        {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : saved ? <Check className="w-3 h-3" /> : <Check className="w-3 h-3" />}
      </button>
    </div>
  )
}

export default function DriverPaystubPage() {
  const { id, driverId } = useParams<{ id: string; driverId: string }>()
  const router = useRouter()
  const [data, setData] = useState<PaystubData | null>(null)
  const [loading, setLoading] = useState(true)

  function handleBack() {
    if (window.history.length > 1) {
      router.back()
    } else {
      window.close()
    }
  }

  useEffect(() => {
    api.get<PaystubData>(`/api/data/payroll-history/${id}/driver/${driverId}`)
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [id, driverId])

  function handleRateSaved(rideId: number, newRate: number) {
    if (!data) return
    const updatedRides = data.rides.map(r =>
      r.ride_id === rideId ? { ...r, z_rate: newRate, margin: r.net_pay - newRate } : r
    )
    const newTotals = {
      ...data.totals,
      z_rate: updatedRides.reduce((s, r) => s + r.z_rate, 0),
      margin: updatedRides.reduce((s, r) => s + (r.net_pay - r.z_rate), 0),
    }
    setData({ ...data, rides: updatedRides, totals: newTotals })
  }

  if (loading) return <LoadingSpinner fullPage />
  if (!data) return <div className="text-center py-16 dark:text-white/40 text-gray-400">Pay stub not found</div>

  const { driver, batch, rides, totals } = data
  const isFa = batch.source?.includes('acumen')

  return (
    <div className="max-w-4xl mx-auto space-y-5 py-6">
      {/* Back + Header */}
      <div className="flex items-center gap-3">
        <button onClick={handleBack} className="p-2 rounded-xl dark:hover:bg-white/8 hover:bg-gray-100 transition-all dark:text-white/50 text-gray-500">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold dark:text-white text-gray-900">{driver.name}</h1>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <Badge variant={isFa ? 'fa' : 'ed'}>{batch.company}</Badge>
            <span className="text-xs dark:text-white/40 text-gray-400">{formatPeriod(batch.period_start, batch.period_end)}</span>
            {batch.batch_ref && <span className="text-xs font-mono dark:text-white/30 text-gray-400">#{batch.batch_ref}</span>}
          </div>
        </div>
      </div>

      {/* Driver info + totals */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Driver info card */}
        <div className="rounded-2xl p-5 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
          <h3 className="text-xs font-semibold text-gray-400 dark:text-white/40 uppercase tracking-wide mb-3">Driver Info</h3>
          <div className="space-y-2.5">
            <div className="flex items-center gap-2">
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-[#667eea] to-[#06b6d4] flex items-center justify-center text-white text-sm font-bold">
                {driver.name?.[0]?.toUpperCase() || '?'}
              </div>
              <div>
                <p className="text-sm font-semibold dark:text-white text-gray-900">{driver.name}</p>
                {driver.pay_code && <p className="text-xs font-mono dark:text-white/40 text-gray-400">Pay Code: {driver.pay_code}</p>}
              </div>
            </div>
            {driver.phone && (
              <div className="flex items-center gap-2 text-xs dark:text-white/50 text-gray-500">
                <Phone className="w-3.5 h-3.5" /> {driver.phone}
              </div>
            )}
            {driver.email && (
              <div className="flex items-center gap-2 text-xs dark:text-white/50 text-gray-500">
                <Mail className="w-3.5 h-3.5" /> {driver.email}
              </div>
            )}
          </div>
        </div>

        {/* Totals card */}
        <div className="rounded-2xl p-5 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10">
          <h3 className="text-xs font-semibold text-gray-400 dark:text-white/40 uppercase tracking-wide mb-3">Pay Summary</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Rides</p>
              <p className="text-lg font-bold dark:text-white text-gray-900">{totals.rides}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Total Miles</p>
              <p className="text-lg font-bold dark:text-white text-gray-900">{totals.miles}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Partner Pays</p>
              <p className="text-lg font-bold text-blue-500">{formatCurrency(totals.net_pay)}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Driver Pay</p>
              <p className="text-lg font-bold text-emerald-500">{formatCurrency(totals.z_rate)}</p>
            </div>
            {totals.deduction > 0 && (
              <div>
                <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Deductions</p>
                <p className="text-lg font-bold text-amber-500">-{formatCurrency(totals.deduction)}</p>
              </div>
            )}
            <div>
              <p className="text-[10px] text-gray-400 dark:text-white/30 uppercase">Margin</p>
              <p className={`text-lg font-bold ${totals.margin >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>{formatCurrency(totals.margin)}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Rides table */}
      <div className="rounded-2xl overflow-hidden bg-white dark:bg-white/3 border border-gray-200 dark:border-white/8">
        <div className="px-5 py-3 border-b border-gray-100 dark:border-white/8">
          <h3 className="text-sm font-semibold dark:text-white text-gray-900">Ride Breakdown</h3>
          <p className="text-xs dark:text-white/40 text-gray-400 mt-0.5">{rides.length} rides this period — click Driver Pay to edit</p>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b dark:border-white/8 border-gray-100 bg-gray-50/50 dark:bg-white/3">
              {['Date', 'Service / Route', 'Miles', 'Partner Pays', 'Driver Pay', 'Margin'].map(h => (
                <th key={h} className="px-4 py-2.5 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rides.map((ride, i) => (
              <tr key={ride.ride_id || i} className="border-b last:border-0 dark:border-white/5 border-gray-50 dark:hover:bg-white/3 hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3 text-xs dark:text-white/60 text-gray-500 whitespace-nowrap">{ride.date || '—'}</td>
                <td className="px-4 py-3">
                  <p className="text-sm dark:text-white text-gray-800 font-medium">{ride.service_name}</p>
                </td>
                <td className="px-4 py-3 text-xs font-mono dark:text-white/60 text-gray-600">{ride.miles > 0 ? `${ride.miles} mi` : '—'}</td>
                <td className="px-4 py-3 text-xs dark:text-white/70 text-gray-700">{formatCurrency(ride.net_pay)}</td>
                <td className="px-4 py-3">
                  <EditableRate ride={ride} onSaved={handleRateSaved} />
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs font-semibold ${ride.margin >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                    {formatCurrency(ride.margin)}
                  </span>
                </td>
              </tr>
            ))}
            {/* Totals */}
            <tr className="border-t-2 dark:border-white/20 border-gray-200 dark:bg-white/3 bg-gray-50 font-semibold">
              <td className="px-4 py-3 text-xs dark:text-white/60 text-gray-600">Total</td>
              <td className="px-4 py-3 text-xs dark:text-white/60 text-gray-600">{totals.rides} rides</td>
              <td className="px-4 py-3 text-xs font-mono dark:text-white text-gray-800">{totals.miles} mi</td>
              <td className="px-4 py-3 text-xs dark:text-white text-gray-800">{formatCurrency(totals.net_pay)}</td>
              <td className="px-4 py-3 text-xs text-emerald-500">{formatCurrency(totals.z_rate)}</td>
              <td className="px-4 py-3 text-xs text-emerald-500">{formatCurrency(totals.margin)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
