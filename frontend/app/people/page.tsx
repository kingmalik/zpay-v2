'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Search, Users } from 'lucide-react'
import { api } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import DataTable, { Column } from '@/components/ui/DataTable'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface Driver {
  id: string | number
  name?: string
  company?: string
  fa_id?: string
  ed_id?: string
  phone?: string
  email?: string
  pay_code?: string
  notes?: string
  rides?: number
  last_active?: string
}

function InlineNoteEdit({ driverId, value, onSave }: { driverId: string | number; value: string; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(value)
  const [saving, setSaving] = useState(false)

  async function save() {
    setSaving(true)
    try {
      await api.post(`/people/${driverId}/set-notes`, { notes: val })
      onSave(val)
      setEditing(false)
    } catch {
      // revert
      setVal(value)
    } finally {
      setSaving(false)
    }
  }

  if (editing) {
    return (
      <div className="flex items-center gap-2">
        <input
          autoFocus
          value={val}
          onChange={e => setVal(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { setVal(value); setEditing(false) } }}
          className="px-2 py-1 text-xs rounded-lg dark:bg-white/10 bg-gray-100 dark:text-white text-gray-800 border dark:border-white/20 border-gray-300 focus:outline-none focus:border-[#667eea]/60 w-32"
        />
        <button onClick={save} disabled={saving} className="text-xs text-[#667eea] hover:text-[#7c93f0] cursor-pointer">
          {saving ? '...' : 'Save'}
        </button>
        <button onClick={() => { setVal(value); setEditing(false) }} className="text-xs dark:text-white/40 text-gray-400 cursor-pointer">✕</button>
      </div>
    )
  }

  return (
    <span
      onClick={() => setEditing(true)}
      className="cursor-pointer text-xs dark:text-white/60 text-gray-500 hover:dark:text-white hover:text-gray-800 transition-colors border-b border-dashed dark:border-white/20 border-gray-300"
      title="Click to edit"
    >
      {val || 'Add note...'}
    </span>
  )
}

export default function PeoplePage() {
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [company, setCompany] = useState('all')

  useEffect(() => {
    api.get<Driver[]>('/api/data/people').then(setDrivers).catch(console.error).finally(() => setLoading(false))
  }, [])

  const updateNote = useCallback((id: string | number, note: string) => {
    setDrivers(prev => prev.map(d => d.id === id ? { ...d, notes: note } : d))
  }, [])

  const filtered = drivers.filter(d => {
    const q = search.toLowerCase()
    const matchSearch = !q || (d.name?.toLowerCase().includes(q) || d.phone?.includes(q) || d.email?.toLowerCase().includes(q))
    const co = (d.company || '').toLowerCase()
    const matchCompany = company === 'all'
      || (company === 'fa' && (co.includes('first') || co === 'both'))
      || (company === 'ed' && (co.includes('ever') || co === 'both'))
    return matchSearch && matchCompany
  })

  const columns: Column<Driver>[] = [
    {
      key: 'name', label: 'Name', sortable: true,
      render: row => (
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[#667eea] to-[#06b6d4] flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
            {row.name?.[0]?.toUpperCase() || '?'}
          </div>
          <span className="font-medium dark:text-white text-gray-800">{row.name || '—'}</span>
        </div>
      ),
    },
    {
      key: 'company', label: 'Company',
      render: row => {
        const c = (row.company || '').toLowerCase()
        if (c === 'both') return <div className="flex gap-1"><Badge variant="fa">FA</Badge><Badge variant="ed">ED</Badge></div>
        if (c.includes('first')) return <Badge variant="fa">FirstAlt</Badge>
        if (c.includes('ever')) return <Badge variant="ed">EverDriven</Badge>
        return <span className="text-xs dark:text-white/40 text-gray-400">{row.company || '—'}</span>
      },
    },
    { key: 'fa_id', label: 'FA ID', mobileHide: true },
    { key: 'ed_id', label: 'ED ID', mobileHide: true },
    { key: 'phone', label: 'Phone' },
    { key: 'email', label: 'Email', mobileHide: true },
    { key: 'pay_code', label: 'Pay Code', mobileHide: true },
    {
      key: 'notes', label: 'Notes',
      render: row => <InlineNoteEdit driverId={row.id} value={row.notes || ''} onSave={v => updateNote(row.id, v)} />,
    },
    { key: 'rides', label: 'Rides', sortable: true, mobileHide: true },
    {
      key: 'last_active', label: 'Last Active', sortable: true, mobileHide: true,
      render: row => <span className="text-xs">{formatDate(row.last_active)}</span>,
    },
  ]

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold dark:text-white text-gray-900">People</h1>
          <span className="px-2.5 py-1 rounded-full text-xs font-medium dark:bg-white/10 bg-gray-100 dark:text-white/60 text-gray-500">
            {filtered.length} drivers
          </span>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search drivers..."
            className="pl-9 pr-4 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder-gray-400 dark:placeholder-white/30 focus:outline-none focus:border-[#667eea]/60 transition-all w-56"
          />
        </div>
        <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
          {[['all', 'All'], ['fa', 'FirstAlt'], ['ed', 'EverDriven']].map(([v, l]) => (
            <button
              key={v}
              onClick={() => setCompany(v)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all cursor-pointer ${company === v ? 'bg-[#667eea] text-white' : 'dark:text-white/50 text-gray-500'}`}
            >
              {l}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <DataTable
        columns={columns}
        data={filtered}
        keyField="id"
        emptyTitle="No drivers found"
        emptySubtitle="Try adjusting your filters"
        rowClassName={row => !row.fa_id && !row.ed_id ? 'border-l-2 border-amber-500/60' : ''}
      />
    </div>
  )
}
