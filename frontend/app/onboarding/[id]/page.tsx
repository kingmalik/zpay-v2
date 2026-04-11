'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft,
  Check,
  Clock,
  AlertCircle,
  Mail,
  FileText,
  Upload,
  User,
  Car,
  Phone,
  MapPin,
  ExternalLink,
  Copy,
  CheckCheck,
  X,
  Pencil,
  Send,
  Wrench,
  ShieldCheck,
  FlaskConical,
  Scroll,
  FolderOpen,
  Wallet,
  Globe,
} from 'lucide-react'
import Link from 'next/link'
import { api } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

/* ─── Types ──────────────────────────────────────────────────────────── */
interface OnboardingFile {
  id: number
  file_type: string
  filename: string | null
  r2_url: string | null
  uploaded_at: string | null
  expires_at: string | null
}

interface OnboardingRecord {
  id: number
  person_id: number
  person_name: string
  person_email: string
  person_phone: string
  person_address: string
  person_vehicle: string
  person_language: string | null
  consent_status: string
  consent_envelope_id: string | null
  priority_email_status: string
  brandon_email_status: string
  bgc_status: string
  drug_test_status: string
  contract_status: string
  contract_envelope_id: string | null
  files_status: string
  paychex_status: string
  notes: string | null
  started_at: string
  completed_at: string | null
  files: OnboardingFile[]
}

interface BrandonEmailData {
  to: string
  subject: string
  body: string
}

/* ─── Status helpers ─────────────────────────────────────────────────── */
type StepStatus = 'complete' | 'pending' | 'sent' | 'partial' | 'manual'

function resolveStatus(raw: string): StepStatus {
  const s = (raw || '').toLowerCase()
  if (s === 'complete' || s === 'done' || s === 'signed' || s === 'sent') return 'complete'
  if (s === 'awaiting' || s === 'in_progress' || s === 'sent_awaiting') return 'sent'
  if (s === 'partial') return 'partial'
  return 'pending'
}

function statusBadge(status: StepStatus) {
  switch (status) {
    case 'complete': return <Badge variant="success" dot>Complete</Badge>
    case 'sent': return <Badge variant="info" dot>Awaiting</Badge>
    case 'partial': return <Badge variant="warning" dot>Partial</Badge>
    case 'manual': return <Badge variant="inactive" dot>Manual</Badge>
    default: return <Badge variant="default" dot>Pending</Badge>
  }
}

function overallStatus(record: OnboardingRecord): StepStatus {
  if (record.completed_at) return 'complete'
  const statuses = [
    record.consent_status,
    record.priority_email_status,
    record.brandon_email_status,
    record.bgc_status,
    record.drug_test_status,
    record.contract_status,
    record.files_status,
    record.paychex_status,
  ]
  const allDone = statuses.every(s => {
    const v = (s || '').toLowerCase()
    return v === 'complete' || v === 'done' || v === 'signed' || v === 'sent'
  })
  if (allDone) return 'complete'
  const anyDone = statuses.some(s => {
    const v = (s || '').toLowerCase()
    return v === 'complete' || v === 'done' || v === 'signed' || v === 'sent'
  })
  if (anyDone) return 'partial'
  return 'pending'
}

/* ─── Step Card ──────────────────────────────────────────────────────── */
interface StepCardProps {
  number: number
  icon: React.ReactNode
  title: string
  status?: StepStatus
  isManual?: boolean
  manualNote?: string
  children: React.ReactNode
}

