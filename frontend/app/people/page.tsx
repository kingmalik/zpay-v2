'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Users, Plus, Pencil, X, Car, ClipboardList, Phone, Mail, Hash, AlertTriangle } from 'lucide-react'
import { api } from '@/lib/api'
import { formatDate } from '@/lib/utils'
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
  status?: 'active' | 'dormant' | 'inactive'
  onboarding_id?: number | null
  sex?: 'M' | 'F' | null
}

/* ─── Avatar ────────────────────────────────────────────────────────── */
const AVATAR_COLORS = [
  ['#667eea', '#764ba2'],
  ['#06b6d4', '#0e7490'],
  ['#10b981', '#059669'],
  ['#f59e0b', '#d97706'],
  ['#ef4444', '#dc2626'],
  ['#8b5cf6', '#7c3aed'],
  ['#ec4899', '#db2777'],
  ['#14b8a6', '#0d9488'],
]
function nameHash(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return h % AVATAR_COLORS.length
}
function getAvatarGradient(name: string): string {
  const [from, to] = AVATAR_COLORS[nameHash(name)]
  return `linear-gradient(135deg, ${from}, ${to})`
}
function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return parts[0][0]?.toUpperCase() || '?'
  return ((parts[0][0] || '') + (parts[parts.length - 1][0] || '')).toUpperCase()
}

/* ─── Missing-data chips ────────────────────────────────────────────── */
interface MissingField {
  key: string
  label: string
  tone: 'red' | 'amber'
}

function getMissingFields(driver: Driver): MissingField[] {
  const missing: MissingField[] = []
  if (!driver.phone) missing.push({ key: 'phone', label: 'phone', tone: 'red' })
  if (!driver.home_address) missing.push({ key: 'addr', label: 'address', tone: 'red' })
  if (!driver.pay_code) missing.push({ key: 'pay', label: 'pay code', tone: 'red' })
  if (!driver.email) missing.push({ key: 'email', label: 'email', tone: 'amber' })
  if (!driver.vehicle_make) missing.push({ key: 'vehicle', label: 'vehicle', tone: 'amber' })
  return missing
}

function MissingChips({ fields }: { fields: MissingField[] }) {
  if (fields.length === 0) return null
  const hasRed = fields.some(f => f.tone === 'red')
  return (
    <div className="flex items-center gap-1 flex-wrap">
      <AlertTriangle className={`w-3 h-3 flex-shrink-0 ${hasRed ? 'text-red-400' : 'text-amber-400'}`} />
      {fields.map(f => (
        <span
          key={f.key}
          className={
            f.tone === 'red'
              ? 'text-[10px] px-1.5 py-0.5 rounded-md font-medium bg-red-500/10 text-red-400 border border-red-500/25'
              : 'text-[10px] px-1.5 py-0.5 rounded-md font-medium bg-amber-500/10 text-amber-500 border border-amber-500/25'
          }
        >
          no {f.label}
        </span>
      ))}
    </div>
  )
}

