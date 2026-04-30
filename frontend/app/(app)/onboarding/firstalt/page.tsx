'use client'

/**
 * FirstAlt / Acumen Driver Onboarding Wizard
 *
 * Two modes:
 *   1. No ?id param   — Step 0: pick an existing driver from the people list and start onboarding
 *   2. ?id=<record_id> — Steps 1–8: walk through the FA 8-step flow for an existing onboarding record
 *
 * Routes all API calls through /api/data/onboarding/* proxy.
 */

import { useEffect, useState, useCallback } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Loader2,
  UserPlus,
  Smartphone,
  ShieldCheck,
  FlaskConical,
  GraduationCap,
  FolderOpen,
  FileSignature,
  Wallet,
  AlertTriangle,
  RefreshCw,
  Send,
  Clock,
  Search,
  ExternalLink,
  Info,
  CheckCircle2,
  Zap,
} from 'lucide-react'
import Link from 'next/link'
import { api } from '@/lib/api'
import { toast } from 'sonner'

/* ─── Types ──────────────────────────────────────────────────────────── */

interface Person {
  person_id: number
  full_name: string
  email: string | null
  phone: string | null
  home_address: string | null
}

interface OnboardingRecord {
  id: number
  person_id: number
  person_name: string | null
  person_email: string | null
  partner: string
  priority_email_status: string
  firstalt_invite_status: string
  bgc_status: string
  brandon_email_status: string
  fadv_status: string | null
  fadv_report_id: string | null
  fadv_initiated_at: string | null
  consent_status: string
  drug_test_status: string
  training_status: string
  files_status: string
  contract_status: string
  maz_training_status: string
  maz_contract_status: string
  paychex_status: string
  completed_at: string | null
}

type StepStatus = 'pending' | 'sent' | 'complete' | 'signed' | 'manual' | 'skipped' | 'initiated'

/* ─── Step definitions ───────────────────────────────────────────────── */

interface FAStep {
  number: number
  title: string
  subtitle: string
  icon: React.ElementType
  statusKey: keyof OnboardingRecord | null
  automatable: boolean
}

const FA_STEPS: FAStep[] = [
  {
    number: 1,
    title: 'FirstAlt App Invite',
    subtitle: 'Driver downloads app, creates account, signs Driver Acknowledgement',
    icon: Smartphone,
    statusKey: 'firstalt_invite_status',
    automatable: true,
  },
  {
    number: 2,
    title: 'Brandon BGC Email',
    subtitle: 'Email Brandon at FirstAlt to trigger background check',
    icon: ShieldCheck,
    statusKey: 'bgc_status',
    automatable: true,
  },
  {
    number: 3,
    title: 'Drug Test Consent',
    subtitle: 'Send Adobe Sign consent form — blank consortium PDF, no Acumen branding',
    icon: FlaskConical,
    statusKey: 'consent_status',
    automatable: true,
  },
  {
    number: 4,
    title: 'Drug Test Passed',
    subtitle: 'Driver completes DOT 5-panel at Concentra. Confirm negative result.',
    icon: FlaskConical,
    statusKey: 'drug_test_status',
    automatable: false,
  },
  {
    number: 5,
    title: 'FirstAlt Training',
    subtitle: 'FirstServes special needs training — available inside the FA app',
    icon: GraduationCap,
    statusKey: 'training_status',
    automatable: false,
  },
  {
    number: 6,
    title: 'Document Uploads',
    subtitle: 'DL, vehicle registration, vehicle inspection — upload to FirstAlt portal',
    icon: FolderOpen,
    statusKey: 'files_status',
    automatable: false,
  },
  {
    number: 7,
    title: 'Acumen Contract',
    subtitle: 'Internal Acumen contract signed via Adobe Sign',
    icon: FileSignature,
    statusKey: 'contract_status',
    automatable: true,
  },
  {
    number: 8,
    title: 'Paychex + W-9',
    subtitle: 'Add driver to Paychex Acumen account (70189220), collect W-9',
    icon: Wallet,
    statusKey: 'paychex_status',
    automatable: false,
  },
]

