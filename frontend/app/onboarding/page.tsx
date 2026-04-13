'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus, Search, X, Users, CheckCircle2, AlertCircle, Wrench,
  ChevronRight, Clock, FileText, ShieldCheck, FlaskConical,
  FileSignature, Upload, Building2, Copy, Check, Smartphone,
  GraduationCap, FolderOpen, Wallet, ScrollText, BookOpen,
} from 'lucide-react'
import { api } from '@/lib/api'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Link from 'next/link'

/* ─── Avatar color from name hash ───────────────────────────────────── */
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

/* ─── Types ──────────────────────────────────────────────────────────── */

interface OnboardingRecord {
  id: number
  person_id: number
  person_name: string
  person_email: string
  person_phone: string
  consent_status: string
  consent_envelope_id: string | null
  priority_email_status: string
  firstalt_invite_status: string
  brandon_email_status: string
  bgc_status: string
  drug_test_status: string
  contract_status: string
  contract_envelope_id: string | null
  files_status: string
  paychex_status: string
  training_status: string
  maz_training_status: string
  maz_contract_status: string
  notes: string | null
  started_at: string
  completed_at: string | null
  invite_token: string | null
  intake_submitted_at: string | null
}

interface Person {
  id: number | string
  name?: string
  email?: string
  phone?: string
}

/* ─── Step metadata ──────────────────────────────────────────────────── */

const STEPS = [
  { key: 'firstalt_invite_status', label: 'FirstAlt',      icon: Smartphone },
  { key: 'bgc_status',             label: 'BGC',           icon: ShieldCheck },
  { key: 'consent_status',         label: 'Consent',       icon: ScrollText },
  { key: 'drug_test_status',       label: 'Drug Test',     icon: FlaskConical },
  { key: 'training_status',        label: 'Training',      icon: GraduationCap },
  { key: 'files_status',           label: 'Docs',          icon: FolderOpen },
  { key: 'contract_status',        label: 'Contract',      icon: FileSignature },
  { key: 'maz_training_status',    label: 'Maz Train',     icon: BookOpen },
  { key: 'maz_contract_status',    label: 'Maz Contract',  icon: FileText },
  { key: 'paychex_status',         label: 'Paychex',       icon: Wallet },
] as const

/* ─── Next-action logic ──────────────────────────────────────────────── */

function getNextAction(r: OnboardingRecord): { label: string; type: 'action' | 'waiting' | 'manual' | 'done' } {
  if (r.completed_at) return { label: 'Complete', type: 'done' }
  const fa = r.firstalt_invite_status ?? r.priority_email_status
  if (fa === 'pending')                                      return { label: 'Send FirstAlt Invite',  type: 'action' }
  if (r.bgc_status === 'pending')                            return { label: 'Contact Brandon (BGC)', type: 'action' }
  if (r.bgc_status === 'manual')                             return { label: 'Review BGC',            type: 'manual' }
  if (r.consent_status === 'pending')                        return { label: 'Send Drug Test Consent', type: 'action' }
  if (r.consent_status === 'sent')                           return { label: 'Awaiting Consent Sig',  type: 'waiting' }
  if (r.drug_test_status === 'pending')                      return { label: 'Waiting on Drug Test',  type: 'waiting' }
  if (r.drug_test_status === 'manual')                       return { label: 'Review Drug Test',      type: 'manual' }
  if (r.training_status === 'pending')                       return { label: 'FirstAlt Training',     type: 'waiting' }
  if (r.files_status === 'pending')                          return { label: 'Upload Documents',      type: 'action' }
  if (r.contract_status === 'pending')                       return { label: 'Send Contract',         type: 'action' }
  if (r.contract_status === 'sent')                          return { label: 'Awaiting Contract Sig', type: 'waiting' }
  if ((r.maz_training_status ?? 'pending') === 'pending')    return { label: 'Maz Training',          type: 'action' }
  if ((r.maz_contract_status ?? 'pending') === 'pending')    return { label: 'Maz Contract',          type: 'action' }
  if (r.paychex_status === 'pending')                        return { label: 'Paychex + W-9',         type: 'action' }
  return { label: 'In Progress', type: 'waiting' }
}

/* ─── Overall status of a record ─────────────────────────────────────── */

