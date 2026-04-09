'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Users, Plus, Pencil, X, Car, ClipboardList } from 'lucide-react'
import { api } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import DataTable, { Column } from '@/components/ui/DataTable'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Link from 'next/link'

interface Driver {
  id: string | number
  name?: string
  company?: string
  fa_id?: string | number
  ed_id?: string | number
  phone?: string
  email?: string
  pay_code?: string
  notes?: string
  rides?: number
  last_active?: string
  home_address?: string
  vehicle_make?: string
  vehicle_model?: string
  vehicle_year?: number
  vehicle_plate?: string
  vehicle_color?: string
  active?: boolean
}

/* ─── Inline Note Edit ──────────────────────────────────────────────── */
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

/* ─── Driver Modal (Edit + Add New) ─────────────────────────────────── */
function DriverModal({ driver, onClose, onSave }: { driver: Driver | null; onClose: () => void; onSave: () => void }) {
  const isNew = !driver
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const [form, setForm] = useState({
    full_name: driver?.name || '',
    phone: driver?.phone || '',
    email: driver?.email || '',
    paycheck_code: driver?.pay_code || '',
    firstalt_driver_id: driver?.fa_id || '',
    everdriven_driver_id: driver?.ed_id || '',
    notes: driver?.notes || '',
    home_address: driver?.home_address || '',
    vehicle_make: driver?.vehicle_make || '',
    vehicle_model: driver?.vehicle_model || '',
    vehicle_year: driver?.vehicle_year || '',
    vehicle_plate: driver?.vehicle_plate || '',
    vehicle_color: driver?.vehicle_color || '',
    active: driver?.active !== false,
  })

  function set(key: string, val: string | boolean) {
    setForm(prev => ({ ...prev, [key]: val }))
  }

  async function handleSave() {
    if (isNew && !form.full_name.trim()) {
      setError('Name is required')
      return
    }
    setSaving(true)
    setError('')
    try {
      if (isNew) {
        await api.post('/people/create', form)
      } else {
        await api.patch(`/people/${driver!.id}/update-json`, form)
      }
      onSave()
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const inputClass = "w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 placeholder-gray-400 dark:placeholder-white/30 focus:outline-none focus:border-[#667eea]/60 transition-all"
  const labelClass = "text-xs font-medium dark:text-white/50 text-gray-500 mb-1 block"
  const sectionClass = "text-xs font-semibold uppercase tracking-wide dark:text-white/40 text-gray-400 mb-3 mt-5 first:mt-0"

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95 }}
          className="dark:bg-[#0f1729] bg-white rounded-2xl border dark:border-white/10 border-gray-200 p-6 max-w-2xl w-full max-h-[85vh] overflow-y-auto"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold dark:text-white text-gray-900">
              {isNew ? 'Add New Driver' : `Edit — ${driver?.name}`}
            </h2>
            <button onClick={onClose} className="p-1.5 rounded-lg dark:hover:bg-white/10 hover:bg-gray-100 transition-colors cursor-pointer">
              <X className="w-4 h-4 dark:text-white/50 text-gray-500" />
            </button>
          </div>

          {error && (
            <div className="mb-4 px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">{error}</div>
          )}

          {/* Basic Info */}
          <p className={sectionClass}>Basic Info</p>
          <div className="grid grid-cols-2 gap-3">
            <div className={isNew ? 'col-span-2' : 'col-span-2'}>
              <label className={labelClass}>Full Name {isNew && '*'}</label>
              <input value={form.full_name} onChange={e => set('full_name', e.target.value)} placeholder="Full name" className={inputClass} disabled={!isNew} />
            </div>
            <div>
              <label className={labelClass}>Phone</label>
              <input value={form.phone} onChange={e => set('phone', e.target.value)} placeholder="(555) 123-4567" className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Email</label>
              <input value={form.email} onChange={e => set('email', e.target.value)} placeholder="email@example.com" className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Pay Code</label>
              <input value={form.paycheck_code} onChange={e => set('paycheck_code', e.target.value)} placeholder="Paychex worker ID" className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Home Address</label>
              <input value={form.home_address} onChange={e => set('home_address', e.target.value)} placeholder="123 Main St" className={inputClass} />
            </div>
          </div>

          {/* IDs */}
          <p className={sectionClass}>Partner IDs</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelClass}>FirstAlt ID</label>
              <input value={form.firstalt_driver_id} onChange={e => set('firstalt_driver_id', e.target.value)} placeholder="FA driver ID" className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>EverDriven MDD</label>
              <input value={form.everdriven_driver_id} onChange={e => set('everdriven_driver_id', e.target.value)} placeholder="ED driver ID" className={inputClass} />
            </div>
          </div>

          {/* Vehicle */}
          <p className={sectionClass}>
            <span className="flex items-center gap-1.5"><Car className="w-3.5 h-3.5" /> Vehicle</span>
          </p>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className={labelClass}>Make</label>
              <input value={form.vehicle_make} onChange={e => set('vehicle_make', e.target.value)} placeholder="Toyota" className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Model</label>
              <input value={form.vehicle_model} onChange={e => set('vehicle_model', e.target.value)} placeholder="Camry" className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Year</label>
              <input value={form.vehicle_year} onChange={e => set('vehicle_year', e.target.value)} placeholder="2024" className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Plate</label>
              <input value={form.vehicle_plate} onChange={e => set('vehicle_plate', e.target.value)} placeholder="ABC1234" className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Color</label>
              <input value={form.vehicle_color} onChange={e => set('vehicle_color', e.target.value)} placeholder="Silver" className={inputClass} />
            </div>
          </div>

          {/* Notes + Active */}
          <p className={sectionClass}>Other</p>
          <div className="space-y-3">
            <div>
              <label className={labelClass}>Notes</label>
              <textarea value={form.notes} onChange={e => set('notes', e.target.value)} rows={2} placeholder="Internal notes..." className={inputClass + ' resize-none'} />
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={form.active as boolean} onChange={e => set('active', e.target.checked)} className="rounded accent-[#667eea]" />
              <span className="text-sm dark:text-white/70 text-gray-600">Active driver</span>
            </label>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 mt-6 pt-4 border-t dark:border-white/8 border-gray-100">
            <button onClick={onClose} className="px-4 py-2 rounded-xl text-sm font-medium dark:text-white/60 text-gray-500 dark:hover:bg-white/5 hover:bg-gray-100 transition-all cursor-pointer">
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-5 py-2 rounded-xl text-sm font-medium text-white transition-all cursor-pointer disabled:opacity-60"
              style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
            >
              {saving ? 'Saving...' : isNew ? 'Add Driver' : 'Save Changes'}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}