/* ─── Driver Card ────────────────────────────────────────────────────── */
function DriverCard({ driver, onEdit, onToggleActive }: {
  driver: Driver
  onEdit: (d: Driver) => void
  onToggleActive: (d: Driver) => void
}) {
  const c = (driver.company || '').toLowerCase()
  const isFa = c.includes('first')
  const isEd = c.includes('ever')
  const isBoth = c === 'both'
  const dStatus = driver.status || (driver.active !== false ? 'active' : 'inactive')
  const isActive = dStatus === 'active'
  const isOnboarding = driver.onboarding_id != null
  const missing = isActive ? getMissingFields(driver) : []

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl dark:bg-white/[0.04] bg-white border dark:border-white/[0.07] border-gray-200 p-4 flex flex-col gap-3 hover:dark:bg-white/[0.07] hover:bg-gray-50 transition-colors"
    >
      {/* Top: avatar + name + company */}
      <div className="flex items-start gap-3">
        <div
          className="w-10 h-10 rounded-full flex items-center justify-center text-white text-sm font-bold flex-shrink-0 select-none"
          style={{ background: driver.name ? getAvatarGradient(driver.name) : 'linear-gradient(135deg, #667eea, #06b6d4)' }}
        >
          {driver.name ? getInitials(driver.name) : '?'}
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-semibold dark:text-white text-gray-900 text-sm leading-tight">{driver.name || '—'}</p>
          <div className="flex items-center gap-1 mt-1 flex-wrap">
            {(isFa || isBoth) && <Badge variant="fa">FA</Badge>}
            {(isEd || isBoth) && <Badge variant="ed">ED</Badge>}
            {!isFa && !isEd && !isBoth && (
              <span className="text-[10px] dark:text-white/30 text-gray-400">No company</span>
            )}
            {driver.sex === 'F' && (
              <span className="px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-pink-500/10 text-pink-500 border border-pink-500/20">♀</span>
            )}
            {driver.sex === 'M' && (
              <span className="px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-blue-500/10 text-blue-500 border border-blue-500/20">♂</span>
            )}
          </div>
        </div>
        <button
          onClick={() => onEdit(driver)}
          className="p-1.5 rounded-lg dark:hover:bg-white/10 hover:bg-gray-100 transition-colors cursor-pointer flex-shrink-0"
        >
          <Pencil className="w-3.5 h-3.5 dark:text-white/30 text-gray-400" />
        </button>
      </div>

      {/* Missing-data alerts (active drivers only) */}
      {missing.length > 0 && <MissingChips fields={missing} />}

      {/* Contact row */}
      {(driver.phone || driver.email) && (
        <div className="flex flex-col gap-1">
          {driver.phone && (
            <div className="flex items-center gap-1.5 text-xs dark:text-white/50 text-gray-500">
              <Phone className="w-3 h-3 flex-shrink-0" />
              <span className="truncate">{driver.phone}</span>
            </div>
          )}
          {driver.email && (
            <div className="flex items-center gap-1.5 text-xs dark:text-white/50 text-gray-500">
              <Mail className="w-3 h-3 flex-shrink-0" />
              <span className="truncate">{driver.email}</span>
            </div>
          )}
        </div>
      )}

      {/* Stats row */}
      <div className="flex items-center gap-3 pt-1 border-t dark:border-white/[0.06] border-gray-100">
        <div className="flex items-center gap-1.5 text-xs">
          <Car className="w-3 h-3 dark:text-white/30 text-gray-400" />
          <span className="font-semibold dark:text-white/80 text-gray-700">{driver.rides ?? 0}</span>
          <span className="dark:text-white/30 text-gray-400">rides</span>
        </div>
        {driver.pay_code && (
          <div className="flex items-center gap-1.5 text-xs">
            <Hash className="w-3 h-3 dark:text-white/30 text-gray-400" />
            <span className="font-mono dark:text-white/70 text-gray-600">{driver.pay_code}</span>
          </div>
        )}
        {driver.last_active && (
          <div className="ml-auto text-[10px] dark:text-white/30 text-gray-400">{formatDate(driver.last_active)}</div>
        )}
      </div>

      {/* Status row */}
      <div className="flex items-center justify-between">
        {isOnboarding ? (
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-500 border border-amber-500/25">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
            Onboarding
          </span>
        ) : (
          <button onClick={() => onToggleActive(driver)} className="cursor-pointer hover:opacity-80 transition-opacity">
            <Badge variant={dStatus === 'active' ? 'active' : dStatus === 'dormant' ? 'warning' : 'inactive'} dot>
              {dStatus === 'active' ? 'Active' : dStatus === 'dormant' ? 'Dormant' : 'Inactive'}
            </Badge>
          </button>
        )}
        {driver.onboarding_id != null && (
          <Link
            href={`/onboarding/${driver.onboarding_id}`}
            className="text-[10px] text-[#667eea] hover:text-[#7c93f0] transition-colors"
          >
            View progress →
          </Link>
        )}
        {driver.notes && (
          <span className="text-[10px] dark:text-white/30 text-gray-400 truncate max-w-[120px]" title={driver.notes}>
            {driver.notes}
          </span>
        )}
      </div>
    </motion.div>
  )
}

