'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft, Copy, Merge, AlertCircle, UserMinus,
  Upload, CheckCircle2, XCircle, Loader2, Play, Eye,
} from 'lucide-react'
import Link from 'next/link'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'
import Badge from '@/components/ui/Badge'

// ─── Toast ───────────────────────────────────────────────────────────────────

function Toast({ message, type, onDone }: { message: string; type: 'success' | 'error'; onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 3500)
    return () => clearTimeout(t)
  }, [onDone])
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      className={`fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 rounded-xl text-sm font-medium shadow-xl border backdrop-blur-xl ${
        type === 'success'
          ? 'dark:bg-emerald-500/20 bg-emerald-50 border-emerald-500/30 text-emerald-400 dark:text-emerald-300'
          : 'dark:bg-red-500/20 bg-red-50 border-red-500/30 text-red-400 dark:text-red-300'
      }`}
    >
      {type === 'success' ? <CheckCircle2 className="w-4 h-4 flex-shrink-0" /> : <XCircle className="w-4 h-4 flex-shrink-0" />}
      {message}
    </motion.div>
  )
}

function useToast() {
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null)
  const show = useCallback((message: string, type: 'success' | 'error' = 'success') => {
    setToast({ message, type })
  }, [])
  const clear = useCallback(() => setToast(null), [])
  return { toast, show, clear }
}