/* ─── Main Page ─────────────────────────────────────────────────────── */
export default function PeoplePage() {
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [company, setCompany] = useState('all')
  const [activeFilter, setActiveFilter] = useState<'all' | 'active' | 'inactive'>('active')
  const [showModal, setShowModal] = useState(false)
  const [editDriver, setEditDriver] = useState<Driver | null>(null)

  const fetchDrivers = useCallback(() => {
    api.get<Driver[]>('/api/data/people').then(setDrivers).catch(console.error).finally(() => setLoading(false))
  }, [])

  useEffect(() => { fetchDrivers() }, [fetchDrivers])

  const updateNote = useCallback((id: string | number, note: string) => {
    setDrivers(prev => prev.map(d => d.id === id ? { ...d, notes: note } : d))
  }, [])

  function openEdit(driver: Driver) {
    setEditDriver(driver)
    setShowModal(true)
  }

  function openAdd() {
    setEditDriver(null)
    setShowModal(true)
  }

  function handleModalSave() {
    fetchDrivers()
  }

  async function toggleActive(driver: Driver) {
    try {
      const res = await api.post<{ ok: boolean; active: boolean }>(`/people/${driver.id}/toggle-active`, {})
      setDrivers(prev => prev.map(d => d.id === driver.id ? { ...d, active: res.active } : d))
    } catch {
      // silent fail — state unchanged
    }
  }

  const filtered = drivers.filter(d => {
    const q = search.toLowerCase()
    const matchSearch = !q || (d.name?.toLowerCase().includes(q) || d.phone?.includes(q) || d.email?.toLowerCase().includes(q))
    const co = (d.company || '').toLowerCase()
    const matchCompany = company === 'all'
      || (company === 'fa' && (co.includes('first') || co === 'both'))
      || (company === 'ed' && (co.includes('ever') || co === 'both'))
    const isActive = d.active !== false  // treat undefined as active
    const matchActive = activeFilter === 'all'
      || (activeFilter === 'active' && isActive)
      || (activeFilter === 'inactive' && !isActive)
    return matchSearch && matchCompany && matchActive
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
      render: (row: Driver) => {
        const c = (row.company || '').toLowerCase()
        if (c === 'both') return <div className="flex gap-1"><Badge variant="fa">FA</Badge><Badge variant="ed">ED</Badge></div>
        if (c.includes('first')) return <Badge variant="fa">FirstAlt</Badge>
        if (c.includes('ever')) return <Badge variant="ed">EverDriven</Badge>
        return <span className="text-xs dark:text-white/40 text-gray-400">{row.company || '—'}</span>
      },
    },
    ...(company !== 'ed' ? [{ key: 'fa_id', label: 'FA ID', mobileHide: true }] as Column<Driver>[] : []),
    ...(company !== 'fa' ? [{ key: 'ed_id', label: 'MDD', mobileHide: true }] as Column<Driver>[] : []),
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
    {
      key: 'active' as keyof Driver, label: 'Status',
      render: row => (
        <button
          onClick={() => toggleActive(row)}
          className="cursor-pointer transition-opacity hover:opacity-80"
          title={row.active !== false ? 'Click to mark inactive' : 'Click to mark active'}
        >
          <Badge variant={row.active !== false ? 'active' : 'inactive'} dot>
            {row.active !== false ? 'Active' : 'Inactive'}
          </Badge>
        </button>
      ),
    },
    {
      key: 'actions' as keyof Driver, label: '',
      render: row => (
        <button onClick={() => openEdit(row)} className="p-1.5 rounded-lg dark:hover:bg-white/10 hover:bg-gray-100 transition-colors cursor-pointer" title="Edit driver">
          <Pencil className="w-3.5 h-3.5 dark:text-white/40 text-gray-400" />
        </button>
      ),
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
        <div className="flex items-center gap-2">
          <Link
            href="/people/audit"
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium dark:bg-white/5 bg-gray-100 dark:text-white/70 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-200 border dark:border-white/10 border-gray-200 transition-all"
          >
            <ClipboardList className="w-4 h-4" />
            Audit
          </Link>
          <button
            onClick={openAdd}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all cursor-pointer"
            style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
          >
            <Plus className="w-4 h-4" />
            Add Driver
          </button>
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
        <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
          {(['all', 'active', 'inactive'] as const).map(v => (
            <button
              key={v}
              onClick={() => setActiveFilter(v)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all cursor-pointer capitalize ${activeFilter === v
                ? v === 'active' ? 'bg-emerald-500 text-white'
                  : v === 'inactive' ? 'bg-gray-500 text-white'
                  : 'bg-[#667eea] text-white'
                : 'dark:text-white/50 text-gray-500'
              }`}
            >
              {v === 'all' ? 'All' : v.charAt(0).toUpperCase() + v.slice(1)}
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

      {/* Modal */}
      {showModal && (
        <DriverModal
          driver={editDriver}
          onClose={() => { setShowModal(false); setEditDriver(null) }}
          onSave={handleModalSave}
        />
      )}
    </div>
  )
}