/* ─── Helpers ────────────────────────────────────────────────────────── */

function getStepStatus(record: OnboardingRecord, step: FAStep): StepStatus {
  if (!step.statusKey) return 'pending'
  const raw = record[step.statusKey] as string | null | undefined
  return (raw || 'pending') as StepStatus
}

function isStepDone(status: StepStatus): boolean {
  return ['complete', 'signed', 'manual', 'skipped'].includes(status)
}

function getCompletedCount(record: OnboardingRecord): number {
  return FA_STEPS.filter(s => isStepDone(getStepStatus(record, s))).length
}

/* ─── Avatar ─────────────────────────────────────────────────────────── */

const AVATAR_PALETTE = [
  ['#667eea', '#764ba2'],
  ['#06b6d4', '#0e7490'],
  ['#10b981', '#059669'],
  ['#f59e0b', '#d97706'],
  ['#8b5cf6', '#7c3aed'],
]

function avatarGradient(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  const [from, to] = AVATAR_PALETTE[h % AVATAR_PALETTE.length]
  return `linear-gradient(135deg, ${from}, ${to})`
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  return parts.length === 1
    ? (parts[0][0] || '').toUpperCase()
    : ((parts[0][0] || '') + (parts[parts.length - 1][0] || '')).toUpperCase()
}

/* ─── Status chip ────────────────────────────────────────────────────── */

