'use client'

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { Search, Sliders } from 'lucide-react'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { REQUIREMENT_META } from '../../season/RequirementIcons'
import { getCapabilities, patchCapabilities } from '../../season/seasonApi'
import { apiErrorMessage } from '../../season/utils'
import { CAPABILITY_FIELDS, CAPABILITY_LABELS, REQUIRES_TO_CAPABILITY } from '../../season/types'
import type { CapabilitiesFlags, DriverCapabilityRow } from '../../season/types'

const EMPTY_CAPS: CapabilitiesFlags = {
  car_seat: false, booster: false, harness: false, monitor_ok: false, wheelchair_vehicle: false,
}

// Icons for each capability column, reusing the same requirement icon set (mapped through
// REQUIRES_TO_CAPABILITY so the icon a driver sees here matches the icon shown on ride cards).
const CAP_ICON: Record<keyof CapabilitiesFlags, React.ReactNode> = Object.fromEntries(
  REQUIREMENT_META.map(r => [REQUIRES_TO_CAPABILITY[r.key], r.icon])
) as Record<keyof CapabilitiesFlags, React.ReactNode>

export default function DriverCapabilitiesPage() {
  const [drivers, setDrivers] = useState<DriverCapabilityRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [savingKey, setSavingKey] = useState<string | null>(null)

  function load() {
    setLoading(true)
    getCapabilities()
      .then(rows => { setDrivers(rows); setError(null) })
      .catch(e => setError(apiErrorMessage(e, 'Failed to load driver capabilities')))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  async function toggle(driver: DriverCapabilityRow, field: keyof CapabilitiesFlags) {
    const key = `${driver.person_id}:${field}`
    const before = driver.capabilities || EMPTY_CAPS
    const next: CapabilitiesFlags = { ...before, [field]: !before[field] }

    setSavingKey(key)
    setDrivers(prev => prev.map(d => (d.person_id === driver.person_id ? { ...d, capabilities: next } : d)))

    try {
      const saved = await patchCapabilities(driver.person_id, next)
      setDrivers(prev => prev.map(d => (d.person_id === driver.person_id ? saved : d)))
    } catch (e) {
      // revert on failure
      setDrivers(prev => prev.map(d => (d.person_id === driver.person_id ? { ...d, capabilities: before } : d)))
      toast.error(apiErrorMessage(e, `Failed to update ${CAPABILITY_LABELS[field]} for ${driver.name}`))
    } finally {
      setSavingKey(null)
    }
  }

  const filtered = drivers.filter(d => !query || d.name.toLowerCase().includes(query.toLowerCase()))

  return (
    <div className="max-w-4xl mx-auto space-y-5 py-6">
      <div className="flex items-center gap-2.5">
        <Sliders className="w-5 h-5 text-[#667eea]" />
        <div>
          <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">Driver Capabilities</h1>
          <p className="text-sm dark:text-white/40 text-gray-500 mt-0.5">
            Which drivers run a wheelchair vehicle — the one thing that limits who can take a ride.
            Car seats, boosters, and harnesses get handed out by Maz; monitors come from FirstAlt.
          </p>
        </div>
      </div>

      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search drivers…"
          className="w-full pl-9 pr-4 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 focus:outline-none focus:border-[#667eea]/60"
        />
      </div>

      {loading ? (
        <LoadingSpinner fullPage />
      ) : error ? (
        <div className="rounded-2xl p-6 bg-red-500/10 border border-red-500/20 text-center">
          <p className="text-red-400 font-medium">{error}</p>
          <button onClick={load} className="mt-4 px-4 py-2 rounded-xl text-sm bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors">
            Retry
          </button>
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b dark:border-white/8 border-gray-100">
                  <th className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">Driver</th>
                  {CAPABILITY_FIELDS.map(f => (
                    <th key={f} className="px-3 py-3 text-center text-xs font-medium dark:text-white/40 text-gray-400">
                      {CAPABILITY_LABELS[f]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((driver, i) => {
                  const caps = driver.capabilities || EMPTY_CAPS
                  return (
                    <motion.tr
                      key={driver.person_id}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ delay: Math.min(i * 0.015, 0.3) }}
                      className="border-b last:border-0 dark:border-white/5 border-gray-50"
                    >
                      <td className="px-4 py-2.5 dark:text-white/80 text-gray-700 whitespace-nowrap">{driver.name}</td>
                      {CAPABILITY_FIELDS.map(field => {
                        const active = !!caps[field]
                        const isSaving = savingKey === `${driver.person_id}:${field}`
                        return (
                          <td key={field} className="px-3 py-2.5 text-center">
                            <button
                              onClick={() => toggle(driver, field)}
                              disabled={isSaving}
                              title={CAPABILITY_LABELS[field]}
                              className={`inline-flex items-center justify-center w-8 h-8 rounded-lg border transition-all cursor-pointer disabled:cursor-wait ${
                                active
                                  ? 'bg-[#667eea] text-white border-[#667eea] shadow-sm shadow-[#667eea]/25'
                                  : 'dark:bg-white/5 bg-gray-100 dark:text-white/30 text-gray-400 dark:border-white/10 border-gray-200 dark:hover:bg-white/10 hover:bg-gray-200'
                              } ${isSaving ? 'opacity-50' : ''}`}
                            >
                              {CAP_ICON[field]}
                            </button>
                          </td>
                        )
                      })}
                    </motion.tr>
                  )
                })}
                {filtered.length === 0 && (
                  <tr><td colSpan={CAPABILITY_FIELDS.length + 1} className="px-4 py-10 text-center text-sm dark:text-white/30 text-gray-400">No drivers match</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