// ─── Tab button ──────────────────────────────────────────────────────────────

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-xl text-sm font-medium transition-all cursor-pointer ${
        active
          ? 'text-white'
          : 'dark:text-white/50 text-gray-500 dark:hover:text-white/80 hover:text-gray-700'
      }`}
      style={active ? { background: 'linear-gradient(135deg, #667eea, #06b6d4)' } : {}}
    >
      {children}
    </button>
  )
}

// ─── Types ───────────────────────────────────────────────────────────────────

interface AuditPerson {
  id: number
  name: string
  fa_id?: string | number
  ed_id?: string | number
  paycheck_code?: string
  phone?: string
}

interface DuplicatePair {
  person_a: AuditPerson
  person_b: AuditPerson
  similarity: number
  reason: string
}

interface MissingPerson {
  person_id: number
  name: string
  missing_fields: string[]
  phone?: string
  email?: string
  paycheck_code?: string
  ed_id?: string | number
}

interface ImportResult {
  updated: number
  unmatched: string[]
}

interface AutoInactivateResult {
  inactivated: string[]
  count: number
}

// ─── Tab 1: Duplicates ────────────────────────────────────────────────────────

function DuplicatesTab({ showToast }: { showToast: (msg: string, type?: 'success' | 'error') => void }) {
  const [pairs, setPairs] = useState<DuplicatePair[]>([])
  const [loading, setLoading] = useState(true)
  const [merging, setMerging] = useState<string | null>(null)

  useEffect(() => {
    api.get<DuplicatePair[]>('/people/audit/duplicates')
      .then(setPairs)
      .catch(() => showToast('Failed to load duplicates', 'error'))
      .finally(() => setLoading(false))
  }, [showToast])

  async function merge(keepId: number, removeId: number, pairKey: string) {
    setMerging(pairKey)
    try {
      await api.post('/people/audit/merge', { keep_id: keepId, remove_id: removeId })
      setPairs(prev => prev.filter(p => !(p.person_a.id === keepId || p.person_a.id === removeId || p.person_b.id === keepId || p.person_b.id === removeId)))
      showToast('Drivers merged successfully')
    } catch {
      showToast('Failed to merge drivers', 'error')
    } finally {
      setMerging(null)
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center py-16">
      <Loader2 className="w-6 h-6 animate-spin dark:text-white/40 text-gray-400" />
    </div>
  )

  if (!pairs.length) return (
    <div className="text-center py-16">
      <CheckCircle2 className="w-10 h-10 mx-auto mb-3 text-emerald-400" />
      <p className="dark:text-white/60 text-gray-500 text-sm">No duplicate drivers found</p>
    </div>
  )

  return (
    <div className="space-y-4">
      <p className="text-sm dark:text-white/50 text-gray-500">{pairs.length} potential duplicate pair{pairs.length !== 1 ? 's' : ''} found</p>
      <AnimatePresence>
        {pairs.map((pair, i) => {
          const key = `${pair.person_a.id}-${pair.person_b.id}`
          const isMerging = merging === key
          return (
            <motion.div
              key={key}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.97 }}
              transition={{ delay: i * 0.04 }}
            >
              <GlassCard>
                <div className="flex items-start justify-between gap-4 mb-4">
                  <div className="flex items-center gap-2">
                    <Copy className="w-4 h-4 text-amber-400" />
                    <span className="text-sm font-semibold dark:text-white/80 text-gray-700">Possible Duplicate</span>
                    <Badge variant="warning">{Math.round(pair.similarity * 100)}% match</Badge>
                  </div>
                  <span className="text-xs dark:text-white/40 text-gray-400 italic">{pair.reason}</span>
                </div>

                <div className="grid grid-cols-2 gap-4 mb-4">
                  {[pair.person_a, pair.person_b].map((p, idx) => (
                    <div key={p.id} className="rounded-xl dark:bg-white/5 bg-gray-50 border dark:border-white/8 border-gray-200 p-3 space-y-1.5">
                      <p className="text-sm font-semibold dark:text-white text-gray-800">{p.name}</p>
                      <div className="space-y-0.5 text-xs dark:text-white/50 text-gray-500">
                        {p.fa_id && <p>FA: {p.fa_id}</p>}
                        {p.ed_id && <p>MDD: {p.ed_id}</p>}
                        {p.paycheck_code && <p>Pay Code: {p.paycheck_code}</p>}
                        {p.phone && <p>Phone: {p.phone}</p>}
                      </div>
                      <button
                        onClick={() => merge(p.id, idx === 0 ? pair.person_b.id : pair.person_a.id, key)}
                        disabled={!!isMerging}
                        className={`mt-2 w-full py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer disabled:opacity-50 ${
                          idx === 0
                            ? 'dark:bg-[#667eea]/20 bg-indigo-50 dark:text-[#667eea] text-indigo-600 dark:hover:bg-[#667eea]/30 hover:bg-indigo-100 border dark:border-[#667eea]/30 border-indigo-200'
                            : 'dark:bg-cyan-500/10 bg-cyan-50 dark:text-cyan-400 text-cyan-600 dark:hover:bg-cyan-500/20 hover:bg-cyan-100 border dark:border-cyan-500/20 border-cyan-200'
                        }`}
                      >
                        {isMerging ? <Loader2 className="w-3 h-3 animate-spin mx-auto" /> : `Keep ${idx === 0 ? 'A' : 'B'}`}
                      </button>
                    </div>
                  ))}
                </div>
              </GlassCard>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}

// ─── Inline editable cell ────────────────────────────────────────────────────

function EditableCell({
  value, personId, field, onSave,
}: { value: string; personId: number; field: string; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(value)
  const [saving, setSaving] = useState(false)

  async function save() {
    if (val === value) { setEditing(false); return }
    setSaving(true)
    try {
      await api.post(`/people/${personId}/edit`, { [field]: val })
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
      <input
        autoFocus
        value={val}
        onChange={e => setVal(e.target.value)}
        onBlur={save}
        onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { setVal(value); setEditing(false) } }}
        className="px-2 py-1 text-xs rounded-lg dark:bg-white/10 bg-gray-100 dark:text-white text-gray-800 border dark:border-white/20 border-gray-300 focus:outline-none focus:border-[#667eea]/60 w-28"
        disabled={saving}
      />
    )
  }

  return (
    <span
      onClick={() => setEditing(true)}
      className="cursor-pointer text-xs dark:text-white/70 text-gray-600 hover:dark:text-white hover:text-gray-900 transition-colors border-b border-dashed dark:border-white/20 border-gray-300"
      title="Click to edit"
    >
      {val || <span className="dark:text-white/30 text-gray-300 italic">—</span>}
    </span>
  )
}

// ─── Tab 2: Missing Data ──────────────────────────────────────────────────────

function MissingDataTab({ showToast }: { showToast: (msg: string, type?: 'success' | 'error') => void }) {
  const [people, setPeople] = useState<MissingPerson[]>([])
  const [loading, setLoading] = useState(true)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const [importing, setImporting] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.get<MissingPerson[]>('/people/audit/missing')
      .then(setPeople)
      .catch(() => showToast('Failed to load missing data', 'error'))
      .finally(() => setLoading(false))
  }, [showToast])

  function updateField(personId: number, field: keyof MissingPerson, value: string) {
    setPeople(prev => prev.map(p => p.person_id === personId ? { ...p, [field]: value } : p))
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    setImportResult(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await api.postForm<ImportResult>('/people/audit/import-csv', form)
      setImportResult(res)
      showToast(`Imported: ${res.updated} updated`)
    } catch {
      showToast('Import failed', 'error')
    } finally {
      setImporting(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center py-16">
      <Loader2 className="w-6 h-6 animate-spin dark:text-white/40 text-gray-400" />
    </div>
  )

  return (
    <div className="space-y-4">
      {/* Import CSV */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p className="text-sm dark:text-white/50 text-gray-500">{people.length} driver{people.length !== 1 ? 's' : ''} with missing fields</p>
        <div className="flex items-center gap-2">
          <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={handleImport} id="csv-import" />
          <label
            htmlFor="csv-import"
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium cursor-pointer transition-all dark:bg-white/5 bg-gray-100 dark:text-white/70 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-200 border dark:border-white/10 border-gray-200 ${importing ? 'opacity-60 pointer-events-none' : ''}`}
          >
            {importing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            Import CSV
          </label>
        </div>
      </div>

      {/* Import result */}
      <AnimatePresence>
        {importResult && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
          >
            <GlassCard className="!p-4">
              <div className="flex items-start gap-3">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" />
                <div className="text-sm space-y-1">
                  <p className="dark:text-white text-gray-800 font-medium">{importResult.updated} driver{importResult.updated !== 1 ? 's' : ''} updated</p>
                  {importResult.unmatched.length > 0 && (
                    <p className="text-xs dark:text-amber-400 text-amber-600">
                      Unmatched: {importResult.unmatched.join(', ')}
                    </p>
                  )}
                </div>
              </div>
            </GlassCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Table */}
      {people.length === 0 ? (
        <div className="text-center py-16">
          <CheckCircle2 className="w-10 h-10 mx-auto mb-3 text-emerald-400" />
          <p className="dark:text-white/60 text-gray-500 text-sm">All drivers have complete data</p>
        </div>
      ) : (
        <GlassCard padding={false}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b dark:border-white/8 border-gray-100">
                  {['Driver', 'Missing Fields', 'Pay Code', 'MDD / ED ID', 'Phone'].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide dark:text-white/40 text-gray-400">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {people.map((p, i) => (
                  <tr
                    key={p.person_id}
                    className={`border-b dark:border-white/5 border-gray-50 transition-colors dark:hover:bg-white/3 hover:bg-gray-50 ${i % 2 === 0 ? '' : 'dark:bg-white/2 bg-gray-50/50'}`}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-6 h-6 rounded-full bg-gradient-to-br from-[#667eea] to-[#06b6d4] flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                          {p.name?.[0]?.toUpperCase() || '?'}
                        </div>
                        <span className="font-medium dark:text-white text-gray-800 whitespace-nowrap">{p.name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {p.missing_fields.map(f => (
                          <Badge key={f} variant="warning" className="text-xs">{f}</Badge>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <EditableCell
                        value={p.paycheck_code || ''}
                        personId={p.person_id}
                        field="paycheck_code"
                        onSave={v => updateField(p.person_id, 'paycheck_code', v)}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <EditableCell
                        value={String(p.ed_id || '')}
                        personId={p.person_id}
                        field="everdriven_driver_id"
                        onSave={v => updateField(p.person_id, 'ed_id', v)}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <EditableCell
                        value={p.phone || ''}
                        personId={p.person_id}
                        field="phone"
                        onSave={v => updateField(p.person_id, 'phone', v)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}
    </div>
  )
}

// ─── Tab 3: Auto-Inactivate ───────────────────────────────────────────────────

function AutoInactivateTab({ showToast }: { showToast: (msg: string, type?: 'success' | 'error') => void }) {
  const [previewing, setPreviewing] = useState(false)
  const [running, setRunning] = useState(false)
  const [previewResult, setPreviewResult] = useState<AutoInactivateResult | null>(null)
  const [runResult, setRunResult] = useState<AutoInactivateResult | null>(null)

  async function preview() {
    setPreviewing(true)
    setPreviewResult(null)
    try {
      const res = await api.post<AutoInactivateResult>('/people/audit/auto-inactivate', { dry_run: true })
      setPreviewResult(res)
    } catch {
      showToast('Preview failed', 'error')
    } finally {
      setPreviewing(false)
    }
  }

  async function run() {
    setRunning(true)
    setRunResult(null)
    try {
      const res = await api.post<AutoInactivateResult>('/people/audit/auto-inactivate', {})
      setRunResult(res)
      showToast(`${res.count ?? res.inactivated?.length ?? 0} drivers marked inactive`)
    } catch {
      showToast('Auto-inactivate failed', 'error')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-5 max-w-2xl">
      {/* Description card */}
      <GlassCard>
        <div className="flex items-start gap-3">
          <UserMinus className="w-5 h-5 dark:text-white/50 text-gray-400 mt-0.5 flex-shrink-0" />
          <div className="space-y-1">
            <p className="text-sm font-semibold dark:text-white text-gray-800">Auto-Inactivate Rule</p>
            <p className="text-sm dark:text-white/60 text-gray-500">
              Drivers with <span className="font-semibold dark:text-white text-gray-800">no rides in the last 35 days</span> will be marked inactive.
              Use Preview to see who would be affected before committing.
            </p>
          </div>
        </div>
      </GlassCard>

      {/* Action buttons */}
      <div className="flex gap-3">
        <button
          onClick={preview}
          disabled={previewing || running}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium cursor-pointer transition-all disabled:opacity-50 dark:bg-white/5 bg-gray-100 dark:text-white/70 text-gray-600 dark:hover:bg-white/10 hover:bg-gray-200 border dark:border-white/10 border-gray-200"
        >
          {previewing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Eye className="w-4 h-4" />}
          Preview
        </button>
        <button
          onClick={run}
          disabled={running || previewing}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white cursor-pointer transition-all disabled:opacity-50"
          style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
        >
          {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Run Auto-Inactivate
        </button>
      </div>

      {/* Preview result */}
      <AnimatePresence>
        {previewResult && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <GlassCard>
              <div className="flex items-center gap-2 mb-3">
                <Eye className="w-4 h-4 text-amber-400" />
                <span className="text-sm font-semibold dark:text-white text-gray-800">
                  Preview — {previewResult.count ?? previewResult.inactivated?.length ?? 0} driver{(previewResult.count ?? previewResult.inactivated?.length ?? 0) !== 1 ? 's' : ''} would be inactivated
                </span>
                <Badge variant="warning">Dry Run</Badge>
              </div>
              {previewResult.inactivated?.length > 0 && (
                <ul className="space-y-1">
                  {previewResult.inactivated.map(name => (
                    <li key={name} className="text-xs dark:text-white/60 text-gray-500 flex items-center gap-1.5">
                      <span className="w-1 h-1 rounded-full dark:bg-white/20 bg-gray-300 flex-shrink-0" />
                      {name}
                    </li>
                  ))}
                </ul>
              )}
            </GlassCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Run result */}
      <AnimatePresence>
        {runResult && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <GlassCard>
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span className="text-sm font-semibold dark:text-white text-gray-800">
                  Done — {runResult.count ?? runResult.inactivated?.length ?? 0} driver{(runResult.count ?? runResult.inactivated?.length ?? 0) !== 1 ? 's' : ''} inactivated
                </span>
              </div>
              {runResult.inactivated?.length > 0 && (
                <ul className="space-y-1">
                  {runResult.inactivated.map(name => (
                    <li key={name} className="text-xs dark:text-white/60 text-gray-500 flex items-center gap-1.5">
                      <span className="w-1 h-1 rounded-full dark:bg-white/20 bg-gray-300 flex-shrink-0" />
                      {name}
                    </li>
                  ))}
                </ul>
              )}
            </GlassCard>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type AuditTab = 'duplicates' | 'missing' | 'auto-inactivate'

const TABS: { id: AuditTab; label: string }[] = [
  { id: 'duplicates', label: 'Duplicates' },
  { id: 'missing', label: 'Missing Data' },
  { id: 'auto-inactivate', label: 'Auto-Inactivate' },
]

export default function PeopleAuditPage() {
  const [tab, setTab] = useState<AuditTab>('duplicates')
  const { toast, show: showToast, clear: clearToast } = useToast()

  return (
    <div className="max-w-6xl mx-auto space-y-6 py-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link
          href="/people"
          className="p-2 rounded-xl dark:bg-white/5 bg-gray-100 dark:hover:bg-white/10 hover:bg-gray-200 border dark:border-white/10 border-gray-200 transition-all"
          title="Back to People"
        >
          <ArrowLeft className="w-4 h-4 dark:text-white/60 text-gray-500" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold dark:text-white text-gray-900">Driver Audit</h1>
          <p className="text-sm dark:text-white/50 text-gray-500 mt-0.5">Review duplicates, fill missing data, and clean up inactive drivers</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100 w-fit">
        {TABS.map(t => (
          <TabBtn key={t.id} active={tab === t.id} onClick={() => setTab(t.id)}>
            {t.label}
          </TabBtn>
        ))}
      </div>

      {/* Tab content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.15 }}
        >
          {tab === 'duplicates' && <DuplicatesTab showToast={showToast} />}
          {tab === 'missing' && <MissingDataTab showToast={showToast} />}
          {tab === 'auto-inactivate' && <AutoInactivateTab showToast={showToast} />}
        </motion.div>
      </AnimatePresence>

      {/* Toast */}
      <AnimatePresence>
        {toast && <Toast message={toast.message} type={toast.type} onDone={clearToast} />}
      </AnimatePresence>
    </div>
  )
}