function StepCard({ number, icon, title, status = 'pending', isManual, manualNote, children }: StepCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: number * 0.04 }}
      className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.02] bg-white p-5"
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className={`w-8 h-8 rounded-xl flex items-center justify-center text-sm font-bold flex-shrink-0 ${
            status === 'complete'
              ? 'bg-emerald-500/15 text-emerald-400'
              : status === 'sent'
              ? 'bg-blue-500/15 text-blue-400'
              : 'dark:bg-white/8 bg-gray-100 dark:text-white/50 text-gray-400'
          }`}>
            {status === 'complete' ? <Check className="w-4 h-4" /> : number}
          </div>
          <div className="flex items-center gap-2">
            <span className="dark:text-white/30 text-gray-400">{icon}</span>
            <span className="font-semibold dark:text-white text-gray-900 text-sm">{title}</span>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {isManual && (
            <span className="text-xs px-2 py-0.5 rounded-full dark:bg-white/5 bg-gray-100 dark:text-white/40 text-gray-500 border dark:border-white/10 border-gray-200">
              Manual
            </span>
          )}
          {statusBadge(status)}
        </div>
      </div>

      {isManual && manualNote && (
        <p className="text-xs dark:text-white/40 text-gray-500 mb-3 pl-11">{manualNote}</p>
      )}

      <div className="pl-11">{children}</div>
    </motion.div>
  )
}

