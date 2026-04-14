'use client'

import { use, useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { ArrowLeft, Edit3, Archive, Send, Check, Tag, AlertCircle, Save, X } from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { SOPDetail, Role } from '@/lib/teamos'

interface Me { role?: Role }

export default function SOPDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const sopId = Number(id)
  const router = useRouter()

  const [me, setMe] = useState<Me | null>(null)
  const [sop, setSop] = useState<SOPDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [savingEdit, setSavingEdit] = useState(false)
  const [editForm, setEditForm] = useState({
    title: '', category: '', owner_role: 'operator' as Role, trigger_when: '', content: '',
  })

  const [newNote, setNewNote] = useState('')
  const [posting, setPosting] = useState(false)

  const load = useCallback(async () => {
    try {
      const [meData, detail] = await Promise.all([
        api.get<Me>('/users/me'),
        api.get<SOPDetail>(`/sops/${sopId}`),
      ])
      setMe(meData)
      setSop(detail)
      setEditForm({
        title: detail.title,
        category: detail.category || '',
        owner_role: detail.owner_role,
        trigger_when: detail.trigger_when || '',
        content: detail.content,
      })
    } catch (e: unknown) {
      setErr((e as Error).message || 'Failed to load SOP')
    } finally {
      setLoading(false)
    }
  }, [sopId])

  useEffect(() => { load() }, [load])

  const canManage = me?.role === 'admin' || me?.role === 'operator'

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!sop) return
    setSavingEdit(true)
    try {
      const updated = await api.patch<SOPDetail>(`/sops/${sop.sop_id}`, {
        title: editForm.title,
        category: editForm.category || null,
        owner_role: editForm.owner_role,
        trigger_when: editForm.trigger_when || null,
        content: editForm.content,
      })
      setSop({ ...sop, ...updated })
      setEditing(false)
    } catch (e: unknown) {
      alert((e as Error).message || 'Save failed')
    } finally {
      setSavingEdit(false)
    }
  }

  async function toggleArchive() {
    if (!sop) return
    if (!confirm(sop.archived ? 'Unarchive this SOP?' : 'Archive this SOP?')) return
    try {
      const r = await api.post<{ archived: boolean }>(`/sops/${sop.sop_id}/archive`)
      setSop({ ...sop, archived: r.archived })
      if (r.archived) router.push('/sops')
    } catch (e: unknown) {
      alert((e as Error).message || 'Failed')
    }
  }

  async function addNote(e: React.FormEvent) {
    e.preventDefault()
    if (!sop || !newNote.trim()) return
    setPosting(true)
    try {
      const note = await api.post<SOPDetail['field_notes'][number]>(
        `/sops/${sop.sop_id}/notes`,
        { note: newNote.trim() }
      )
      setSop({ ...sop, field_notes: [note, ...sop.field_notes] })
      setNewNote('')
    } catch (e: unknown) {
      alert((e as Error).message || 'Post failed')
    } finally {
      setPosting(false)
    }
  }

  async function promoteNote(noteId: number) {
    if (!sop) return
    try {
      await api.post(`/sops/notes/${noteId}/promote`)
      setSop({
        ...sop,
        field_notes: sop.field_notes.map((n) =>
          n.id === noteId ? { ...n, promoted: true } : n
        ),
      })
    } catch (e: unknown) {
      alert((e as Error).message || 'Failed')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner />
      </div>
    )
  }

  if (err || !sop) {
    return (
      <div className="max-w-2xl mx-auto p-6">
        <Link href="/sops" className="inline-flex items-center gap-1 text-sm dark:text-white/60 text-gray-600 mb-4">
          <ArrowLeft className="w-4 h-4" /> Back to SOPs
        </Link>
        <div className="p-3 rounded-lg border border-red-500/30 bg-red-500/10 text-red-500 text-sm">
          {err || 'SOP not found'}
        </div>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="max-w-3xl mx-auto px-4 py-6 md:py-10 space-y-6"
    >
      <Link href="/sops" className="inline-flex items-center gap-1 text-sm dark:text-white/60 text-gray-600 dark:hover:text-white hover:text-gray-900">
        <ArrowLeft className="w-4 h-4" /> Back to SOPs
      </Link>

      {editing ? (
        <form onSubmit={saveEdit}>
          <GlassCard>
            <div className="space-y-3">
              <Input label="Title" value={editForm.title} onChange={(v) => setEditForm({ ...editForm, title: v })} required />
              <div className="grid grid-cols-2 gap-3">
                <Input label="Category" value={editForm.category} onChange={(v) => setEditForm({ ...editForm, category: v })} />
                <Field label="Owner role">
                  <select
                    value={editForm.owner_role}
                    onChange={(e) => setEditForm({ ...editForm, owner_role: e.target.value as Role })}
                    className={inputCls}
                  >
                    <option value="admin">Admin</option>
                    <option value="operator">Operator</option>
                    <option value="associate">Associate</option>
                  </select>
                </Field>
              </div>
              <Input label="Trigger when" value={editForm.trigger_when} onChange={(v) => setEditForm({ ...editForm, trigger_when: v })} />
              <Field label="Content (markdown)">
                <textarea
                  value={editForm.content}
                  onChange={(e) => setEditForm({ ...editForm, content: e.target.value })}
                  rows={14}
                  className={`${inputCls} font-mono text-xs`}
                  required
                />
              </Field>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="px-4 py-2 rounded-lg text-sm dark:text-white/60 text-gray-600 dark:hover:bg-white/[0.07] hover:bg-gray-100 cursor-pointer inline-flex items-center gap-1"
              >
                <X className="w-4 h-4" /> Cancel
              </button>
              <button
                type="submit"
                disabled={savingEdit}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-[#667eea] to-[#764ba2] text-white disabled:opacity-50 cursor-pointer inline-flex items-center gap-1"
              >
                <Save className="w-4 h-4" />
                {savingEdit ? 'Saving…' : 'Save'}
              </button>
            </div>
          </GlassCard>
        </form>
      ) : (
        <>
          <GlassCard>
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <h1 className="text-xl md:text-2xl font-bold dark:text-white text-gray-900">
                  {sop.title}
                </h1>
                <div className="flex flex-wrap items-center gap-2 mt-2">
                  {sop.category && (
                    <span className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded dark:bg-white/[0.05] bg-gray-100 dark:text-white/60 text-gray-600">
                      <Tag className="w-2.5 h-2.5" />
                      {sop.category}
                    </span>
                  )}
                  <span className="text-[10px] dark:text-white/40 text-gray-400">
                    v{sop.version} · owner: {sop.owner_role}
                  </span>
                  {sop.archived && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-500">
                      ARCHIVED
                    </span>
                  )}
                </div>
                {sop.trigger_when && (
                  <p className="mt-2 text-sm dark:text-white/70 text-gray-600 italic">
                    When: {sop.trigger_when}
                  </p>
                )}
              </div>
              {canManage && (
                <div className="flex gap-1">
                  <button
                    onClick={() => setEditing(true)}
                    className="p-2 rounded-lg dark:text-white/60 text-gray-600 dark:hover:bg-white/[0.07] hover:bg-gray-100 cursor-pointer"
                    title="Edit"
                  >
                    <Edit3 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={toggleArchive}
                    className="p-2 rounded-lg text-amber-500 hover:bg-amber-500/10 cursor-pointer"
                    title={sop.archived ? 'Unarchive' : 'Archive'}
                  >
                    <Archive className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>

            <div className="mt-5 prose-invert text-sm dark:text-white/80 text-gray-700 whitespace-pre-wrap">
              {sop.content}
            </div>
          </GlassCard>

          {/* Field notes */}
          <GlassCard>
            <h2 className="font-semibold dark:text-white text-gray-900 mb-1">
              Notes from the field
            </h2>
            <p className="text-xs dark:text-white/50 text-gray-500 mb-4">
              Anyone can leave a note. Admin/operator can promote useful ones.
            </p>

            {sop.field_notes.length === 0 ? (
              <p className="text-sm dark:text-white/40 text-gray-400 italic mb-4">
                No notes yet. If you spot something missing or out of date, drop it here.
              </p>
            ) : (
              <div className="space-y-3 mb-4">
                {sop.field_notes.map((n) => (
                  <div
                    key={n.id}
                    className={`p-3 rounded-lg border ${
                      n.promoted
                        ? 'border-emerald-500/30 bg-emerald-500/5'
                        : 'dark:border-white/[0.08] border-gray-200 dark:bg-white/[0.02]'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      {n.author && (
                        <div
                          className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold text-white"
                          style={{ backgroundColor: n.author.color }}
                        >
                          {n.author.initials}
                        </div>
                      )}
                      <span className="text-xs font-medium dark:text-white/80 text-gray-700">
                        {n.author?.display_name || 'Someone'}
                      </span>
                      <span className="text-[10px] dark:text-white/40 text-gray-400">
                        {n.created_at ? new Date(n.created_at).toLocaleString() : ''}
                      </span>
                      {n.promoted && (
                        <span className="text-[10px] text-emerald-500 inline-flex items-center gap-0.5">
                          <Check className="w-2.5 h-2.5" />
                          Promoted
                        </span>
                      )}
                    </div>
                    <p className="text-sm dark:text-white/80 text-gray-700 whitespace-pre-wrap">
                      {n.note}
                    </p>
                    {!n.promoted && canManage && (
                      <button
                        onClick={() => promoteNote(n.id)}
                        className="mt-2 text-[11px] text-emerald-500 hover:underline cursor-pointer"
                      >
                        Mark promoted
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            <form onSubmit={addNote} className="space-y-2">
              <textarea
                value={newNote}
                onChange={(e) => setNewNote(e.target.value)}
                rows={3}
                placeholder="Drop a field note — edge case, correction, tip…"
                className={inputCls}
              />
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={!newNote.trim() || posting}
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-[#667eea] to-[#764ba2] text-white disabled:opacity-50 cursor-pointer inline-flex items-center gap-1"
                >
                  <Send className="w-4 h-4" />
                  {posting ? 'Posting…' : 'Add note'}
                </button>
              </div>
            </form>
          </GlassCard>
        </>
      )}
    </motion.div>
  )
}

function Input({ label, value, onChange, required }: { label: string; value: string; onChange: (v: string) => void; required?: boolean }) {
  return (
    <Field label={label}>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        className={inputCls}
      />
    </Field>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-medium dark:text-white/60 text-gray-600 mb-1.5 block">
        {label}
      </span>
      {children}
    </label>
  )
}

const inputCls =
  'w-full px-3 py-2 rounded-lg text-sm dark:bg-white/[0.04] bg-white border dark:border-white/[0.1] border-gray-200 dark:text-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#667eea]/50'
