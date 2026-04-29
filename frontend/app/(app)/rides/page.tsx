'use client'

import { useEffect, useState } from 'react'
import { Search, Car, Plus } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import DataTable, { Column } from '@/components/ui/DataTable'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import AddAdjustmentModal from '@/components/payroll/AddAdjustmentModal'

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

export default function RidesPage() {
  const [rides, setRides] = useState<Ride[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const [showModal, setShowModal] = useState(false)
  const [batches, setBatches] = useState<BatchOption[]>([])
  const [drivers, setDrivers] = useState<DriverOption[]>([])

  useEffect(() => {
    api.get<Ride[]>('/api/data/rides').then(setRides).catch(console.error).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (showModal && drivers.length === 0) {
      api.get<DriverOption[]>('/api/data/people')
        .then(setDrivers)
        .catch(() => {})
    }
    if (showModal && batches.length === 0) {
      // Fetch active/recent batches for the picker
      api.get<{
        id: number
        week_label?: string
        company?: string
        source?: string
        status?: string
        finalized_at?: string | null
        paychex_exported_at?: string | null
      }[]>('/api/data/batches?limit=30')
        .then(data => {
          // Refinement I — hide locked batches client-side (belt-and-suspenders).
          // A batch is locked if it has been finalized, exported to Paychex, or marked complete.
          const unlocked = data.filter(b => {
            const hasFields = 'finalized_at' in b || 'paychex_exported_at' in b
            if (!hasFields) {
              console.warn('[rides] Batch response missing finalized_at / paychex_exported_at — passing all through until backend ships fields')
              return true
            }
            if (b.finalized_at != null) return false
            if (b.paychex_exported_at != null) return false
            if (b.status === 'complete') return false
            return true
          })
          const mapped: BatchOption[] = unlocked.map(b => ({
            id: b.id,
            label: `${b.week_label ?? `Batch #${b.id}`} — ${b.company ?? ''} (${b.status ?? ''})`,
            source: b.source ?? '',
            company: b.company ?? '',
          }))
          setBatches(mapped)
        })
        .catch(() => {})
    }
  }, [showModal]) // eslint-disable-line react-hooks/exhaustive-deps

  function reload() {
    api.get<Ride[]>('/api/data/rides').then(setRides).catch(console.error)
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

      <AddAdjustmentModal
        open={showModal}
        onClose={() => setShowModal(false)}
        onSaved={() => { reload(); setShowModal(false) }}
        requireBatchAndDriverSelection
        availableBatches={batches}
        availableDrivers={drivers}
      />
    </div>
  )
}