/* ─── Action Button ──────────────────────────────────────────────────── */
function ActionButton({
  onClick,
  loading,
  disabled,
  children,
  variant = 'primary',
}: {
  onClick: () => void
  loading?: boolean
  disabled?: boolean
  children: React.ReactNode
  variant?: 'primary' | 'secondary'
}) {
  if (variant === 'primary') {
    return (
      <button
        onClick={onClick}
        disabled={loading || disabled}
        className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all cursor-pointer disabled:opacity-50"
        style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
      >
        {loading && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
        {children}
      </button>
    )
  }
  return (
    <button
      onClick={onClick}
      disabled={loading || disabled}
      className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium dark:bg-white/5 bg-gray-100 dark:text-white/70 text-gray-700 dark:hover:bg-white/10 hover:bg-gray-200 border dark:border-white/10 border-gray-200 transition-all cursor-pointer disabled:opacity-50"
    >
      {loading && <div className="w-3.5 h-3.5 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />}
      {children}
    </button>
  )
}

/* ─── Brandon Email Modal ───────────────────────────────────────────── */
function BrandonEmailModal({
  recordId,
  onClose,
  onMarkedSent,
}: {
  recordId: number
  onClose: () => void
  onMarkedSent: () => void
}) {
  const [emailData, setEmailData] = useState<BrandonEmailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const [marking, setMarking] = useState(false)

  useEffect(() => {
    api
      .get<BrandonEmailData>(`/api/data/onboarding/${recordId}/brandon-email`)
      .then(setEmailData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [recordId])

  async function markSent() {
    setMarking(true)
    try {
      await api.post(`/api/data/onboarding/${recordId}/mark-brandon-sent`)
      onMarkedSent()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to mark as sent')
      setMarking(false)
    }
  }

  function copyToClipboard() {
    if (!emailData) return
    const text = `To: ${emailData.to}\nSubject: ${emailData.subject}\n\n${emailData.body}`
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2500)
  }

  function openInMail() {
    if (!emailData) return
    const mailto = `mailto:${emailData.to}?subject=${encodeURIComponent(emailData.subject)}&body=${encodeURIComponent(emailData.body)}`
    window.open(mailto)
    markSent()
  }

  return (
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
        <div className="flex items-center justify-between mb-5">
          <div>
            <h2 className="text-base font-bold dark:text-white text-gray-900">FirstAlt Email — Brandon</h2>
            <p className="text-xs dark:text-white/40 text-gray-500 mt-0.5">Review and send to trigger the BGC check</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg dark:hover:bg-white/10 hover:bg-gray-100 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4 dark:text-white/50 text-gray-500" />
          </button>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="w-6 h-6 border-2 border-[#667eea]/30 border-t-[#667eea] rounded-full animate-spin" />
          </div>
        )}

        {error && (
          <div className="px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm mb-4">
            {error}
          </div>
        )}

        {emailData && (
          <div className="space-y-4">
            {/* To + Subject */}
            <div className="rounded-xl dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 overflow-hidden">
              <div className="flex border-b dark:border-white/8 border-gray-100">
                <span className="px-4 py-3 text-xs font-semibold dark:text-white/40 text-gray-500 uppercase tracking-wide w-20 flex-shrink-0 border-r dark:border-white/8 border-gray-100">
                  To
                </span>
                <span className="px-4 py-3 text-sm dark:text-white text-gray-800 font-medium">{emailData.to}</span>
              </div>
              <div className="flex">
                <span className="px-4 py-3 text-xs font-semibold dark:text-white/40 text-gray-500 uppercase tracking-wide w-20 flex-shrink-0 border-r dark:border-white/8 border-gray-100">
                  Subject
                </span>
                <span className="px-4 py-3 text-sm dark:text-white text-gray-800">{emailData.subject}</span>
              </div>
            </div>

            {/* Body */}
            <div className="rounded-xl dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 p-4">
              <pre className="text-sm dark:text-white/80 text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                {emailData.body}
              </pre>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-3 pt-1 flex-wrap">
              <button
                onClick={copyToClipboard}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium dark:bg-white/5 bg-gray-100 dark:text-white/70 text-gray-700 dark:hover:bg-white/10 hover:bg-gray-200 border dark:border-white/10 border-gray-200 transition-all cursor-pointer"
              >
                {copied ? <CheckCheck className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                {copied ? 'Copied!' : 'Copy to Clipboard'}
              </button>
              <button
                onClick={openInMail}
                disabled={marking}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all cursor-pointer disabled:opacity-50"
                style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
              >
                {marking
                  ? <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  : <Mail className="w-4 h-4" />}
                Open in Mail
              </button>
              {copied && (
                <button
                  onClick={markSent}
                  disabled={marking}
                  className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium dark:text-white/50 text-gray-500 dark:hover:bg-white/5 hover:bg-gray-100 transition-all cursor-pointer disabled:opacity-50"
                >
                  {marking
                    ? <div className="w-3 h-3 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
                    : <Check className="w-3.5 h-3.5" />}
                  Mark as Sent
                </button>
              )}
            </div>
          </div>
        )}
      </motion.div>
    </motion.div>
  )
}

/* ─── File Upload Slot ───────────────────────────────────────────────── */
const FILE_TYPE_LABELS: Record<string, string> = {
  drivers_license: "Driver's License",
  vehicle_registration: 'Vehicle Registration',
  inspection: 'Inspection Doc',
}

function FileSlot({
  fileType,
  file,
  recordId,
  onUploaded,
}: {
  fileType: string
  file: OnboardingFile | undefined
  recordId: number
  onUploaded: () => void
}) {
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setUploading(true)
    setUploadError('')
    const fd = new FormData()
    fd.append('file', f)
    fd.append('file_type', fileType)
    try {
      await api.postForm(`/api/data/onboarding/${recordId}/upload`, fd)
      onUploaded()
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const label = FILE_TYPE_LABELS[fileType] || fileType

  return (
    <div className="flex items-center justify-between py-3 border-b dark:border-white/8 border-gray-100 last:border-0">
      <div className="flex items-center gap-3 min-w-0">
        <div className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${
          file?.filename
            ? 'bg-emerald-500/10 text-emerald-400'
            : 'dark:bg-white/8 bg-gray-100 dark:text-white/30 text-gray-400'
        }`}>
          {file?.filename ? <Check className="w-3.5 h-3.5" /> : <FileText className="w-3.5 h-3.5" />}
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium dark:text-white/70 text-gray-700">{label}</p>
          {file?.filename ? (
            <div className="flex items-center gap-2 mt-0.5 flex-wrap">
              {file.r2_url ? (
                <a
                  href={file.r2_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-[#667eea] hover:underline truncate max-w-[160px]"
                >
                  {file.filename}
                </a>
              ) : (
                <span className="text-xs dark:text-white/40 text-gray-500 truncate max-w-[160px]">{file.filename}</span>
              )}
              {file.expires_at && (
                <span className="text-xs dark:text-white/30 text-gray-400 flex-shrink-0">
                  · Exp {formatDate(file.expires_at)}
                </span>
              )}
            </div>
          ) : (
            <p className="text-xs dark:text-white/30 text-gray-400 mt-0.5">Not uploaded</p>
          )}
          {uploadError && <p className="text-xs text-red-400 mt-0.5">{uploadError}</p>}
        </div>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0 ml-3">
        <input ref={inputRef} type="file" className="hidden" onChange={handleFile} />
        <button
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-200 border dark:border-white/10 border-gray-200 transition-all cursor-pointer disabled:opacity-50"
        >
          {uploading
            ? <div className="w-3 h-3 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
            : <Upload className="w-3 h-3" />}
          {file?.filename ? 'Replace' : 'Upload'}
        </button>
      </div>
    </div>
  )
}

/* ─── Inline Note Edit ───────────────────────────────────────────────── */
function InlineNoteEdit({
  recordId,
  value,
  onSave,
}: {
  recordId: number
  value: string
  onSave: (v: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(value)
  const [saving, setSaving] = useState(false)

  async function save() {
    setSaving(true)
    try {
      await api.post(`/api/data/onboarding/${recordId}/set-notes`, { notes: val })
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
      <div className="space-y-2">
        <textarea
          autoFocus
          value={val}
          onChange={e => setVal(e.target.value)}
          rows={3}
          className="w-full px-3 py-2 text-sm rounded-xl dark:bg-white/5 bg-gray-50 dark:text-white text-gray-800 border dark:border-white/10 border-gray-200 focus:outline-none focus:border-[#667eea]/60 resize-none"
        />
        <div className="flex gap-2">
          <button
            onClick={save}
            disabled={saving}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-white cursor-pointer disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={() => { setVal(value); setEditing(false) }}
            className="px-3 py-1.5 rounded-lg text-xs font-medium dark:text-white/50 text-gray-500 dark:hover:bg-white/5 hover:bg-gray-100 cursor-pointer"
          >
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div
      onClick={() => setEditing(true)}
      className="group cursor-pointer rounded-xl p-3 dark:hover:bg-white/5 hover:bg-gray-50 transition-colors border border-dashed dark:border-white/10 border-gray-200"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm dark:text-white/60 text-gray-600 leading-relaxed whitespace-pre-wrap">
          {val || <span className="dark:text-white/25 text-gray-400 italic">No notes — click to add</span>}
        </p>
        <Pencil className="w-3 h-3 dark:text-white/20 text-gray-300 flex-shrink-0 mt-0.5 group-hover:dark:text-white/40 group-hover:text-gray-400 transition-colors" />
      </div>
    </div>
  )
}

/* ─── Language Selector ──────────────────────────────────────────────── */
const LANG_OPTIONS_DETAIL = [
  { code: 'en', flag: '🇺🇸', label: 'EN' },
  { code: 'ar', flag: '🇸🇦', label: 'AR' },
  { code: 'am', flag: '🇪🇹', label: 'AM' },
] as const

function LanguageSelector({
  personId,
  current,
  onChange,
}: {
  personId: number
  current: string | null
  onChange: (lang: string) => void
}) {
  const [saving, setSaving] = useState<string | null>(null)

  async function setLang(lang: string) {
    if (saving || current === lang) return
    setSaving(lang)
    try {
      await api.patch(`/api/data/people/${personId}/language`, { language: lang })
      onChange(lang)
    } catch {
      // ignore
    } finally {
      setSaving(null)
    }
  }

  return (
    <div className="flex items-start gap-3 py-2.5 border-b dark:border-white/8 border-gray-100 last:border-0">
      <div className="w-7 h-7 rounded-lg dark:bg-white/5 bg-gray-100 flex items-center justify-center flex-shrink-0 mt-0.5">
        <Globe className="w-3.5 h-3.5 dark:text-white/40 text-gray-400" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs dark:text-white/40 text-gray-500 mb-1.5">Call Language</p>
        <div className="flex items-center gap-1.5">
          {LANG_OPTIONS_DETAIL.map(opt => {
            const isActive = current === opt.code
            const isSaving = saving === opt.code
            return (
              <button
                key={opt.code}
                onClick={() => setLang(opt.code)}
                disabled={!!saving}
                className={[
                  'flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium border transition-all cursor-pointer disabled:cursor-not-allowed',
                  isActive
                    ? 'bg-[#667eea] text-white border-[#667eea]'
                    : 'dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-500 dark:border-white/10 border-gray-200 dark:hover:bg-white/10 hover:bg-gray-200',
                ].join(' ')}
              >
                {isSaving
                  ? <span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
                  : <span>{opt.flag}</span>
                }
                {opt.label}
              </button>
            )
          })}
          {!current && (
            <span className="text-xs dark:text-white/25 text-gray-400 ml-1 italic">not set</span>
          )}
        </div>
      </div>
    </div>
  )
}

/* ─── Info Row ───────────────────────────────────────────────────────── */
function InfoRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | null | undefined }) {
  return (
    <div className="flex items-start gap-3 py-2.5 border-b dark:border-white/8 border-gray-100 last:border-0">
      <div className="w-7 h-7 rounded-lg dark:bg-white/5 bg-gray-100 flex items-center justify-center flex-shrink-0 mt-0.5">
        <span className="dark:text-white/40 text-gray-400">{icon}</span>
      </div>
      <div className="min-w-0">
        <p className="text-xs dark:text-white/40 text-gray-500 mb-0.5">{label}</p>
        <p className="text-sm dark:text-white/80 text-gray-800 break-words">{value || '—'}</p>
      </div>
    </div>
  )
}

/* ─── Main Page ──────────────────────────────────────────────────────── */
export default function OnboardingDetailPage() {
  const params = useParams()
  const router = useRouter()
  const id = Number(params.id)

  const [record, setRecord] = useState<OnboardingRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [pageError, setPageError] = useState('')
  const [showBrandonModal, setShowBrandonModal] = useState(false)
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({})
  const [personLanguage, setPersonLanguage] = useState<string | null>(null)

  const fetchRecord = useCallback(() => {
    return api
      .get<OnboardingRecord>(`/api/data/onboarding/${id}`)
      .then(r => {
        setRecord(r)
        setPersonLanguage(r.person_language ?? null)
      })
      .catch(e => setPageError(e.message))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => { fetchRecord() }, [fetchRecord])

  async function doAction(key: string, endpoint: string) {
    setActionLoading(prev => ({ ...prev, [key]: true }))
    try {
      await api.post(endpoint)
      await fetchRecord()
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Action failed')
    } finally {
      setActionLoading(prev => ({ ...prev, [key]: false }))
    }
  }

  if (loading) return <LoadingSpinner fullPage />

  if (pageError || !record) {
    return (
      <div className="max-w-4xl mx-auto py-12 text-center">
        <AlertCircle className="w-10 h-10 text-red-400 mx-auto mb-3" />
        <p className="dark:text-white/60 text-gray-500 text-sm">{pageError || 'Record not found'}</p>
        <Link href="/onboarding" className="text-[#667eea] text-sm mt-3 inline-block hover:underline">
          Back to Onboarding
        </Link>
      </div>
    )
  }

  const files = record.files || []
  const licenseFile = files.find(f => f.file_type === 'drivers_license')
  const regFile = files.find(f => f.file_type === 'vehicle_registration')
  const inspFile = files.find(f => f.file_type === 'inspection')
  const uploadedCount = [licenseFile, regFile, inspFile].filter(f => f?.filename).length

  const consentStatus = resolveStatus(record.consent_status)
  const priorityStatus = resolveStatus(record.priority_email_status)
  const brandonStatus = resolveStatus(record.brandon_email_status)
  const bgcStatus = resolveStatus(record.bgc_status)
  const drugStatus = resolveStatus(record.drug_test_status)
  const contractStatus = resolveStatus(record.contract_status)
  const filesStatus: StepStatus = uploadedCount === 3 ? 'complete' : uploadedCount > 0 ? 'partial' : 'pending'
  const paychexStatus = resolveStatus(record.paychex_status)
  const overall = overallStatus(record)

  const initials = record.person_name
    ?.split(' ')
    .map(w => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase() || '?'

  const allStepStatuses = [
    consentStatus, priorityStatus, brandonStatus, bgcStatus,
    drugStatus, contractStatus, filesStatus, paychexStatus,
  ]
  const doneCount = allStepStatuses.filter(s => s === 'complete').length
  const progressPct = Math.round((doneCount / allStepStatuses.length) * 100)

  return (
    <div className="max-w-6xl mx-auto space-y-6 py-6">

      {/* ── Header ────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push('/onboarding')}
            className="p-2 rounded-xl dark:hover:bg-white/8 hover:bg-gray-100 transition-colors cursor-pointer dark:text-white/50 text-gray-500"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>

          <div
            className="w-12 h-12 rounded-2xl flex items-center justify-center text-white text-lg font-bold flex-shrink-0"
            style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
          >
            {initials}
          </div>

          <div>
            <h1 className="text-2xl font-bold dark:text-white text-gray-900">{record.person_name}</h1>
            <p className="text-sm dark:text-white/40 text-gray-500 mt-0.5">
              Started {formatDate(record.started_at)}
              {record.completed_at && ` · Completed ${formatDate(record.completed_at)}`}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {overall === 'complete' && <Badge variant="success" dot>Fully Onboarded</Badge>}
          {overall === 'partial' && <Badge variant="warning" dot>In Progress</Badge>}
          {overall === 'pending' && <Badge variant="default" dot>Not Started</Badge>}
        </div>
      </div>

      {/* ── Body ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5 items-start">

        {/* ── Left: Steps (60%) ─────────────────────────────────── */}
        <div className="lg:col-span-3 space-y-3">

          {/* Step 1 — Consent Form */}
          <StepCard number={1} icon={<Scroll className="w-4 h-4" />} title="Consent Form" status={consentStatus}>
            {consentStatus === 'pending' && (
              <ActionButton
                onClick={() => doAction('consent', `/api/data/onboarding/${id}/send-consent`)}
                loading={actionLoading['consent']}
              >
                <Send className="w-3.5 h-3.5" />
                Send Consent Form
              </ActionButton>
            )}
            {consentStatus === 'sent' && (
              <div className="flex items-center gap-2 text-sm dark:text-white/50 text-gray-500">
                <Clock className="w-4 h-4 text-blue-400" />
                Awaiting driver signature...
              </div>
            )}
            {consentStatus === 'complete' && (
              <div className="flex items-center gap-2 text-sm text-emerald-400">
                <Check className="w-4 h-4" />
                Consent form signed
              </div>
            )}
          </StepCard>

          {/* Step 2 — Priority Solutions */}
          <StepCard number={2} icon={<Mail className="w-4 h-4" />} title="Priority Solutions" status={priorityStatus}>
            {priorityStatus === 'complete' ? (
              <div className="flex items-center gap-2 text-sm text-emerald-400">
                <Check className="w-4 h-4" />
                Email sent to Priority Solutions
              </div>
            ) : (
              <div className="flex items-center gap-2 text-sm dark:text-white/40 text-gray-500">
                <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0" />
                Auto-sent when the driver signs the consent form
              </div>
            )}
          </StepCard>

          {/* Step 3 — Brandon Email */}
          <StepCard number={3} icon={<Mail className="w-4 h-4" />} title="Brandon Email (FirstAlt)" status={brandonStatus}>
            {brandonStatus === 'complete' ? (
              <div className="flex items-center gap-2 text-sm text-emerald-400">
                <Check className="w-4 h-4" />
                Email sent to Brandon
              </div>
            ) : (
              <div className="space-y-2">
                <p className="text-xs dark:text-white/40 text-gray-500">
                  Generate a pre-filled email to send Brandon at FirstAlt to start the background check.
                </p>
                <ActionButton onClick={() => setShowBrandonModal(true)}>
                  <Mail className="w-3.5 h-3.5" />
                  Generate Email
                </ActionButton>
              </div>
            )}
          </StepCard>

          {/* Step 4 — BGC Check */}
          <StepCard
            number={4}
            icon={<ShieldCheck className="w-4 h-4" />}
            title="BGC Check"
            status={bgcStatus === 'complete' ? 'complete' : 'manual'}
            isManual
            manualNote="Brandon at FirstAlt triggers this after receiving your email. Mark complete once BGC results come back clear."
          >
            {bgcStatus === 'complete' ? (
              <div className="flex items-center gap-2 text-sm text-emerald-400">
                <Check className="w-4 h-4" />
                BGC check complete
              </div>
            ) : (
              <ActionButton
                onClick={() => doAction('bgc', `/api/data/onboarding/${id}/mark-bgc-sent`)}
                loading={actionLoading['bgc']}
                variant="secondary"
              >
                <Wrench className="w-3.5 h-3.5" />
                Mark Complete
              </ActionButton>
            )}
          </StepCard>

          {/* Step 5 — Drug Test */}
          <StepCard
            number={5}
            icon={<FlaskConical className="w-4 h-4" />}
            title="Drug Test"
            status={drugStatus === 'complete' ? 'complete' : 'manual'}
            isManual
            manualNote="Call or email Dona to confirm results. Mark complete once results come back clear."
          >
            {drugStatus === 'complete' ? (
              <div className="flex items-center gap-2 text-sm text-emerald-400">
                <Check className="w-4 h-4" />
                Drug test complete
              </div>
            ) : (
              <ActionButton
                onClick={() => doAction('drug', `/api/data/onboarding/${id}/mark-drug-test-done`)}
                loading={actionLoading['drug']}
                variant="secondary"
              >
                <Wrench className="w-3.5 h-3.5" />
                Mark Complete
              </ActionButton>
            )}
          </StepCard>

          {/* Step 6 — Acumen Contract */}
          <StepCard number={6} icon={<FileText className="w-4 h-4" />} title="Acumen Contract" status={contractStatus}>
            {contractStatus === 'pending' && (
              <ActionButton
                onClick={() => doAction('contract', `/api/data/onboarding/${id}/send-contract`)}
                loading={actionLoading['contract']}
              >
                <Send className="w-3.5 h-3.5" />
                Send Contract
              </ActionButton>
            )}
            {contractStatus === 'sent' && (
              <div className="flex items-center gap-2 text-sm dark:text-white/50 text-gray-500">
                <Clock className="w-4 h-4 text-blue-400" />
                Awaiting driver signature...
              </div>
            )}
            {contractStatus === 'complete' && (
              <div className="flex items-center gap-2 text-sm text-emerald-400">
                <Check className="w-4 h-4" />
                Contract signed
              </div>
            )}
          </StepCard>

          {/* Step 7 — File Upload */}
          <StepCard number={7} icon={<FolderOpen className="w-4 h-4" />} title="File Upload" status={filesStatus}>
            <div className="mb-3">
              <span className="text-xs dark:text-white/40 text-gray-500">
                {uploadedCount} of 3 files uploaded
              </span>
            </div>
            <div className="rounded-xl dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 px-3 divide-y dark:divide-white/8 divide-gray-100">
              <FileSlot fileType="drivers_license" file={licenseFile} recordId={id} onUploaded={fetchRecord} />
              <FileSlot fileType="vehicle_registration" file={regFile} recordId={id} onUploaded={fetchRecord} />
              <FileSlot fileType="inspection" file={inspFile} recordId={id} onUploaded={fetchRecord} />
            </div>
          </StepCard>

          {/* Step 8 — Paychex */}
          <StepCard number={8} icon={<Wallet className="w-4 h-4" />} title="Paychex" status={paychexStatus}>
            {paychexStatus === 'complete' ? (
              <div className="flex items-center gap-2 text-sm text-emerald-400">
                <Check className="w-4 h-4" />
                Added to Paychex
              </div>
            ) : (
              <div className="space-y-2">
                <p className="text-xs dark:text-white/40 text-gray-500">
                  Use the Export CSV button on the main onboarding page to get this driver&apos;s data ready before adding to Paychex.
                </p>
                <ActionButton
                  onClick={() => doAction('paychex', `/api/data/onboarding/${id}/mark-paychex-done`)}
                  loading={actionLoading['paychex']}
                >
                  <Check className="w-3.5 h-3.5" />
                  Mark Added to Paychex
                </ActionButton>
              </div>
            )}
          </StepCard>

        </div>

        {/* ── Right: Driver Info (40%) ───────────────────────────── */}
        <div className="lg:col-span-2 space-y-4 lg:sticky lg:top-6">

          {/* Driver Info Card */}
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.02] bg-white p-5"
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold dark:text-white text-gray-900">Driver Info</h3>
              <Link
                href={`/people?search=${encodeURIComponent(record.person_name)}`}
                className="flex items-center gap-1.5 text-xs text-[#667eea] hover:text-[#7c93f0] transition-colors"
              >
                View profile
                <ExternalLink className="w-3 h-3" />
              </Link>
            </div>
            <div className="divide-y dark:divide-white/8 divide-gray-100">
              <InfoRow icon={<User className="w-3.5 h-3.5" />} label="Full Name" value={record.person_name} />
              <InfoRow icon={<Phone className="w-3.5 h-3.5" />} label="Phone" value={record.person_phone} />
              <InfoRow icon={<Mail className="w-3.5 h-3.5" />} label="Email" value={record.person_email} />
              <InfoRow icon={<MapPin className="w-3.5 h-3.5" />} label="Address" value={record.person_address} />
              <InfoRow icon={<Car className="w-3.5 h-3.5" />} label="Vehicle" value={record.person_vehicle} />
              <LanguageSelector
                personId={record.person_id}
                current={personLanguage}
                onChange={setPersonLanguage}
              />
            </div>
          </motion.div>

          {/* Notes Card */}
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.02] bg-white p-5"
          >
            <h3 className="text-sm font-semibold dark:text-white text-gray-900 mb-3">Notes</h3>
            <InlineNoteEdit
              recordId={id}
              value={record.notes || ''}
              onSave={v => setRecord(prev => prev ? { ...prev, notes: v } : prev)}
            />
          </motion.div>

          {/* Progress Summary Card */}
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.02] bg-white p-5"
          >
            <h3 className="text-sm font-semibold dark:text-white text-gray-900 mb-4">Progress</h3>

            <div className="space-y-2 mb-4">
              {[
                { label: 'Consent Form', status: consentStatus },
                { label: 'Priority Solutions', status: priorityStatus },
                { label: 'Brandon Email', status: brandonStatus },
                { label: 'BGC Check', status: bgcStatus },
                { label: 'Drug Test', status: drugStatus },
                { label: 'Acumen Contract', status: contractStatus },
                { label: 'Files', status: filesStatus },
                { label: 'Paychex', status: paychexStatus },
              ].map(({ label, status }) => (
                <div key={label} className="flex items-center justify-between">
                  <span className="text-xs dark:text-white/50 text-gray-600">{label}</span>
                  <div className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${
                    status === 'complete'
                      ? 'bg-emerald-500/20 text-emerald-400'
                      : status === 'sent'
                      ? 'bg-blue-500/20 text-blue-400'
                      : status === 'partial'
                      ? 'bg-amber-500/20 text-amber-400'
                      : 'dark:bg-white/8 bg-gray-100 dark:text-white/20 text-gray-300'
                  }`}>
                    {status === 'complete' && <Check className="w-2.5 h-2.5" />}
                    {status === 'sent' && <Clock className="w-2.5 h-2.5" />}
                    {status === 'partial' && <AlertCircle className="w-2.5 h-2.5" />}
                    {(status === 'pending' || status === 'manual') && (
                      <div className="w-1.5 h-1.5 rounded-full dark:bg-white/20 bg-gray-300" />
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Progress bar */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs dark:text-white/30 text-gray-400">{doneCount} of 8 complete</span>
                <span className="text-xs font-semibold dark:text-white/60 text-gray-600">{progressPct}%</span>
              </div>
              <div className="h-1.5 rounded-full dark:bg-white/8 bg-gray-100 overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${progressPct}%` }}
                  transition={{ duration: 0.7, ease: 'easeOut', delay: 0.35 }}
                  className="h-full rounded-full"
                  style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
                />
              </div>
            </div>
          </motion.div>

        </div>
      </div>

      {/* ── Brandon Email Modal ────────────────────────────────── */}
      <AnimatePresence>
        {showBrandonModal && (
          <BrandonEmailModal
            recordId={id}
            onClose={() => setShowBrandonModal(false)}
            onMarkedSent={() => {
              setShowBrandonModal(false)
              fetchRecord()
            }}
          />
        )}
      </AnimatePresence>

    </div>
  )
}