function getOverallStatus(r: OnboardingRecord): 'Complete' | 'Blocked' | 'In Progress' {
  if (r.completed_at) return 'Complete'
  const next = getNextAction(r)
  if (next.type === 'action' || next.type === 'manual') return 'Blocked'
  return 'In Progress'
}

/* ─── Step Dots ──────────────────────────────────────────────────────── */

function StepDots({ record }: { record: OnboardingRecord }) {
  // determine which step index is the "active" one (first non-complete)
  const statuses = STEPS.map(s => {
    const val = record[s.key as keyof OnboardingRecord] as string | undefined
    return val ?? 'pending'
  })
  const activeIdx = statuses.findIndex(s => s !== 'complete' && s !== 'signed' && s !== 'skipped')

  return (
    <div className="flex items-center gap-1.5">
      {statuses.map((status, i) => {
        const isActive = i === activeIdx
        const isDone   = status === 'complete' || status === 'signed'
        const isSent   = status === 'sent'
        const isManual = status === 'manual'

        let dot: React.ReactNode

        if (isDone) {
          dot = <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 flex-shrink-0" title={STEPS[i].label} />
        } else if (isSent) {
          dot = <span className="w-2.5 h-2.5 rounded-full bg-amber-400 flex-shrink-0" title={STEPS[i].label} />
        } else if (isManual) {
          dot = <span className="w-2.5 h-2.5 rounded-full bg-gray-400 flex-shrink-0" title={STEPS[i].label} />
        } else if (isActive && status === 'pending') {
          dot = <span className="w-2.5 h-2.5 rounded-full bg-[#667eea] animate-pulse flex-shrink-0" title={STEPS[i].label} />
        } else {
          // not yet reached
          dot = <span className="w-2.5 h-2.5 rounded-full border-2 dark:border-white/20 border-gray-300 flex-shrink-0" title={STEPS[i].label} />
        }

        return (
          <div key={i} className="relative group">
            {dot}
            {/* tooltip */}
            <div className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
              <div className="px-1.5 py-0.5 rounded text-[10px] font-medium dark:bg-[#1e2d4d] bg-gray-700 text-white whitespace-nowrap shadow-lg">
                {STEPS[i].label}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ─── Next Action Button ─────────────────────────────────────────────── */

function NextActionChip({ record }: { record: OnboardingRecord }) {
  const next = getNextAction(record)

  const styles: Record<typeof next.type, string> = {
    action:  'bg-[#667eea]/10 text-[#667eea] border-[#667eea]/30 hover:bg-[#667eea]/20',
    waiting: 'dark:bg-amber-500/10 bg-amber-50 text-amber-500 border-amber-500/30',
    manual:  'dark:bg-gray-500/10 bg-gray-100 dark:text-gray-400 text-gray-500 border-gray-400/30',
    done:    'dark:bg-emerald-500/10 bg-emerald-50 text-emerald-500 border-emerald-500/30',
  }

  const icons: Record<typeof next.type, React.ReactNode> = {
    action:  <ChevronRight className="w-3 h-3" />,
    waiting: <Clock className="w-3 h-3" />,
    manual:  <Wrench className="w-3 h-3" />,
    done:    <CheckCircle2 className="w-3 h-3" />,
  }

  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium border transition-colors ${styles[next.type]}`}>
      {icons[next.type]}
      {next.label}
    </span>
  )
}

/* ─── Copy Link Button ───────────────────────────────────────────────── */

function CopyLinkButton({ token }: { token: string }) {
  const [copied, setCopied] = useState(false)

  function handleCopy(e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    const url = `${window.location.origin}/join/${token}`
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <button
      onClick={handleCopy}
      title="Copy driver invite link"
      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all cursor-pointer ${
        copied
          ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/30'
          : 'dark:bg-white/5 bg-gray-50 dark:text-white/40 text-gray-500 dark:border-white/10 border-gray-200 dark:hover:bg-white/10 hover:bg-gray-100'
      }`}
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? 'Copied!' : 'Link'}
    </button>
  )
}

/* ─── Summary Stat Card ───────────────────────────────────────────────── */

function SummaryCard({ label, value, icon: Icon, accent }: {
  label: string
  value: number
  icon: React.ElementType
  accent: string
}) {
  return (
    <div className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/5 bg-white p-4 flex items-center gap-3">
      <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${accent}`}>
        <Icon className="w-4.5 h-4.5" />
      </div>
      <div>
        <p className="text-xl font-bold dark:text-white text-gray-900 leading-none">{value}</p>
        <p className="text-xs dark:text-white/50 text-gray-500 mt-0.5">{label}</p>
      </div>
    </div>
  )
}

/* ─── Language options for AddModal ─────────────────────────────────── */
const ADD_LANG_OPTIONS = [
  { code: 'en', flag: '🇺🇸', label: 'English' },
  { code: 'ar', flag: '🇸🇦', label: 'Arabic' },
  { code: 'am', flag: '🇪🇹', label: 'Amharic' },
]

/* ─── Add Driver Modal ───────────────────────────────────────────────── */

function AddModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (name?: string) => void }) {
  const [query, setQuery]               = useState('')
  const [people, setPeople]             = useState<Person[]>([])
  const [loading, setLoading]           = useState(false)
  const [starting, setStarting]         = useState(false)
  const [error, setError]               = useState('')
  // Language-confirm step
  const [selected, setSelected]         = useState<Person | null>(null)
  const [selectedLang, setSelectedLang] = useState<string>('en')

  useEffect(() => {
    setLoading(true)
    api.get<Person[]>('/api/data/people')
      .then(setPeople)
      .catch(() => setError('Could not load drivers'))
      .finally(() => setLoading(false))
  }, [])

  const filtered = people.filter(p => {
    const q = query.toLowerCase()
    return !q || p.name?.toLowerCase().includes(q) || p.email?.toLowerCase().includes(q)
  })

  async function confirmAndStart() {
    if (!selected) return
    setStarting(true)
    setError('')
    try {
      await api.post('/api/data/onboarding/start', { person_id: selected.id })
      // Set language if not English (or set it regardless to be explicit)
      await api.patch(`/api/data/people/${selected.id}/language`, { language: selectedLang })
      onSuccess(selected.name)
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start onboarding')
      setStarting(false)
    }
  }

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
          transition={{ type: 'spring', damping: 25, stiffness: 400 }}
          className="dark:bg-[#0f1729] bg-white rounded-2xl border dark:border-white/10 border-gray-200 p-6 w-full max-w-md shadow-2xl"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div>
              {selected ? (
                <>
                  <h2 className="text-base font-bold dark:text-white text-gray-900">Confirm & Start</h2>
                  <p className="text-xs dark:text-white/40 text-gray-500 mt-0.5">Set preferred language for automated calls</p>
                </>
              ) : (
                <>
                  <h2 className="text-base font-bold dark:text-white text-gray-900">Add to Onboarding</h2>
                  <p className="text-xs dark:text-white/40 text-gray-500 mt-0.5">Select a driver to start the onboarding pipeline</p>
                </>
              )}
            </div>
            <button
              onClick={selected ? () => setSelected(null) : onClose}
              className="p-1.5 rounded-lg dark:hover:bg-white/10 hover:bg-gray-100 transition-colors cursor-pointer"
            >
              <X className="w-4 h-4 dark:text-white/50 text-gray-500" />
            </button>
          </div>

          {/* Error */}
          {error && (
            <div className="mb-3 px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-xs">{error}</div>
          )}

          {/* Step 2: Language confirm */}
          {selected ? (
            <div className="space-y-4">
              {/* Selected driver summary */}
              <div className="flex items-center gap-3 px-3 py-2.5 rounded-xl dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200">
                <div
                  className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                  style={{ background: selected.name ? getAvatarGradient(selected.name) : 'linear-gradient(135deg, #667eea, #06b6d4)' }}
                >
                  {selected.name ? getInitials(selected.name) : '?'}
                </div>
                <div>
                  <p className="text-sm font-medium dark:text-white text-gray-800">{selected.name}</p>
                  {selected.email && (
                    <p className="text-xs dark:text-white/40 text-gray-500">{selected.email}</p>
                  )}
                </div>
              </div>

              {/* Language selector */}
              <div>
                <p className="text-xs dark:text-white/50 text-gray-500 mb-2 font-medium">Call Language</p>
                <div className="grid grid-cols-3 gap-2">
                  {ADD_LANG_OPTIONS.map(opt => (
                    <button
                      key={opt.code}
                      onClick={() => setSelectedLang(opt.code)}
                      className={[
                        'flex flex-col items-center gap-1 px-3 py-2.5 rounded-xl text-xs font-medium border transition-all cursor-pointer',
                        selectedLang === opt.code
                          ? 'bg-[#667eea] text-white border-[#667eea] shadow-sm shadow-[#667eea]/30'
                          : 'dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-500 dark:border-white/10 border-gray-200 dark:hover:bg-white/10 hover:bg-gray-200',
                      ].join(' ')}
                    >
                      <span className="text-lg">{opt.flag}</span>
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Confirm */}
              <button
                onClick={confirmAndStart}
                disabled={starting}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium text-white disabled:opacity-50 cursor-pointer transition-all"
                style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
              >
                {starting && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
                Start Onboarding
              </button>
            </div>
          ) : (
            <>
              {/* Step 1: Search + select driver */}
              <div className="relative mb-3">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
                <input
                  autoFocus
                  type="text"
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  placeholder="Search by name or email…"
                  className="w-full pl-9 pr-4 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 placeholder-gray-400 dark:placeholder-white/30 focus:outline-none focus:border-[#667eea]/60 transition-all"
                />
              </div>

              <div className="max-h-72 overflow-y-auto space-y-1 -mx-1 px-1">
                {loading ? (
                  <div className="flex justify-center py-8"><LoadingSpinner /></div>
                ) : filtered.length === 0 ? (
                  <div className="text-center py-8 dark:text-white/30 text-gray-400 text-sm">No drivers found</div>
                ) : (
                  filtered.map(person => (
                    <button
                      key={person.id}
                      onClick={() => { setSelected(person); setSelectedLang('en') }}
                      className="w-full flex items-center justify-between gap-3 px-3 py-2.5 rounded-xl dark:hover:bg-white/5 hover:bg-gray-50 border border-transparent dark:hover:border-white/10 hover:border-gray-200 transition-all cursor-pointer group"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div
                          className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                          style={{ background: person.name ? getAvatarGradient(person.name) : 'linear-gradient(135deg, #667eea, #06b6d4)' }}
                        >
                          {person.name ? getInitials(person.name) : '?'}
                        </div>
                        <div className="min-w-0 text-left">
                          <p className="text-sm font-medium dark:text-white text-gray-800 truncate">{person.name}</p>
                          {person.email && (
                            <p className="text-xs dark:text-white/40 text-gray-500 truncate">{person.email}</p>
                          )}
                        </div>
                      </div>
                      <ChevronRight className="w-4 h-4 dark:text-white/20 text-gray-300 group-hover:dark:text-white/60 group-hover:text-gray-500 transition-colors flex-shrink-0" />
                    </button>
                  ))
                )}
              </div>
            </>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}

/* ─── Main Page ──────────────────────────────────────────────────────── */

export default function OnboardingPage() {
  const [records, setRecords]     = useState<OnboardingRecord[]>([])
  const [loading, setLoading]     = useState(true)
  const [search, setSearch]       = useState('')
  const [statusFilter, setStatus] = useState<'all' | 'In Progress' | 'Blocked' | 'Complete'>('all')
  const [showAdd, setShowAdd]     = useState(false)
  const [toast, setToast]         = useState<string | null>(null)

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3500)
  }

  const fetchRecords = useCallback(() => {
    api.get<OnboardingRecord[]>('/api/data/onboarding/')
      .then(data => {
        if (Array.isArray(data)) setRecords(data)
        else console.error('Unexpected onboarding response:', data)
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { fetchRecords() }, [fetchRecords])

  /* New intake count — submitted but FirstAlt invite not yet sent */
  const newIntakes = records.filter(r => r.intake_submitted_at && r.priority_email_status === 'pending' && !r.completed_at).length

  /* Summary counts */
  const total        = records.length
  const completedThisMonth = records.filter(r => {
    if (!r.completed_at) return false
    const d = new Date(r.completed_at)
    const now = new Date()
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()
  }).length
  const awaitingAction = records.filter(r => {
    const next = getNextAction(r)
    return next.type === 'action'
  }).length
  const manualPending = records.filter(r => {
    const next = getNextAction(r)
    return next.type === 'manual'
  }).length

  /* Filtered list */
  const filtered = records.filter(r => {
    const q = search.toLowerCase()
    const matchSearch = !q || r.person_name?.toLowerCase().includes(q) || r.person_email?.toLowerCase().includes(q)
    const overall = getOverallStatus(r)
    const matchStatus = statusFilter === 'all' || overall === statusFilter
    return matchSearch && matchStatus
  })

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">

      {/* ── Header ── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold dark:text-white text-gray-900">Onboarding</h1>
          <span className="px-2.5 py-1 rounded-full text-xs font-medium dark:bg-white/10 bg-gray-100 dark:text-white/60 text-gray-500">
            {total} in pipeline
          </span>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all cursor-pointer hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
        >
          <Plus className="w-4 h-4" />
          Add Driver
        </button>
      </div>

      {/* ── New intake banner ── */}
      <AnimatePresence>
        {newIntakes > 0 && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="flex items-center gap-3 px-4 py-3 rounded-2xl bg-[#667eea]/10 border border-[#667eea]/30"
          >
            <div className="w-2 h-2 rounded-full bg-[#667eea] animate-pulse flex-shrink-0" />
            <p className="text-sm font-medium text-[#667eea]">
              {newIntakes === 1 ? '1 driver' : `${newIntakes} drivers`} submitted intake info — review and send their FirstAlt invite
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Summary cards ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <SummaryCard
          label="Total in Pipeline"
          value={total}
          icon={Users}
          accent="dark:bg-[#667eea]/10 bg-indigo-50 dark:text-[#667eea] text-indigo-500"
        />
        <SummaryCard
          label="Completed This Month"
          value={completedThisMonth}
          icon={CheckCircle2}
          accent="dark:bg-emerald-500/10 bg-emerald-50 dark:text-emerald-400 text-emerald-500"
        />
        <SummaryCard
          label="Awaiting Your Action"
          value={awaitingAction}
          icon={AlertCircle}
          accent="dark:bg-amber-500/10 bg-amber-50 dark:text-amber-400 text-amber-500"
        />
        <SummaryCard
          label="Manual Steps Pending"
          value={manualPending}
          icon={Wrench}
          accent="dark:bg-gray-500/10 bg-gray-100 dark:text-gray-400 text-gray-500"
        />
      </div>

      {/* ── Filters ── */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search drivers…"
            className="pl-9 pr-4 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder-gray-400 dark:placeholder-white/30 focus:outline-none focus:border-[#667eea]/60 transition-all w-56"
          />
        </div>
        <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
          {(['all', 'In Progress', 'Blocked', 'Complete'] as const).map(v => (
            <button
              key={v}
              onClick={() => setStatus(v)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all cursor-pointer ${
                statusFilter === v
                  ? v === 'Blocked'    ? 'bg-amber-500 text-white'
                  : v === 'Complete'   ? 'bg-emerald-500 text-white'
                  : 'bg-[#667eea] text-white'
                  : 'dark:text-white/50 text-gray-500 hover:dark:text-white/80 hover:text-gray-800'
              }`}
            >
              {v === 'all' ? 'All' : v}
            </button>
          ))}
        </div>
      </div>

      {/* ── Driver table ── */}
      <div className="rounded-2xl border dark:border-white/10 border-gray-200 overflow-hidden">
        {/* Step column headers */}
        <div className="hidden lg:grid grid-cols-[2fr_auto_1fr_auto_auto_auto] gap-4 px-5 py-3 border-b dark:border-white/5 border-gray-100">
          <span className="text-xs font-medium uppercase tracking-wide dark:text-white/30 text-gray-400">Driver</span>
          <span className="text-xs font-medium uppercase tracking-wide dark:text-white/30 text-gray-400 w-52">Progress</span>
          <span className="text-xs font-medium uppercase tracking-wide dark:text-white/30 text-gray-400">Next Action</span>
          <span className="text-xs font-medium uppercase tracking-wide dark:text-white/30 text-gray-400 w-24">Status</span>
          <span className="w-20" />
          <span className="w-4" />
        </div>

        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 gap-2">
            <Users className="w-8 h-8 dark:text-white/15 text-gray-300" />
            <p className="text-sm font-medium dark:text-white/40 text-gray-500">No drivers found</p>
            <p className="text-xs dark:text-white/25 text-gray-400">
              {search || statusFilter !== 'all' ? 'Try adjusting your filters' : 'Add a driver to get started'}
            </p>
          </div>
        ) : (
          <motion.div initial="hidden" animate="show" variants={{ show: { transition: { staggerChildren: 0.04 } } }}>
            {filtered.map((record, i) => {
              const overall = getOverallStatus(record)
              const overallVariant =
                overall === 'Complete'    ? 'success' :
                overall === 'Blocked'     ? 'warning' :
                'info'

              return (
                <motion.div
                  key={record.id}
                  variants={{
                    hidden: { opacity: 0, y: 6 },
                    show:  { opacity: 1, y: 0, transition: { type: 'spring', damping: 30, stiffness: 400 } },
                  }}
                >
                  <div className={`flex flex-col lg:grid lg:grid-cols-[2fr_auto_1fr_auto_auto_auto] gap-3 lg:gap-4 items-start lg:items-center px-5 py-4 ${
                    i < filtered.length - 1 ? 'border-b dark:border-white/5 border-gray-100' : ''
                  }`}>
                    {/* Name + avatar — clickable */}
                    <Link href={`/onboarding/${record.id}`} className="flex items-center gap-3 min-w-0 group cursor-pointer">
                      <div
                        className="w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-bold flex-shrink-0 select-none"
                        style={{ background: record.person_name ? getAvatarGradient(record.person_name) : 'linear-gradient(135deg, #667eea, #06b6d4)' }}
                      >
                        {record.person_name ? getInitials(record.person_name) : '?'}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-semibold dark:text-white text-gray-800 truncate group-hover:text-[#667eea] transition-colors">{record.person_name}</p>
                          {record.intake_submitted_at && record.priority_email_status === 'pending' && !record.completed_at && (
                            <span className="flex-shrink-0 px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-[#667eea] text-white leading-none">NEW</span>
                          )}
                        </div>
                        <p className="text-xs dark:text-white/40 text-gray-500 truncate">{record.person_email}</p>
                      </div>
                    </Link>

                    {/* Step dots */}
                    <div className="w-52 flex items-center">
                      <StepDots record={record} />
                    </div>

                    {/* Next action */}
                    <div className="flex items-center">
                      <NextActionChip record={record} />
                    </div>

                    {/* Overall status badge */}
                    <div className="w-24">
                      <Badge variant={overallVariant} dot>{overall}</Badge>
                    </div>

                    {/* Copy invite link */}
                    <div className="hidden lg:flex w-20 justify-end">
                      {record.invite_token && (
                        <CopyLinkButton token={record.invite_token} />
                      )}
                    </div>

                    {/* Arrow */}
                    <Link href={`/onboarding/${record.id}`} className="hidden lg:block cursor-pointer">
                      <ChevronRight className="w-4 h-4 dark:text-white/20 text-gray-300 hover:dark:text-white/60 hover:text-gray-500 transition-colors" />
                    </Link>
                  </div>
                </motion.div>
              )
            })}
          </motion.div>
        )}
      </div>

      {/* ── Step legend ── */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-1">
        <span className="text-xs dark:text-white/30 text-gray-400 font-medium">Steps:</span>
        {STEPS.map((s, i) => (
          <span key={s.key} className="flex items-center gap-1.5 text-xs dark:text-white/40 text-gray-500">
            <span className="w-2 h-2 rounded-full dark:bg-white/20 bg-gray-300 flex-shrink-0" />
            <span className="dark:text-white/25 text-gray-400 text-[11px]">{i + 1}.</span>
            {s.label}
          </span>
        ))}
      </div>

      {/* ── Add modal ── */}
      {showAdd && (
        <AddModal
          onClose={() => setShowAdd(false)}
          onSuccess={(name?: string) => { fetchRecords(); setShowAdd(false); showToast(name ? `${name} added to onboarding` : 'Driver added to onboarding') }}
        />
      )}

      {/* ── Toast ── */}
      <AnimatePresence>
        {toast && (
          <motion.div
            key="toast"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 24 }}
            className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[100] px-5 py-3 rounded-2xl bg-emerald-500 text-white text-sm font-medium shadow-2xl flex items-center gap-2"
          >
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
