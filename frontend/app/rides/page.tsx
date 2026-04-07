'use client'

import { useEffect, useState } from 'react'
import { Search, Car } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import DataTable, { Column } from '@/components/ui/DataTable'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import EmptyState from '@/components/ui/EmptyState'

interface Ride {
  id?: string | number
  date?: string
  driver?: string
  service_code?: string
  service_name?: string
  miles?: number
  rate?: number
  net_pay?: number
}

export default function RidesPage() {
  const [rides, setRides] = useState<Ride[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  useEffect(() => {
    api.get<Ride[]>('/api/data/rides').then(setRides).catch(console.error).finally(() => setLoading(false))
  }, [])

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
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Rides</h1>
        <span className="px-2.5 py-1 rounded-full text-xs dark:bg-white/10 bg-gray-100 dark:text-white/50 text-gray-500">{filtered.length} rides</span>
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
    </div>
  )
}
