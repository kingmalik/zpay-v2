'use client'

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { Check, Loader2, School as SchoolIcon } from 'lucide-react'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Badge from '@/components/ui/Badge'
import { getSchools, patchSchool } from '../season/seasonApi'
import { apiErrorMessage } from '../season/utils'
import type { SchoolRow } from '../season/types'

function sortSchools(schools: SchoolRow[]): SchoolRow[] {
  return [...schools].sort((a, b) => {
    if (a.needs_address !== b.needs_address) return a.needs_address ? -1 : 1
    return a.display_name.localeCompare(b.display_name)
  })
}

interface RowState {
  address: string
  city: string
  district: string
}

function toRowState(s: SchoolRow): RowState {
  return { address: s.address || '', city: s.city || '', district: s.district || '' }
}

export default function SchoolsPage() {
  const [schools, setSchools] = useState<SchoolRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [edits, setEdits] = useState<Record<number, RowState>>({})
  const [savingId, setSavingId] = useState<number | null>(null)

  function load() {
    setLoading(true)
    getSchools()
      .then(rows => {
        const sorted = sortSchools(rows)
        setSchools(sorted)
        setEdits(Object.fromEntries(sorted.map(s => [s.school_id, toRowState(s)])))
        setError(null)
      })
      .catch(e => setError(apiErrorMessage(e, 'Failed to load schools')))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  function updateField(id: number, field: keyof RowState, value: string) {
    setEdits(prev => ({ ...prev, [id]: { ...prev[id], [field]: value } }))
  }

  function isDirty(s: SchoolRow): boolean {
    const e = edits[s.school_id]
    if (!e) return false
    return e.address !== (s.address || '') || e.city !== (s.city || '') || e.district !== (s.district || '')
  }

  async function save(s: SchoolRow) {
    const e = edits[s.school_id]
    if (!e) return
    setSavingId(s.school_id)
    try {
      const updated = await patchSchool(s.school_id, {
        address: e.address.trim() || null,
        city: e.city.trim() || null,
        district: e.district.trim() || null,
      })
      setSchools(prev => sortSchools(prev.map(row => (row.school_id === s.school_id ? updated : row))))
      setEdits(prev => ({ ...prev, [s.school_id]: toRowState(updated) }))
      toast.success(`${updated.display_name} saved`)
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Failed to save school'))
    } finally {
      setSavingId(null)
    }
  }

  if (loading) return <LoadingSpinner fullPage />

  if (error) {
    return (
      <div className="max-w-5xl mx-auto py-10">
        <div className="rounded-2xl p-6 bg-red-500/10 border border-red-500/20 text-center">
          <p className="text-red-400 font-medium">Failed to load schools</p>
          <p className="text-sm dark:text-white/40 text-gray-400 mt-1">{error}</p>
          <button onClick={load} className="mt-4 px-4 py-2 rounded-xl text-sm bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors">
            Retry
          </button>
        </div>
      </div>
    )
  }

  const needsAddressCount = schools.filter(s => s.needs_address).length

  return (
    <div className="max-w-5xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2.5">
          <SchoolIcon className="w-5 h-5 text-[#667eea]" />
          <div>
            <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">Schools</h1>
            <p className="text-sm dark:text-white/40 text-gray-500 mt-0.5">
              {schools.length} schools{needsAddressCount > 0 ? ` · ${needsAddressCount} need an address` : ''}
            </p>
          </div>
        </div>
      </div>

      <div className="rounded-2xl overflow-hidden dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b dark:border-white/8 border-gray-100">
                {['School', 'District', 'Address', 'City', 'Rides', ''].map((h, i) => (
                  <th key={i} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {schools.map((s, i) => {
                const e = edits[s.school_id] || toRowState(s)
                const dirty = isDirty(s)
                const saving = savingId === s.school_id
                return (
                  <motion.tr
                    key={s.school_id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: Math.min(i * 0.015, 0.3) }}
                    className={`border-b last:border-0 dark:border-white/5 border-gray-50 ${
                      s.needs_address ? 'dark:bg-amber-500/[0.04] bg-amber-50/40' : ''
                    }`}
                  >
                    <td className="px-4 py-2.5 dark:text-white/80 text-gray-700 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        {s.display_name}
                        {s.needs_address && <Badge variant="warning">needs address</Badge>}
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <input
                        type="text"
                        value={e.district}
                        onChange={ev => updateField(s.school_id, 'district', ev.target.value)}
                        placeholder="District"
                        className="w-32 px-2 py-1 rounded-lg text-xs dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                      />
                    </td>
                    <td className="px-4 py-2.5">
                      <input
                        type="text"
                        value={e.address}
                        onChange={ev => updateField(s.school_id, 'address', ev.target.value)}
                        placeholder="Street address, WA"
                        className="w-64 px-2 py-1 rounded-lg text-xs dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                      />
                    </td>
                    <td className="px-4 py-2.5">
                      <input
                        type="text"
                        value={e.city}
                        onChange={ev => updateField(s.school_id, 'city', ev.target.value)}
                        placeholder="City"
                        className="w-32 px-2 py-1 rounded-lg text-xs dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
                      />
                    </td>
                    <td className="px-4 py-2.5 dark:text-white/60 text-gray-600 tabular-nums">{s.ride_count}</td>
                    <td className="px-4 py-2.5">
                      <button
                        onClick={() => save(s)}
                        disabled={!dirty || saving}
                        className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium disabled:opacity-30 disabled:cursor-not-allowed dark:bg-emerald-500/10 bg-emerald-50 text-emerald-500 dark:hover:bg-emerald-500/20 hover:bg-emerald-100 border dark:border-emerald-500/20 border-emerald-200 transition-colors"
                      >
                        {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                        Save
                      </button>
                    </td>
                  </motion.tr>
                )
              })}
              {schools.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-sm dark:text-white/30 text-gray-400">No schools yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