function StatusChip({ status }: { status: StepStatus }) {
  const map: Record<StepStatus, { label: string; classes: string }> = {
    pending:  { label: 'Pending',   classes: 'dark:bg-white/5 bg-gray-100 dark:text-white/40 text-gray-500 border-gray-300/50' },
    sent:     { label: 'Sent',      classes: 'bg-amber-500/10 text-amber-500 border-amber-400/30' },
    initiated:{ label: 'Initiated', classes: 'bg-blue-500/10 text-blue-400 border-blue-400/30' },
    complete: { label: 'Complete',  classes: 'bg-emerald-500/10 text-emerald-500 border-emerald-400/30' },
    signed:   { label: 'Signed',    classes: 'bg-emerald-500/10 text-emerald-500 border-emerald-400/30' },
    manual:   { label: 'Review',    classes: 'bg-purple-500/10 text-purple-400 border-purple-400/30' },
    skipped:  { label: 'Skipped',   classes: 'dark:bg-white/5 bg-gray-50 dark:text-white/30 text-gray-400 border-gray-300/30' },
  }
  const { label, classes } = map[status] ?? map.pending
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border ${classes}`}>
      {label}
    </span>
  )
}

/* ─── Action button ──────────────────────────────────────────────────── */

function ActionButton({
  onClick,
  loading,
  disabled,
  variant = 'primary',
  children,
}: {
  onClick: () => void
  loading?: boolean
  disabled?: boolean
  variant?: 'primary' | 'secondary' | 'ghost'
  children: React.ReactNode
}) {
  const base = 'inline-flex items-center gap-2 px-3 py-1.5 rounded-xl text-sm font-medium transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed'
  const variants = {
    primary: 'bg-[#667eea] hover:bg-[#7c8ff5] text-white shadow-sm',
    secondary: 'dark:bg-white/8 bg-gray-100 dark:text-white/70 text-gray-700 dark:hover:bg-white/12 hover:bg-gray-200 border dark:border-white/10 border-gray-200',
    ghost: 'dark:text-white/50 text-gray-500 dark:hover:text-white hover:text-gray-800 hover:underline underline-offset-2',
  }
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className={`${base} ${variants[variant]}`}
    >
      {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : children}
    </button>
  )
}

/* ─── Step card ──────────────────────────────────────────────────────── */

function StepCard({
  step,
  status,
  active,
  children,
}: {
  step: FAStep
  status: StepStatus
  active: boolean
  children: React.ReactNode
}) {
  const done = isStepDone(status)
  const Icon = step.icon

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`rounded-2xl border transition-all duration-200 ${
        done
          ? 'dark:bg-emerald-500/5 bg-emerald-50/80 dark:border-emerald-500/20 border-emerald-200/60'
          : active
          ? 'dark:bg-[#1a2a4a] bg-white dark:border-[#667eea]/40 border-[#667eea]/30 shadow-lg shadow-[#667eea]/5'
          : 'dark:bg-white/3 bg-gray-50/80 dark:border-white/8 border-gray-200/60'
      } p-4`}
    >
      <div className="flex items-start gap-3">
        {/* Step number / check */}
        <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold ${
          done
            ? 'bg-emerald-500 text-white'
            : active
            ? 'bg-[#667eea] text-white'
            : 'dark:bg-white/8 bg-gray-200 dark:text-white/40 text-gray-500'
        }`}>
          {done ? <Check className="w-4 h-4" /> : step.number}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-0.5">
            <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${done ? 'text-emerald-500' : active ? 'text-[#667eea]' : 'dark:text-white/30 text-gray-400'}`} />
            <span className={`text-sm font-semibold ${done ? 'dark:text-white/80 text-gray-700' : active ? 'dark:text-white text-gray-900' : 'dark:text-white/50 text-gray-500'}`}>
              {step.title}
            </span>
            <StatusChip status={status} />
            {step.automatable && (
              <span className="inline-flex items-center gap-0.5 text-[10px] dark:text-[#667eea]/60 text-[#667eea]/70 font-medium">
                <Zap className="w-2.5 h-2.5" /> auto
              </span>
            )}
          </div>
          <p className="text-xs dark:text-white/35 text-gray-400 mb-3 leading-relaxed">{step.subtitle}</p>
          {children}
        </div>
      </div>
    </motion.div>
  )
}

/* ─── FADV status badge ──────────────────────────────────────────────── */

function FadvBadge({ fadv_status, fadv_report_id }: { fadv_status: string | null; fadv_report_id: string | null }) {
  if (!fadv_report_id) return null
  const map: Record<string, { label: string; classes: string }> = {
    initiated: { label: 'FADV Initiated', classes: 'bg-blue-500/10 text-blue-400 border-blue-400/30' },
    pending:   { label: 'FADV Pending',   classes: 'bg-amber-500/10 text-amber-500 border-amber-400/30' },
    clear:     { label: 'FADV Clear',     classes: 'bg-emerald-500/10 text-emerald-500 border-emerald-400/30' },
    consider:  { label: 'FADV Consider',  classes: 'bg-orange-500/10 text-orange-400 border-orange-400/30' },
    suspended: { label: 'FADV Suspended', classes: 'bg-red-500/10 text-red-400 border-red-400/30' },
  }
  const { label, classes } = map[fadv_status ?? 'pending'] ?? map.pending
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold border ${classes}`}>
      <ShieldCheck className="w-2.5 h-2.5" />
      {label}
    </span>
  )
}

/* ─── Driver picker (Step 0) ─────────────────────────────────────────── */

