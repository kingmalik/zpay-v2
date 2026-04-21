'use client'

import { useEffect, useState } from 'react'
import { Search, Car, Plus, X } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import DataTable, { Column } from '@/components/ui/DataTable'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import EmptyState from '@/components/ui/EmptyState'

interface Ride {
  id?: string | number
  date?: string
  driver?: string
  company?: string
  service_code?: string
  service_name?: string
  miles?: number
  rate?: number
  net_pay?: number
  gross_pay?: number
  z_rate?: number
  batch_ref?: string
}

interface Driver {
  id: number
  name: string
  company?: string
}

interface AddRideForm {
  service_name: string
  date: string
  pickup_time: string
  source: 'firstalt' | 'maz'
  person_id: string
  driver_pay: string
  miles: string
  notes: string
}

const EMPTY_FORM: AddRideForm = {
  service_name: '',
  date: new Date().toISOString().split('T')[0],
  pickup_time: '',
  source: 'firstalt',
  person_id: '',
  driver_pay: '',
  miles: '',
  notes: '',
}

export default function RidesPage() {
  const [rides, setRides] = useState<Ride[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState<AddRideForm>(EMPTY_FORM)
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get<Ride[]>('/api/data/rides').then(setRides).catch(console.error).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (showModal && drivers.length === 0) {
      api.get<{ id: number; name: string; company?: string }[]>('/api/data/people')
        .then(setDrivers)
        .catch(() => {})
    }
  }, [showModal])

  function reload() {
    api.get<Ride[]>('/api/data/rides').then(setRides).catch(console.error)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!form.service_name || !form.date || !form.driver_pay) {
      setError('School, date, and driver pay are required.')
      return
    }
    setSubmitting(true)
    try {
      await fetch('/api/data/rides', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          service_name: form.service_name,
          date: form.date,
          pickup_time: form.pickup_time,
          source: form.source,
          person_id: parseInt(form.person_id),
          driver_pay: parseFloat(form.driver_pay),
          miles: parseFloat(form.miles || '0'),
          notes: form.notes,
        }),
      })
      setShowModal(false)
      setForm(EMPTY_FORM)
      reload()
    } catch {
      setError('Failed to add ride. Try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const filtered = rides.filter(r => {
    const q = search.toLowerCase()
    const matchSearch = !q || r.driver?.toLowerCase().includes(q) || r.service_code?.toLowerCase().includes(q) || r.service_name?.toLowerCase().includes(q)
    const matchFrom = !dateFrom || (r.date || '') >= dateFrom
    const matchTo = !dateTo || (r.date || '') <= dateTo
    return matchSearch && matchFrom && matchTo
  })

  const columns: Column<Ride>[] = [
    { key: 'date', label: 'Date', sortable: true, render: row => formatDate(row.date) },
    { key: 'driver', label: 'Driver', sortable: true },
    { key: 'service_code', label: 'Code', mobileHide: true },
    { key: 'service_name', label: 'Service Name', sortable: true },
    { key: 'miles', label: 'Miles', sortable: true, render: row => `${row.miles || 0} mi` },
    { key: 'rate', label: 'Rate', render: row => formatCurrency(row.rate) },
    { key: 'net_pay', label: 'Net Pay', sortable: true, render: row => <span className="font-semibold text-emerald-500">{formatCurrency(row.net_pay)}</span> },
  ]

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold dark:text-white text-gray-900">Rides</h1>
          <span className="px-2.5 py-1 rounded-full text-xs dark:bg-white/10 bg-gray-100 dark:text-white/50 text-gray-500">{filtered.length} rides</span>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-[#667eea] hover:bg-[#5a6fd8] text-white transition-colors"
        >
          <Plus className="w-4 h-4" />
          Add Ride
        </button>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search rides..."
            className="pl-9 pr-4 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60 w-48" />
        </div>
        <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
          className="px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
        <span className="dark:text-white/30 text-gray-400 text-sm">to</span>
        <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
          className="px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
      </div>

      <DataTable columns={columns} data={filtered} keyField="id" emptyTitle="No rides found" emptySubtitle="Adjust your filters" />

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4">
          <div className="w-full max-w-md dark:bg-[#1a1a2e] bg-white rounded-2xl shadow-2xl border dark:border-white/10 border-gray-200 overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b dark:border-white/10 border-gray-100">
              <div className="flex items-center gap-2">
                <Car className="w-4 h-4 text-[#667eea]" />
                <h2 className="text-base font-semibold dark:text-white text-gray-900">Add New Ride</h2>
              </div>
              <button onClick={() => { setShowModal(false); setForm(EMPTY_FORM); setError('') }}
                className="dark:text-white/40 text-gray-400 hover:text-gray-600 dark:hover:text-white/70 transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="col-span-2">
                  <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">School / Service Name</label>
                  <input
                    value={form.service_name}
                    onChange={e => setForm(f => ({ ...f, service_name: e.target.value }))}
                    placeholder="e.g. Rosa Parks ES"
                    className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Date</label>
                  <input
                    type="date"
                    value={form.date}
                    onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
                    className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Pickup Time</label>
                  <input
                    type="time"
                    value={form.pickup_time}
                    onChange={e => setForm(f => ({ ...f, pickup_time: e.target.value }))}
                    className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Company</label>
                  <select
                    value={form.source}
                    onChange={e => setForm(f => ({ ...f, source: e.target.value as 'firstalt' | 'maz' }))}
                    className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                  >
                    <option value="firstalt">FirstAlt</option>
                    <option value="maz">EverDriven</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Driver Pay ($)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={form.driver_pay}
                    onChange={e => setForm(f => ({ ...f, driver_pay: e.target.value }))}
                    placeholder="0.00"
                    className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                  />
                </div>

                <div className="col-span-2">
                  <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Driver</label>
                  <select
                    value={form.person_id}
                    onChange={e => setForm(f => ({ ...f, person_id: e.target.value }))}
                    className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                  >
                    <option value="">Assign later</option>
                    {drivers.map(d => (
                      <option key={d.id} value={d.id}>{d.name}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Miles</label>
                  <input
                    type="number"
                    step="0.1"
                    value={form.miles}
                    onChange={e => setForm(f => ({ ...f, miles: e.target.value }))}
                    placeholder="0"
                    className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Notes</label>
                  <input
                    value={form.notes}
                    onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                    placeholder="Optional"
                    className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                  />
                </div>
              </div>

              {error && <p className="text-red-400 text-xs">{error}</p>}

              <div className="flex gap-3 pt-1">
                <button type="button" onClick={() => { setShowModal(false); setForm(EMPTY_FORM); setError('') }}
                  className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium dark:bg-white/5 bg-gray-100 dark:text-white/70 text-gray-600 hover:opacity-80 transition-opacity">
                  Cancel
                </button>
                <button type="submit" disabled={submitting}
                  className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-[#667eea] hover:bg-[#5a6fd8] text-white transition-colors disabled:opacity-50">
                  {submitting ? 'Adding...' : 'Add Ride'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
