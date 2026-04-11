'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ClipboardList, Users, Calendar, FileWarning, Lock,
  Plus, Trash2, CheckSquare, Square, AlertCircle,
  Clock, CheckCircle2, Mail, Activity
} from 'lucide-react'
import { api } from '@/lib/api'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

/* ─── Types ──────────────────────────────────────────────────────────── */

interface OpsSummary {
  payroll_due_date: string | null
  onboarding_active: number
  open_notes: number
  drivers_total: number
}

interface OpsNote {
  id: number
  body: string
  created_by: string
  done: boolean
  created_at: string
  done_at: string | null
}

interface ActivityEntry {
  ts: string | null
  method: string | null
  path: string | null
  user: string | null
}

interface OnboardingRecord {
  id: number
  person_id: number
  person?: {
    full_name: string
    email?: string
  }
  consent_status: string
  priority_email_status: string
  brandon_email_status: string
  bgc_status: string
  drug_test_status: string
  contract_status: string
  files_status: string
  paychex_status: string
  started_at: string
  completed_at: string | null
}

/* ─── Constants ──────────────────────────────────────────────────────── */

const STEP_KEYS = [
  'consent_status',
  'priority_email_status',
  'brandon_email_status',
  'bgc_status',
  'drug_test_status',
  'contract_status',
  'files_status',
  'paychex_status',
] as const

type StepKey = typeof STEP_KEYS[number]

/* ─── Helpers ────────────────────────────────────────────────────────── */