function DriverPicker({ onSelect }: { onSelect: (person: Person) => void }) {
  const [query, setQuery] = useState('')
  const [people, setPeople] = useState<Person[]>([])
  const [filtered, setFiltered] = useState<Person[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<Person[]>('/api/data/people/active')
      .then(data => {
        setPeople(data)
        setFiltered(data.slice(0, 12))
      })
      .catch(() => toast.error('Failed to load drivers'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!query.trim()) {
      setFiltered(people.slice(0, 12))
      return
    }
    const q = query.toLowerCase()
    setFiltered(
      people
        .filter(p => p.full_name.toLowerCase().includes(q) || (p.email || '').toLowerCase().includes(q))
        .slice(0, 12)
    )
  }, [query, people])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin dark:text-white/30 text-gray-400" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400 pointer-events-none" />
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search by name or email..."
          className="w-full pl-9 pr-4 py-2.5 rounded-xl dark:bg-white/5 bg-gray-50 dark:text-white text-gray-900 border dark:border-white/10 border-gray-200 text-sm focus:outline-none focus:border-[#667eea]/60 placeholder:dark:text-white/20 placeholder:text-gray-400"
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {filtered.map(person => (
          <button
            key={person.person_id}
            onClick={() => onSelect(person)}
            className="flex items-center gap-3 p-3 rounded-xl dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200 dark:hover:bg-white/8 hover:bg-gray-50 hover:border-[#667eea]/40 transition-all duration-150 text-left group"
          >
            <div
              className="w-9 h-9 rounded-full flex-shrink-0 flex items-center justify-center text-white text-xs font-bold"
              style={{ background: avatarGradient(person.full_name) }}
            >
              {initials(person.full_name)}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium dark:text-white text-gray-900 truncate">{person.full_name}</p>
              <p className="text-xs dark:text-white/35 text-gray-400 truncate">{person.email || 'No email'}</p>
            </div>
            <ArrowRight className="w-4 h-4 dark:text-white/20 text-gray-300 group-hover:dark:text-[#667eea] group-hover:text-[#667eea] transition-colors flex-shrink-0" />
          </button>
        ))}
        {filtered.length === 0 && (
          <div className="col-span-2 py-8 text-center dark:text-white/30 text-gray-400 text-sm">
            No drivers found matching &ldquo;{query}&rdquo;
          </div>
        )}
      </div>

      <p className="text-xs dark:text-white/25 text-gray-400 text-center">
        Showing {filtered.length} of {people.length} active drivers
      </p>
    </div>
  )
}

/* ─── Main page ──────────────────────────────────────────────────────── */

