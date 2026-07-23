'use client'

import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { MapPin, X, CheckCircle2 } from 'lucide-react'
import { api } from '@/lib/api'
import { HomeGapDriver, HomeGapsResponse } from './types'

// §2.5 extraction rule: ONE question at a time, never a form wall.
// Slim dismissible strip — asks about the single most-active gap driver,
// then advances to the next one on save. Dismiss hides it for the session only.
export default function HomeGapNag() {
  const [drivers, setDrivers] = useState<HomeGapDriver[]>([])
  const [index, setIndex] = useState(0)
  const [area, setArea] = useState('')
  const [zip, setZip] = useState('')
  const [saving, setSaving] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    api.get<HomeGapsResponse>('/api/data/assignment/home-gaps')
      .then(res => setDrivers(res.drivers ?? []))
      .catch(() => setDrivers([]))
      .finally(() => setLoaded(true))
  }, [])

  const current = drivers[index]

  const save = useCallback(async () => {
    if (!current || !area.trim()) return
    setSaving(true)
    try {
      await api.patch(`/api/data/people/${current.person_id}/home`, {
        home_area: area.trim(),
        home_zip: zip.trim() || undefined,
      })
      setJustSaved(true)
      setTimeout(() => {
        setJustSaved(false)
        setArea('')
        setZip('')
        setIndex(i => i + 1)
      }, 1100)
    } catch {
      // leave the input up — she can retry
    } finally {
      setSaving(false)
    }
  }, [current, area, zip])

  if (!loaded || dismissed || !current) return null

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        className="flex items-center gap-3 flex-wrap px-4 py-2.5 rounded-xl border dark:bg-white/[0.03] bg-blue-50/60 dark:border-white/8 border-blue-100"
      >
        <MapPin className="w-4 h-4 dark:text-white/35 text-blue-400 shrink-0" />

        {justSaved ? (
          <span className="flex items-center gap-1.5 text-sm dark:text-emerald-400 text-emerald-600 font-medium">
            <CheckCircle2 className="w-3.5 h-3.5" />
            Saved — one less unknown
          </span>
        ) : (
          <>
            <span className="text-sm dark:text-white/70 text-gray-700">
              Where does <span className="font-semibold">{current.name}</span> live? (rough area is fine)
            </span>
            <input
              type="text"
              value={area}
              onChange={e => setArea(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && save()}
              placeholder="e.g. Kent / south Seattle"
              autoFocus
              className="px-2.5 py-1 rounded-lg text-sm w-44 dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 focus:outline-none focus:border-[#667eea]/60"
            />
            <input
              type="text"
              value={zip}
              onChange={e => setZip(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && save()}
              placeholder="zip (optional)"
              className="px-2.5 py-1 rounded-lg text-sm w-28 dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 focus:outline-none focus:border-[#667eea]/60"
            />
            <button
              onClick={save}
              disabled={saving || !area.trim()}
              className="px-3 py-1 rounded-lg text-sm font-semibold text-white disabled:opacity-40 cursor-pointer"
              style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
            >
              Save
            </button>
          </>
        )}

        <button
          onClick={() => setDismissed(true)}
          className="ml-auto p-1 rounded-lg dark:text-white/25 text-gray-300 dark:hover:text-white/60 hover:text-gray-500 cursor-pointer"
          title="Dismiss for this session"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </motion.div>
    </AnimatePresence>
  )
}
