'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Globe, CheckCircle2, Phone } from 'lucide-react'
import { api } from '@/lib/api'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

/* ─── Types ──────────────────────────────────────────────────────────── */

interface Driver {
  id: number
  name: string
  phone: string
  language: string | null
}

type Lang = 'en' | 'ar' | 'am'

const LANG_OPTIONS: { code: Lang; flag: string; label: string }[] = [
  { code: 'en', flag: '🇺🇸', label: 'EN' },
  { code: 'ar', flag: '🇸🇦', label: 'AR' },
  { code: 'am', flag: '🇪🇹', label: 'AM' },
]

/* ─── Language Badge ──────────────────────────────────────────────────── */

function LangBadge({ lang }: { lang: string | null }) {
  if (!lang) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs dark:bg-white/5 bg-gray-100 dark:text-white/30 text-gray-400 border dark:border-white/10 border-gray-200">
        unset
      </span>
    )
  }
  const opt = LANG_OPTIONS.find(o => o.code === lang)
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-[#667eea]/10 text-[#667eea] border border-[#667eea]/30">
      {opt?.flag} {opt?.label ?? lang.toUpperCase()}
    </span>
  )
}

/* ─── Driver Row ──────────────────────────────────────────────────────── */

function DriverRow({
  driver,
  onLanguageSet,
}: {
  driver: Driver
  onLanguageSet: (id: number, lang: Lang) => void
}) {
  const [saving, setSaving] = useState<Lang | null>(null)
  const [justSaved, setJustSaved] = useState<Lang | null>(null)

  async function setLang(lang: Lang) {
    if (saving || driver.language === lang) return
    setSaving(lang)
    try {
      await api.patch(`/api/data/people/${driver.id}/language`, { language: lang })
      onLanguageSet(driver.id, lang)
      setJustSaved(lang)
      setTimeout(() => setJustSaved(null), 1800)
    } catch {
      // silently fail — state stays as-is
    } finally {
      setSaving(null)
    }
  }

  const initials = driver.name
    .split(' ')
    .map(w => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-center justify-between gap-3 px-4 py-3 rounded-2xl border dark:border-white/8 border-gray-200 dark:bg-white/[0.02] bg-white hover:dark:bg-white/[0.04] hover:bg-gray-50 transition-all"
    >
      {/* Avatar + info */}
      <div className="flex items-center gap-3 min-w-0">
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
          style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
        >
          {initials || '?'}
        </div>
        <div className="min-w-0">
          <p className="text-sm font-medium dark:text-white text-gray-900 truncate">{driver.name}</p>
          {driver.phone ? (
            <p className="text-xs dark:text-white/40 text-gray-500 flex items-center gap-1 truncate">
              <Phone className="w-3 h-3 flex-shrink-0" />
              {driver.phone}
            </p>
          ) : (
            <p className="text-xs dark:text-white/25 text-gray-400 italic">No phone</p>
          )}
        </div>
      </div>

      {/* Right: current badge + lang buttons */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <LangBadge lang={driver.language} />

        <div className="flex items-center gap-1">
          {LANG_OPTIONS.map(opt => {
            const isActive = driver.language === opt.code
            const isSaving = saving === opt.code
            const isSaved = justSaved === opt.code

            return (
              <motion.button
                key={opt.code}
                onClick={() => setLang(opt.code)}
                disabled={!!saving}
                whileTap={{ scale: 0.92 }}
                className={[
                  'flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-medium border transition-all cursor-pointer disabled:cursor-not-allowed',
                  isActive
                    ? 'bg-[#667eea] text-white border-[#667eea] shadow-sm shadow-[#667eea]/30'
                    : 'dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-500 dark:border-white/10 border-gray-200 dark:hover:bg-white/10 hover:bg-gray-200',
                ].join(' ')}
              >
                {isSaving ? (
                  <span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
                ) : isSaved ? (
                  <CheckCircle2 className="w-3 h-3" />
                ) : (
                  <span>{opt.flag}</span>
                )}
                {opt.label}
              </motion.button>
            )
          })}
        </div>
      </div>
    </motion.div>
  )
}

/* ─── Page ────────────────────────────────────────────────────────────── */

export default function LanguageSettingsPage() {
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')

  useEffect(() => {
    api
      .get<Driver[]>('/api/data/people')
      .then(people => {
        // api/data/people returns id, name, phone, language
        setDrivers(people)
      })
      .catch(e => setError(e.message || 'Failed to load drivers'))
      .finally(() => setLoading(false))
  }, [])

  const handleLanguageSet = useCallback((id: number, lang: Lang) => {
    setDrivers(prev =>
      prev.map(d => (d.id === id ? { ...d, language: lang } : d))
    )
  }, [])

  const filtered = drivers.filter(d => {
    if (!query) return true
    const q = query.toLowerCase()
    return d.name.toLowerCase().includes(q) || (d.phone || '').includes(q)
  })

  const taggedCount = drivers.filter(d => d.language).length
  const totalCount = drivers.length

  return (
    <div className="min-h-screen dark:bg-[#0a0f1a] bg-gray-50 pt-20 pb-24 px-4">
      <div className="max-w-2xl mx-auto">

        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-6"
        >
          <div className="flex items-center gap-3 mb-1">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-[#667eea]/15">
              <Globe className="w-4.5 h-4.5 text-[#667eea]" />
            </div>
            <h1 className="text-xl font-bold dark:text-white text-gray-900">Driver Language Settings</h1>
          </div>
          <p className="text-sm dark:text-white/50 text-gray-500 pl-12">
            Set each driver's preferred language for automated calls and SMS
          </p>
        </motion.div>

        {/* Stats bar */}
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="flex items-center justify-between mb-4 px-4 py-2.5 rounded-xl dark:bg-white/5 bg-white border dark:border-white/8 border-gray-200"
        >
          <span className="text-sm dark:text-white/60 text-gray-500">
            <span className="font-semibold dark:text-white text-gray-900">{taggedCount}</span>
            {' '}of {totalCount} tagged
          </span>
          <div className="flex items-center gap-3">
            {LANG_OPTIONS.map(opt => {
              const count = drivers.filter(d => d.language === opt.code).length
              return (
                <span key={opt.code} className="text-xs dark:text-white/50 text-gray-500">
                  {opt.flag} {opt.label}: <span className="font-medium dark:text-white text-gray-900">{count}</span>
                </span>
              )
            })}
          </div>
        </motion.div>

        {/* Search */}
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.08 }}
          className="relative mb-4"
        >
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search by name or phone…"
            className="w-full pl-9 pr-4 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 placeholder-gray-400 dark:placeholder-white/30 focus:outline-none focus:border-[#667eea]/60 transition-all"
          />
        </motion.div>

        {/* Content */}
        {loading ? (
          <div className="flex justify-center py-20"><LoadingSpinner /></div>
        ) : error ? (
          <div className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-16 dark:text-white/30 text-gray-400 text-sm">No drivers match your search</div>
        ) : (
          <motion.div className="space-y-2">
            <AnimatePresence>
              {filtered.map((driver, i) => (
                <motion.div
                  key={driver.id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.012 }}
                >
                  <DriverRow driver={driver} onLanguageSet={handleLanguageSet} />
                </motion.div>
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </div>
    </div>
  )
}