function daysUntil(dateStr: string): number {
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const target = new Date(dateStr)
  target.setHours(0, 0, 0, 0)
  return Math.round((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
}

function daysSince(dateStr: string): number {
  const now = new Date()
  const start = new Date(dateStr)
  return Math.floor((now.getTime() - start.getTime()) / (1000 * 60 * 60 * 24))
}

function formatRelative(dateStr: string): string {
  const d = daysSince(dateStr)
  if (d === 0) return 'today'
  if (d === 1) return 'yesterday'
  return `${d}d ago`
}

function countCompletedSteps(record: OnboardingRecord): number {
  const terminal = new Set(['complete', 'signed', 'manual', 'skipped'])
  return STEP_KEYS.filter(k => terminal.has(record[k as keyof OnboardingRecord] as string)).length
}

function getOnboardingColor(record: OnboardingRecord): { dot: string; badge: string; label: string } {
  const steps = STEP_KEYS.map(k => record[k as keyof OnboardingRecord] as string)
  const hasPending = steps.some(s => s === 'pending')
  const hasSent = steps.some(s => s === 'sent' || s === 'waiting')
  const allDone = steps.every(s => ['complete', 'signed', 'manual', 'skipped'].includes(s))

  if (allDone)   return { dot: 'bg-emerald-500', badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30', label: 'Done' }
  if (hasPending) return { dot: 'bg-amber-400',  badge: 'bg-amber-500/10 text-amber-400 border-amber-500/30',    label: 'Action needed' }
  if (hasSent)    return { dot: 'bg-blue-400',    badge: 'bg-blue-500/10 text-blue-400 border-blue-500/30',       label: 'Waiting' }
  return { dot: 'bg-gray-400', badge: 'dark:bg-white/5 dark:text-white/50 text-gray-500 border-gray-400/30', label: 'In Progress' }
}

/* ─── Morning Brief Stat Card ─────────────────────────────────────────── */

function BriefCard({
  icon: Icon,
  label,
  value,
  accent,
  sub,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  accent: string
  sub?: string
}) {
  return (
    <div className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.03] bg-white p-5 flex items-center gap-4">
      <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${accent}`}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="min-w-0">
        <p className="text-2xl font-bold dark:text-white text-gray-900 leading-none truncate">{value}</p>
        <p className="text-xs dark:text-white/50 text-gray-500 mt-0.5">{label}</p>
        {sub && <p className="text-[11px] dark:text-white/30 text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

/* ─── Section Header ─────────────────────────────────────────────────── */

function SectionHeader({ icon: Icon, title, count }: { icon: React.ElementType; title: string; count?: number }) {
  return (
    <div className="flex items-center gap-2.5 mb-4">
      <div className="w-7 h-7 rounded-lg dark:bg-white/8 bg-gray-100 flex items-center justify-center">
        <Icon className="w-4 h-4 dark:text-white/50 text-gray-500" />
      </div>
      <h2 className="text-base font-semibold dark:text-white text-gray-900">{title}</h2>
      {count !== undefined && (
        <span className="px-2 py-0.5 rounded-full text-xs font-medium dark:bg-white/10 bg-gray-100 dark:text-white/50 text-gray-500">
          {count}
        </span>
      )}
    </div>
  )
}

/* ─── Onboarding Pipeline ─────────────────────────────────────────────── */

function OnboardingPipeline() {
  const [records, setRecords] = useState<OnboardingRecord[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<OnboardingRecord[]>('/api/data/onboarding/')
      .then(data => {
        // Only show active (not completed)
        setRecords(data.filter(r => !r.completed_at))
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="flex justify-center py-8"><LoadingSpinner /></div>

  if (records.length === 0) {
    return (
      <div className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.02] bg-gray-50 px-6 py-10 flex flex-col items-center gap-2">
        <CheckCircle2 className="w-7 h-7 dark:text-white/15 text-gray-300" />
        <p className="text-sm dark:text-white/40 text-gray-500 font-medium">No drivers in onboarding</p>
        <p className="text-xs dark:text-white/25 text-gray-400">All caught up</p>
      </div>
    )
  }

  return (
    <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
      {records.map(record => {
        const name = record.person?.full_name ?? `Driver #${record.person_id}`
        const initial = name[0]?.toUpperCase() ?? '?'
        const completed = countCompletedSteps(record)
        const total = STEP_KEYS.length
        const pct = Math.round((completed / total) * 100)
        const color = getOnboardingColor(record)
        const age = daysSince(record.started_at)

        return (
          <motion.div
            key={record.id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: 'spring', damping: 30, stiffness: 400 }}
            className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.03] bg-white p-4 space-y-3"
          >
            {/* Header */}
            <div className="flex items-center gap-3">
              <div
                className="w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-bold flex-shrink-0"
                style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
              >
                {initial}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold dark:text-white text-gray-800 truncate">{name}</p>
                <p className="text-xs dark:text-white/40 text-gray-500">Started {age === 0 ? 'today' : `${age}d ago`}</p>
              </div>
              <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full border ${color.badge}`}>
                {color.label}
              </span>
            </div>

            {/* Progress bar */}
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-xs dark:text-white/40 text-gray-500">{completed} / {total} steps</span>
                <span className="text-xs font-medium dark:text-white/60 text-gray-600">{pct}%</span>
              </div>
              <div className="h-1.5 rounded-full dark:bg-white/8 bg-gray-100 overflow-hidden">
                <motion.div
                  className="h-full rounded-full"
                  style={{ background: 'linear-gradient(90deg, #667eea, #06b6d4)' }}
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.6, ease: 'easeOut' }}
                />
              </div>
            </div>

            {/* Step dots */}
            <div className="flex items-center gap-1.5">
              {STEP_KEYS.map(key => {
                const status = record[key as keyof OnboardingRecord] as string
                const isDone = ['complete', 'signed', 'manual', 'skipped'].includes(status)
                const isSent = status === 'sent' || status === 'waiting'
                const isPending = status === 'pending'

                return (
                  <span
                    key={key}
                    className={`w-2 h-2 rounded-full flex-shrink-0 ${
                      isDone   ? 'bg-emerald-500' :
                      isSent   ? 'bg-blue-400' :
                      isPending ? 'bg-amber-400 animate-pulse' :
                      'dark:bg-white/15 bg-gray-200'
                    }`}
                    title={key.replace(/_status$/, '').replace(/_/g, ' ')}
                  />
                )
              })}
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}

/* ─── Recent Activity ────────────────────────────────────────────────── */

function timeAgo(isoString: string | null): string {
  if (!isoString) return '—'
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000)
  if (diff < 60)    return 'just now'
  if (diff < 3600)  return `${Math.floor(diff / 60)} min ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)} hour${Math.floor(diff / 3600) === 1 ? '' : 's'} ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function isOnboardingActivity(entry: ActivityEntry): boolean {
  const method = (entry.method || '').toLowerCase()
  const path = (entry.path || '').toLowerCase()
  return method.includes('onboarding') || path.includes('onboarding') || path.includes('/join/')
}

function RecentActivity() {
  const [entries, setEntries] = useState<ActivityEntry[]>([])
  const [loading, setLoading]  = useState(true)

  const fetchActivity = useCallback(() => {
    api.get<ActivityEntry[]>('/api/data/activity')
      .then(data => {
        const filtered = data.filter(isOnboardingActivity).slice(0, 5)
        setEntries(filtered)
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    fetchActivity()
    const interval = setInterval(fetchActivity, 60_000)
    return () => clearInterval(interval)
  }, [fetchActivity])

  if (loading) return <div className="flex justify-center py-8"><LoadingSpinner /></div>

  if (entries.length === 0) {
    return (
      <div className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.02] bg-gray-50 px-6 py-8 flex flex-col items-center gap-2">
        <Activity className="w-6 h-6 dark:text-white/15 text-gray-300" />
        <p className="text-sm dark:text-white/40 text-gray-500 font-medium">No recent onboarding activity</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {entries.map((entry, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.05, type: 'spring', damping: 30, stiffness: 400 }}
          className="flex items-center gap-3 px-4 py-3 rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.03] bg-white"
        >
          <div className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0 dark:bg-[#667eea]/10 bg-indigo-50">
            <Activity className="w-4 h-4 dark:text-[#667eea] text-indigo-500" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm dark:text-white text-gray-800 truncate">
              {entry.path || entry.method || 'Onboarding event'}
            </p>
            {entry.user && (
              <p className="text-xs dark:text-white/40 text-gray-400 mt-0.5">{entry.user}</p>
            )}
          </div>
          <span className="text-xs dark:text-white/30 text-gray-400 flex-shrink-0">{timeAgo(entry.ts)}</span>
        </motion.div>
      ))}
    </div>
  )
}

/* ─── Email Feed Placeholder ─────────────────────────────────────────── */

function EmailFeedPlaceholder() {
  return (
    <div className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.02] bg-gray-50 px-6 py-10 flex flex-col items-center gap-3 opacity-60">
      <div className="w-12 h-12 rounded-2xl dark:bg-white/5 bg-gray-100 flex items-center justify-center">
        <Lock className="w-5 h-5 dark:text-white/30 text-gray-400" />
      </div>
      <div className="text-center">
        <p className="text-sm font-medium dark:text-white/50 text-gray-500">Email feed coming soon</p>
        <p className="text-xs dark:text-white/30 text-gray-400 mt-1">Gmail integration pending</p>
      </div>
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg dark:bg-white/5 bg-gray-100 border dark:border-white/8 border-gray-200">
        <Mail className="w-3.5 h-3.5 dark:text-white/30 text-gray-400" />
        <span className="text-xs dark:text-white/40 text-gray-400">milionmalik.co@gmail.com</span>
      </div>
    </div>
  )
}

/* ─── Notes Section ──────────────────────────────────────────────────── */

function NotesSection() {
  const [notes, setNotes] = useState<OpsNote[]>([])
  const [loading, setLoading] = useState(true)
  const [body, setBody] = useState('')
  const [createdBy, setCreatedBy] = useState<'Malik' | 'Mom'>('Malik')
  const [adding, setAdding] = useState(false)
  const [togglingId, setTogglingId] = useState<number | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [error, setError] = useState('')

  const fetchNotes = useCallback(() => {
    api.get<OpsNote[]>('/api/data/ops/notes')
      .then(setNotes)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { fetchNotes() }, [fetchNotes])

  async function handleAdd() {
    if (!body.trim()) return
    setAdding(true)
    setError('')
    try {
      const note = await api.post<OpsNote>('/api/data/ops/notes', { body: body.trim(), created_by: createdBy })
      setNotes(prev => [note, ...prev])
      setBody('')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to add note')
    } finally {
      setAdding(false)
    }
  }

  async function handleToggle(id: number) {
    setTogglingId(id)
    try {
      const updated = await api.patch<OpsNote>(`/api/data/ops/notes/${id}`, {})
      setNotes(prev => prev.map(n => n.id === id ? updated : n))
    } catch (e) {
      console.error(e)
    } finally {
      setTogglingId(null)
    }
  }

  async function handleDelete(id: number) {
    setDeletingId(id)
    try {
      await api.delete(`/api/data/ops/notes/${id}`)
      setNotes(prev => prev.filter(n => n.id !== id))
    } catch (e) {
      console.error(e)
    } finally {
      setDeletingId(null)
    }
  }

  const openNotes = notes.filter(n => !n.done)
  const doneNotes = notes.filter(n => n.done)

  return (
    <div className="space-y-4">
      {/* Input */}
      <div className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.03] bg-white p-4 space-y-3">
        <textarea
          value={body}
          onChange={e => setBody(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleAdd() }}
          placeholder="Add a note or route move… (Cmd+Enter to submit)"
          rows={2}
          className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 placeholder-gray-400 dark:placeholder-white/25 focus:outline-none focus:border-[#667eea]/60 transition-all resize-none"
        />
        <div className="flex items-center justify-between gap-3">
          <div className="flex gap-1.5">
            {(['Malik', 'Mom'] as const).map(name => (
              <button
                key={name}
                onClick={() => setCreatedBy(name)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                  createdBy === name
                    ? 'bg-[#667eea] text-white'
                    : 'dark:bg-white/5 bg-gray-100 dark:text-white/50 text-gray-500 dark:hover:bg-white/10 hover:bg-gray-200'
                }`}
              >
                {name}
              </button>
            ))}
          </div>
          <button
            onClick={handleAdd}
            disabled={adding || !body.trim()}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all cursor-pointer hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
          >
            <Plus className="w-3.5 h-3.5" />
            {adding ? 'Adding…' : 'Add'}
          </button>
        </div>
        {error && (
          <p className="text-xs text-red-400 px-1">{error}</p>
        )}
      </div>

      {/* Notes list */}
      {loading ? (
        <div className="flex justify-center py-6"><LoadingSpinner /></div>
      ) : notes.length === 0 ? (
        <div className="text-center py-10 dark:text-white/30 text-gray-400 text-sm">
          No notes yet — add one above
        </div>
      ) : (
        <div className="space-y-2">
          <AnimatePresence mode="popLayout">
            {openNotes.map(note => (
              <motion.div
                key={note.id}
                layout
                initial={{ opacity: 0, y: -8, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95, y: -4 }}
                transition={{ type: 'spring', damping: 30, stiffness: 400 }}
                className="flex items-start gap-3 px-4 py-3 rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.03] bg-white group"
              >
                <button
                  onClick={() => handleToggle(note.id)}
                  disabled={togglingId === note.id}
                  className="mt-0.5 flex-shrink-0 cursor-pointer dark:text-white/30 text-gray-400 dark:hover:text-[#667eea] hover:text-[#667eea] transition-colors disabled:opacity-50"
                >
                  <Square className="w-4 h-4" />
                </button>
                <div className="flex-1 min-w-0 space-y-1">
                  <p className="text-sm dark:text-white text-gray-800 leading-snug">{note.body}</p>
                  <div className="flex items-center gap-2">
                    <span className={`text-[11px] font-medium px-1.5 py-0.5 rounded ${
                      note.created_by === 'Malik'
                        ? 'dark:bg-[#667eea]/15 bg-indigo-50 dark:text-[#667eea] text-indigo-600'
                        : 'dark:bg-emerald-500/15 bg-emerald-50 dark:text-emerald-400 text-emerald-600'
                    }`}>
                      {note.created_by}
                    </span>
                    <span className="text-[11px] dark:text-white/30 text-gray-400">{formatRelative(note.created_at)}</span>
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(note.id)}
                  disabled={deletingId === note.id}
                  className="flex-shrink-0 p-1.5 rounded-lg opacity-0 group-hover:opacity-100 transition-all cursor-pointer dark:text-white/25 text-gray-400 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-30"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </motion.div>
            ))}

            {/* Done notes — dimmed */}
            {doneNotes.length > 0 && (
              <motion.div layout key="done-divider" className="pt-2">
                <p className="text-xs dark:text-white/25 text-gray-400 px-1 mb-2 uppercase tracking-wider font-medium">Done</p>
                <div className="space-y-1.5">
                  {doneNotes.map(note => (
                    <motion.div
                      key={note.id}
                      layout
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="flex items-start gap-3 px-4 py-2.5 rounded-2xl border dark:border-white/5 border-gray-100 dark:bg-white/[0.02] bg-gray-50 group opacity-50 hover:opacity-70 transition-opacity"
                    >
                      <button
                        onClick={() => handleToggle(note.id)}
                        disabled={togglingId === note.id}
                        className="mt-0.5 flex-shrink-0 cursor-pointer text-emerald-500 transition-colors disabled:opacity-50"
                      >
                        <CheckSquare className="w-4 h-4" />
                      </button>
                      <div className="flex-1 min-w-0 space-y-0.5">
                        <p className="text-sm dark:text-white/50 text-gray-500 line-through leading-snug">{note.body}</p>
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] dark:text-white/25 text-gray-400">{note.created_by}</span>
                          <span className="text-[11px] dark:text-white/20 text-gray-300">{formatRelative(note.created_at)}</span>
                        </div>
                      </div>
                      <button
                        onClick={() => handleDelete(note.id)}
                        disabled={deletingId === note.id}
                        className="flex-shrink-0 p-1.5 rounded-lg opacity-0 group-hover:opacity-100 transition-all cursor-pointer dark:text-white/20 text-gray-300 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-30"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </motion.div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}

/* ─── Main Page ──────────────────────────────────────────────────────── */

export default function OpsPage() {
  const [summary, setSummary] = useState<OpsSummary | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(true)

  useEffect(() => {
    api.get<OpsSummary>('/api/data/ops/summary')
      .then(setSummary)
      .catch(console.error)
      .finally(() => setSummaryLoading(false))
  }, [])

  // Compute payroll countdown display
  let payrollLabel = 'No payroll date'
  let payrollSub: string | undefined
  if (summary?.payroll_due_date) {
    const days = daysUntil(summary.payroll_due_date)
    if (days < 0)       payrollLabel = `${Math.abs(days)}d overdue`
    else if (days === 0) payrollLabel = 'Due today'
    else if (days === 1) payrollLabel = 'Due tomorrow'
    else                 payrollLabel = `${days} days`
    payrollSub = `Payroll due ${new Date(summary.payroll_due_date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
  }

  return (
    <div className="max-w-6xl mx-auto space-y-8 py-6">

      {/* ── Header ── */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #667eea22, #06b6d422)' }}>
          <ClipboardList className="w-5 h-5" style={{ color: '#667eea' }} />
        </div>
        <div>
          <h1 className="text-2xl font-bold dark:text-white text-gray-900">Ops Board</h1>
          <p className="text-xs dark:text-white/40 text-gray-500 mt-0.5">Malik + Mom — shared command center</p>
        </div>
      </div>

      {/* ── Morning Brief ── */}
      <section>
        <SectionHeader icon={Activity} title="Morning Brief" />
        {summaryLoading ? (
          <div className="flex justify-center py-8"><LoadingSpinner /></div>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <BriefCard
              icon={Calendar}
              label="Payroll countdown"
              value={payrollLabel}
              sub={payrollSub}
              accent="dark:bg-[#667eea]/10 bg-indigo-50 dark:text-[#667eea] text-indigo-500"
            />
            <BriefCard
              icon={FileWarning}
              label="Drivers in onboarding"
              value={summary?.onboarding_active ?? 0}
              accent="dark:bg-amber-500/10 bg-amber-50 dark:text-amber-400 text-amber-500"
            />
            <BriefCard
              icon={AlertCircle}
              label="Open notes"
              value={summary?.open_notes ?? 0}
              accent="dark:bg-red-500/10 bg-red-50 dark:text-red-400 text-red-500"
            />
            <BriefCard
              icon={Users}
              label="Total active drivers"
              value={summary?.drivers_total ?? 0}
              accent="dark:bg-emerald-500/10 bg-emerald-50 dark:text-emerald-400 text-emerald-500"
            />
          </div>
        )}
      </section>

      {/* ── Recent Activity ── */}
      <section>
        <SectionHeader icon={Activity} title="Recent Activity" />
        <RecentActivity />
      </section>

      {/* ── Onboarding Pipeline ── */}
      <section>
        <SectionHeader
          icon={Clock}
          title="Onboarding Pipeline"
          count={summary?.onboarding_active}
        />
        <OnboardingPipeline />
      </section>

      {/* ── Email Feed ── */}
      <section>
        <SectionHeader icon={Mail} title="Email Feed" />
        <EmailFeedPlaceholder />
      </section>

      {/* ── Notes & Route Moves ── */}
      <section>
        <SectionHeader
          icon={ClipboardList}
          title="Notes & Route Moves"
          count={summary?.open_notes}
        />
        <NotesSection />
      </section>

    </div>
  )
}