export default function FirstAltOnboardingPage() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const recordIdParam = searchParams.get('id')

  const [record, setRecord] = useState<OnboardingRecord | null>(null)
  const [loading, setLoading] = useState(!!recordIdParam)
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({})
  const [ssnInput, setSsnInput] = useState('')
  const [showFadvPanel, setShowFadvPanel] = useState(false)

  const load = useCallback(async (id: string) => {
    setLoading(true)
    try {
      const data = await api.get<OnboardingRecord>(`/api/data/onboarding/${id}`)
      setRecord(data)
    } catch {
      toast.error('Failed to load onboarding record')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (recordIdParam) {
      load(recordIdParam)
    }
  }, [recordIdParam, load])

  const doAction = useCallback(async (
    key: string,
    endpoint: string,
    body?: Record<string, unknown>
  ) => {
    setActionLoading(prev => ({ ...prev, [key]: true }))
    try {
      const result = await api.post<{ ok: boolean; error?: string; record?: OnboardingRecord }>(
        endpoint,
        body
      )
      if (result?.record) setRecord(result.record)
      toast.success('Done')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setActionLoading(prev => ({ ...prev, [key]: false }))
    }
  }, [])

  const doGet = useCallback(async (
    key: string,
    endpoint: string
  ) => {
    setActionLoading(prev => ({ ...prev, [key]: true }))
    try {
      const result = await api.get<{ ok: boolean; record?: OnboardingRecord; fadv_status?: string }>(endpoint)
      if (result?.record) setRecord(result.record)
      toast.success('Refreshed')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed')
    } finally {
      setActionLoading(prev => ({ ...prev, [key]: false }))
    }
  }, [])

  const handleDriverSelected = useCallback(async (person: Person) => {
    try {
      const result = await api.post<OnboardingRecord & { already_exists?: boolean }>(
        '/api/data/onboarding/start',
        { person_id: person.person_id, partner: 'firstalt' }
      )
      if (result.already_exists) {
        toast.info('Onboarding already started — opening existing record')
      } else {
        toast.success(`Onboarding started for ${person.full_name}`)
      }
      router.push(`/onboarding/firstalt?id=${result.id}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to start onboarding')
    }
  }, [router])

  /* ── Loading state ─────────────────────────────────────────────────── */
  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-6 h-6 animate-spin dark:text-white/30 text-gray-400" />
      </div>
    )
  }

  /* ── Step 0: Driver picker ──────────────────────────────────────────── */
  if (!recordIdParam && !record) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
        <div className="flex items-center gap-3">
          <Link
            href="/onboarding"
            className="p-2 rounded-xl dark:bg-white/5 bg-gray-100 dark:hover:bg-white/10 hover:bg-gray-200 transition-colors"
          >
            <ArrowLeft className="w-4 h-4 dark:text-white/60 text-gray-600" />
          </Link>
          <div>
            <h1 className="text-xl font-bold dark:text-white text-gray-900">FirstAlt Onboarding</h1>
            <p className="text-sm dark:text-white/40 text-gray-500">Select a driver to start the 8-step FA onboarding flow</p>
          </div>
        </div>

        <div className="rounded-2xl border dark:bg-[#0d1829] bg-white dark:border-white/8 border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-4">
            <UserPlus className="w-4 h-4 text-[#667eea]" />
            <h2 className="text-sm font-semibold dark:text-white text-gray-900">Select Driver</h2>
          </div>
          <DriverPicker onSelect={handleDriverSelected} />
        </div>
      </div>
    )
  }

  if (!record) return null

  /* ── Steps 1–8 ──────────────────────────────────────────────────────── */

  const completedCount = getCompletedCount(record)
  const totalSteps = FA_STEPS.length
  const progressPct = Math.round((completedCount / totalSteps) * 100)
  const firstPendingIdx = FA_STEPS.findIndex(s => !isStepDone(getStepStatus(record, s)))

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-5">

      {/* ── Header ────────────────────────────────────────────────────── */}
      <div className="flex items-start gap-3">
        <Link
          href="/onboarding"
          className="p-2 rounded-xl dark:bg-white/5 bg-gray-100 dark:hover:bg-white/10 hover:bg-gray-200 transition-colors mt-0.5"
        >
          <ArrowLeft className="w-4 h-4 dark:text-white/60 text-gray-600" />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            {record.person_name && (
              <div
                className="w-9 h-9 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                style={{ background: avatarGradient(record.person_name) }}
              >
                {initials(record.person_name)}
              </div>
            )}
            <div>
              <h1 className="text-xl font-bold dark:text-white text-gray-900">
                {record.person_name || 'Driver Onboarding'}
              </h1>
              <p className="text-sm dark:text-white/40 text-gray-500">
                FirstAlt · Record #{record.id} · {record.person_email || 'No email'}
              </p>
            </div>
            {record.completed_at && (
              <span className="ml-auto inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-500 border border-emerald-400/30 text-xs font-semibold">
                <CheckCircle2 className="w-3.5 h-3.5" />
                Complete
              </span>
            )}
          </div>
        </div>
      </div>

      {/* ── Progress bar ──────────────────────────────────────────────── */}
      <div className="rounded-2xl border dark:bg-[#0d1829] bg-white dark:border-white/8 border-gray-200 p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium dark:text-white/70 text-gray-700">
            Progress — {completedCount} of {totalSteps} steps
          </span>
          <span className="text-sm font-bold dark:text-white text-gray-900">{progressPct}%</span>
        </div>
        <div className="h-2 rounded-full dark:bg-white/8 bg-gray-200 overflow-hidden">
          <motion.div
            className="h-full rounded-full bg-gradient-to-r from-[#667eea] to-[#764ba2]"
            initial={{ width: 0 }}
            animate={{ width: `${progressPct}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
        </div>
        <div className="flex gap-1.5 mt-3">
          {FA_STEPS.map(s => {
            const st = getStepStatus(record, s)
            const done = isStepDone(st)
            return (
              <div
                key={s.number}
                title={s.title}
                className={`h-1.5 flex-1 rounded-full transition-colors duration-300 ${
                  done ? 'bg-emerald-500' : st === 'sent' ? 'bg-amber-400' : 'dark:bg-white/10 bg-gray-200'
                }`}
              />
            )
          })}
        </div>
      </div>

      {/* ── FADV pre-check panel (optional) ───────────────────────────── */}
      <div className="rounded-2xl border dark:border-white/8 border-gray-200 dark:bg-white/3 bg-gray-50/60 overflow-hidden">
        <button
          onClick={() => setShowFadvPanel(v => !v)}
          className="w-full flex items-center gap-2 px-4 py-3 text-left dark:hover:bg-white/3 hover:bg-gray-100 transition-colors"
        >
          <ShieldCheck className="w-4 h-4 text-[#667eea]" />
          <span className="text-sm font-semibold dark:text-white/80 text-gray-700 flex-1">
            First Advantage Pre-Check (Optional)
          </span>
          {record.fadv_report_id && (
            <FadvBadge fadv_status={record.fadv_status} fadv_report_id={record.fadv_report_id} />
          )}
          <span className="text-xs dark:text-white/30 text-gray-400">{showFadvPanel ? '▲' : '▼'}</span>
        </button>
        <AnimatePresence>
          {showFadvPanel && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="px-4 pb-4 space-y-3 border-t dark:border-white/8 border-gray-200 pt-3">
                <div className="flex items-start gap-2 p-3 rounded-xl dark:bg-blue-500/8 bg-blue-50 border dark:border-blue-400/20 border-blue-200">
                  <Info className="w-3.5 h-3.5 text-blue-400 flex-shrink-0 mt-0.5" />
                  <p className="text-xs dark:text-blue-300/80 text-blue-700 leading-relaxed">
                    Pre-running FADV lets Maz see BGC results before FirstAlt triggers their own check.
                    Catches problems early. Requires <strong>FADV_CLIENT_ID</strong> and <strong>FADV_CLIENT_SECRET</strong> in Railway env.
                  </p>
                </div>
                {!record.fadv_report_id ? (
                  <div className="flex items-end gap-3">
                    <div className="flex-1">
                      <label className="block text-xs dark:text-white/40 text-gray-500 mb-1">Last 4 SSN</label>
                      <input
                        type="text"
                        inputMode="numeric"
                        maxLength={4}
                        value={ssnInput}
                        onChange={e => setSsnInput(e.target.value.replace(/\D/g, ''))}
                        placeholder="1234"
                        className="w-full px-3 py-2 text-sm rounded-xl dark:bg-white/5 bg-white dark:text-white text-gray-900 border dark:border-white/10 border-gray-200 focus:outline-none focus:border-[#667eea]/60 placeholder:dark:text-white/20 placeholder:text-gray-400"
                      />
                    </div>
                    <ActionButton
                      onClick={() => doAction(
                        'fadvInit',
                        `/api/data/onboarding/${record.id}/initiate-fadv-bgc`,
                        { ssn_last4: ssnInput }
                      )}
                      loading={actionLoading['fadvInit']}
                      disabled={ssnInput.length !== 4}
                    >
                      <Zap className="w-3.5 h-3.5" />
                      Run FADV Check
                    </ActionButton>
                  </div>
                ) : (
                  <div className="flex items-center gap-3">
                    <FadvBadge fadv_status={record.fadv_status} fadv_report_id={record.fadv_report_id} />
                    <span className="text-xs dark:text-white/40 text-gray-500">
                      Report: {record.fadv_report_id}
                      {record.fadv_initiated_at && ` · Initiated ${new Date(record.fadv_initiated_at).toLocaleDateString()}`}
                    </span>
                    <ActionButton
                      onClick={() => doGet('fadvRefresh', `/api/data/onboarding/${record.id}/fadv-status`)}
                      loading={actionLoading['fadvRefresh']}
                      variant="ghost"
                    >
                      <RefreshCw className="w-3 h-3" />
                      Refresh
                    </ActionButton>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Step cards ────────────────────────────────────────────────── */}
      <div className="space-y-3">
        {FA_STEPS.map((step, idx) => {
          const status = getStepStatus(record, step)
          const done = isStepDone(status)
          const active = idx === firstPendingIdx

          return (
            <StepCard key={step.number} step={step} status={status} active={active}>
              <StepActions
                step={step}
                status={status}
                done={done}
                active={active}
                record={record}
                actionLoading={actionLoading}
                doAction={doAction}
              />
            </StepCard>
          )
        })}
      </div>

      {/* ── View full detail link ─────────────────────────────────────── */}
      <div className="text-center pt-2">
        <Link
          href={`/onboarding/${record.id}`}
          className="inline-flex items-center gap-1.5 text-sm dark:text-[#667eea]/80 text-[#667eea] hover:underline underline-offset-2"
        >
          <ExternalLink className="w-3.5 h-3.5" />
          Open full detail view
        </Link>
      </div>
    </div>
  )
}

/* ─── Step-specific action panels ────────────────────────────────────── */

function StepActions({
  step,
  status,
  done,
  active,
  record,
  actionLoading,
  doAction,
}: {
  step: FAStep
  status: StepStatus
  done: boolean
  active: boolean
  record: OnboardingRecord
  actionLoading: Record<string, boolean>
  doAction: (key: string, endpoint: string, body?: Record<string, unknown>) => Promise<void>
}) {
  if (done) {
    return (
      <div className="flex items-center gap-2 text-xs text-emerald-500">
        <Check className="w-3.5 h-3.5" />
        Done
      </div>
    )
  }

  const base = `/api/data/onboarding/${record.id}`

  switch (step.number) {
    case 1:
      return (
        <div className="flex flex-wrap items-center gap-2">
          {status === 'pending' && (
            <ActionButton
              onClick={() => doAction('faInvite', `${base}/send-firstalt-invite`)}
              loading={actionLoading['faInvite']}
            >
              <Send className="w-3.5 h-3.5" />
              Send Invite Email
            </ActionButton>
          )}
          {status === 'sent' && (
            <>
              <div className="flex items-center gap-1.5 text-xs text-amber-500">
                <Clock className="w-3.5 h-3.5" />
                Invite sent — waiting for driver to create account
              </div>
              <ActionButton
                onClick={() => doAction('faInviteMark', `${base}/mark-firstalt-invited`)}
                loading={actionLoading['faInviteMark']}
                variant="secondary"
              >
                <Check className="w-3.5 h-3.5" />
                Mark Complete
              </ActionButton>
            </>
          )}
          <a
            href="https://spguardian.firstalt.com"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs dark:text-white/40 text-gray-400 hover:dark:text-white hover:text-gray-700 transition-colors"
          >
            <ExternalLink className="w-3 h-3" />
            SP Guardian
          </a>
        </div>
      )

    case 2:
      return (
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            onClick={() => doAction('brandonEmail', `${base}/send-brandon-email`)}
            loading={actionLoading['brandonEmail']}
          >
            <Send className="w-3.5 h-3.5" />
            Email Brandon
          </ActionButton>
          {status === 'sent' && (
            <ActionButton
              onClick={() => doAction('bgcManual', `${base}/mark-bgc-sent`)}
              loading={actionLoading['bgcManual']}
              variant="secondary"
            >
              <Check className="w-3.5 h-3.5" />
              Mark BGC Received
            </ActionButton>
          )}
          {(status === 'manual') && (
            <div className="flex items-center gap-1.5 text-xs text-purple-400">
              <AlertTriangle className="w-3.5 h-3.5" />
              Review BGC results before proceeding
            </div>
          )}
        </div>
      )

    case 3:
      return (
        <div className="space-y-2">
          {status === 'pending' && (
            <ActionButton
              onClick={() => doAction('drugConsent', `${base}/send-fa-drug-consent`)}
              loading={actionLoading['drugConsent']}
            >
              <Send className="w-3.5 h-3.5" />
              Send Consent Form
            </ActionButton>
          )}
          {status === 'sent' && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1.5 text-xs text-amber-500">
                <Clock className="w-3.5 h-3.5" />
                Consent form sent — waiting for driver signature
              </div>
              <ActionButton
                onClick={() => doAction('consentSigned', `${base}/mark-fa-drug-consent-signed`)}
                loading={actionLoading['consentSigned']}
                variant="secondary"
              >
                <Check className="w-3.5 h-3.5" />
                Mark Signed
              </ActionButton>
            </div>
          )}
          <p className="text-[11px] dark:text-white/25 text-gray-400">
            Uses blank consortium PDF. Adobe emails signed copy to mazservices3@gmail.com.
            Forward to Priority Solutions on your own channel.
          </p>
        </div>
      )

    case 4:
      return (
        <div className="space-y-2">
          <p className="text-xs dark:text-white/40 text-gray-500">
            Driver goes to Concentra for DOT 5-panel urine test. Negative results in 24–48h.
            Mark complete once Priority Solutions confirms negative result.
          </p>
          <ActionButton
            onClick={() => doAction('drugPassed', `${base}/mark-fa-drug-test-passed`)}
            loading={actionLoading['drugPassed']}
            variant="secondary"
          >
            <Check className="w-3.5 h-3.5" />
            Mark Drug Test Passed
          </ActionButton>
        </div>
      )

    case 5:
      return (
        <div className="space-y-2">
          <p className="text-xs dark:text-white/40 text-gray-500">
            FirstServes special needs training — available in the FA app after account creation.
            Takes 2–3 hours.
          </p>
          <ActionButton
            onClick={() => doAction('training', `${base}/mark-fa-training-complete`)}
            loading={actionLoading['training']}
            variant="secondary"
          >
            <Check className="w-3.5 h-3.5" />
            Mark Training Complete
          </ActionButton>
        </div>
      )

    case 6:
      return (
        <div className="space-y-2">
          <p className="text-xs dark:text-white/40 text-gray-500">
            Vehicle registration, inspection certificate, and DL must be uploaded to the FA portal.
            Upload backups to Z-Pay via the full detail view.
          </p>
          <div className="flex items-center gap-2">
            <ActionButton
              onClick={() => doAction('files', `${base}/mark-fa-files-complete`)}
              loading={actionLoading['files']}
              variant="secondary"
            >
              <Check className="w-3.5 h-3.5" />
              Mark Docs Uploaded
            </ActionButton>
            <Link
              href={`/onboarding/${record.id}`}
              className="inline-flex items-center gap-1 text-xs dark:text-[#667eea]/70 text-[#667eea] hover:underline underline-offset-2"
            >
              <ExternalLink className="w-3 h-3" />
              Upload in detail view
            </Link>
          </div>
        </div>
      )

    case 7:
      return (
        <div className="space-y-2">
          <p className="text-xs dark:text-white/40 text-gray-500">
            Acumen internal contract sent via Adobe Sign. Driver signs digitally.
            Use the full detail view to send the contract.
          </p>
          <div className="flex items-center gap-2">
            {status === 'sent' && (
              <div className="flex items-center gap-1.5 text-xs text-amber-500">
                <Clock className="w-3.5 h-3.5" />
                Awaiting driver signature
              </div>
            )}
            <Link
              href={`/onboarding/${record.id}`}
              className="inline-flex items-center gap-1 text-xs dark:text-[#667eea]/70 text-[#667eea] hover:underline underline-offset-2"
            >
              <ExternalLink className="w-3 h-3" />
              Send contract in detail view
            </Link>
          </div>
        </div>
      )

    case 8:
      return (
        <div className="space-y-2">
          <p className="text-xs dark:text-white/40 text-gray-500">
            Add driver to Paychex Acumen account (70189220). Single-member LLC owners
            check &quot;individual/sole proprietor&quot; on W-9, NOT &quot;LLC&quot;.
          </p>
          <div className="flex items-center gap-2">
            <ActionButton
              onClick={() => doAction('paychex', `${base}/mark-paychex-complete`)}
              loading={actionLoading['paychex']}
              variant="secondary"
            >
              <Check className="w-3.5 h-3.5" />
              Mark Paychex Complete
            </ActionButton>
            <a
              href={`/api/data/onboarding/${record.id}/paychex-csv`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs dark:text-[#667eea]/70 text-[#667eea] hover:underline underline-offset-2"
            >
              <ExternalLink className="w-3 h-3" />
              Export Paychex row
            </a>
          </div>
        </div>
      )

    default:
      return null
  }
}