/* ─── Driver Modal ───────────────────────────────────────────────────── */
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
    if (isNew && !form.full_name.trim()) { setError('Name is required'); return }
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
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold dark:text-white text-gray-900">
              {isNew ? 'Add New Driver' : `Edit — ${driver?.name}`}
            </h2>
            <button onClick={onClose} className="p-1.5 rounded-lg dark:hover:bg-white/10 hover:bg-gray-100 transition-colors cursor-pointer">
              <X className="w-4 h-4 dark:text-white/50 text-gray-500" />
            </button>
          </div>

          {error && <div className="mb-4 px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">{error}</div>}

          <p className={sectionClass}>Basic Info</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
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

          <p className={sectionClass}>
            <span className="flex items-center gap-1.5"><Car className="w-3.5 h-3.5" /> Vehicle</span>
          </p>
          <div className="grid grid-cols-3 gap-3">
            <div><label className={labelClass}>Make</label><input value={form.vehicle_make} onChange={e => set('vehicle_make', e.target.value)} placeholder="Toyota" className={inputClass} /></div>
            <div><label className={labelClass}>Model</label><input value={form.vehicle_model} onChange={e => set('vehicle_model', e.target.value)} placeholder="Camry" className={inputClass} /></div>
            <div><label className={labelClass}>Year</label><input value={form.vehicle_year} onChange={e => set('vehicle_year', e.target.value)} placeholder="2024" className={inputClass} /></div>
            <div><label className={labelClass}>Plate</label><input value={form.vehicle_plate} onChange={e => set('vehicle_plate', e.target.value)} placeholder="ABC1234" className={inputClass} /></div>
            <div><label className={labelClass}>Color</label><input value={form.vehicle_color} onChange={e => set('vehicle_color', e.target.value)} placeholder="Silver" className={inputClass} /></div>
          </div>

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
  const [activeFilter, setActiveFilter] = useState<'all' | 'active' | 'dormant' | 'inactive'>('active')
  const [sexFilter, setSexFilter] = useState<'all' | 'M' | 'F'>('all')
  const [showModal, setShowModal] = useState(false)
  const [editDriver, setEditDriver] = useState<Driver | null>(null)

  const fetchDrivers = useCallback(() => {
    api.get<Driver[]>('/api/data/people').then(setDrivers).catch(console.error).finally(() => setLoading(false))
  }, [])

  useEffect(() => { fetchDrivers() }, [fetchDrivers])

  function openEdit(driver: Driver) { setEditDriver(driver); setShowModal(true) }
  function openAdd() { setEditDriver(null); setShowModal(true) }

  async function toggleActive(driver: Driver) {
    try {
      const res = await api.post<{ ok: boolean; active: boolean }>(`/people/${driver.id}/toggle-active`, {})
      setDrivers(prev => prev.map(d => d.id === driver.id ? { ...d, active: res.active } : d))
    } catch { /* silent */ }
  }

  const filtered = drivers.filter(d => {
    const q = search.toLowerCase()
    const matchSearch = !q || (d.name?.toLowerCase().includes(q) || d.phone?.includes(q) || d.email?.toLowerCase().includes(q))
    const co = (d.company || '').toLowerCase()
    const matchCompany = company === 'all'
      || (company === 'fa' && (co.includes('first') || co === 'both'))
      || (company === 'ed' && (co.includes('ever') || co === 'both'))
    const dStatus = d.status || (d.active !== false ? 'active' : 'inactive')
    const matchActive = activeFilter === 'all' || dStatus === activeFilter
    const matchSex = sexFilter === 'all' || d.sex === sexFilter
    return matchSearch && matchCompany && matchActive && matchSex
  })

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div data-tour="people-table" className="max-w-7xl mx-auto space-y-5 py-6">
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
            <button key={v} onClick={() => setCompany(v)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${company === v ? 'bg-[#667eea] text-white' : 'dark:text-white/50 text-gray-500'}`}>
              {l}
            </button>
          ))}
        </div>
        <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
          {([
            ['active', 'Active', 'bg-emerald-500'],
            ['dormant', 'Dormant', 'bg-amber-500'],
            ['inactive', 'Inactive', 'bg-gray-500'],
            ['all', 'All', 'bg-[#667eea]'],
          ] as const).map(([v, l, bg]) => (
            <button key={v} onClick={() => setActiveFilter(v)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${activeFilter === v ? `${bg} text-white` : 'dark:text-white/50 text-gray-500'}`}>
              {l}
            </button>
          ))}
        </div>
        <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
          {([['all', 'All'], ['F', '♀ Female'], ['M', '♂ Male']] as const).map(([v, l]) => (
            <button key={v} onClick={() => setSexFilter(v)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                sexFilter === v
                  ? v === 'F' ? 'bg-pink-500 text-white'
                  : v === 'M' ? 'bg-blue-500 text-white'
                  : 'bg-[#667eea] text-white'
                  : 'dark:text-white/50 text-gray-500'
              }`}>
              {l}
            </button>
          ))}
        </div>
      </div>

      {/* Card Grid */}
      {filtered.length === 0 ? (
        <div className="rounded-2xl dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200 p-16 text-center">
          <Users className="w-8 h-8 dark:text-white/20 text-gray-300 mx-auto mb-3" />
          <p className="dark:text-white/50 text-gray-500 font-medium">No drivers found</p>
          <p className="text-sm dark:text-white/30 text-gray-400 mt-1">Try adjusting your filters</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {filtered.map((d, i) => (
            <motion.div key={d.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.02 }}>
              <DriverCard driver={d} onEdit={openEdit} onToggleActive={toggleActive} />
            </motion.div>
          ))}
        </div>
      )}

      {showModal && (
        <DriverModal
          driver={editDriver}
          onClose={() => { setShowModal(false); setEditDriver(null) }}
          onSave={fetchDrivers}
        />
      )}
    </div>
  )
}
