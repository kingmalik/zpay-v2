'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { ArrowLeft, Save } from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'
import { SOPRow, Role } from '@/lib/teamos'

export default function NewSOPPage() {
  const router = useRouter()
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [form, setForm] = useState({
    title: '',
    category: '',
    owner_role: 'operator' as Role,
    trigger_when: '',
    content: '',
  })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setSaving(true)
    try {
      const created = await api.post<SOPRow>('/sops', {
        title: form.title,
        category: form.category || null,
        owner_role: form.owner_role,
        trigger_when: form.trigger_when || null,
        content: form.content,
      })
      router.push(`/sops/${created.sop_id}`)
    } catch (e: unknown) {
      setErr((e as Error).message || 'Failed to create SOP')
      setSaving(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="max-w-3xl mx-auto px-4 py-6 md:py-10 space-y-6"
    >
      <Link
        href="/sops"
        className="inline-flex items-center gap-1 text-sm dark:text-white/60 text-gray-600 dark:hover:text-white hover:text-gray-900"
      >
        <ArrowLeft className="w-4 h-4" /> Back to SOPs
      </Link>

      <div>
        <h1 className="text-2xl md:text-3xl font-bold dark:text-white text-gray-900">
          New SOP
        </h1>
        <p className="text-sm dark:text-white/50 text-gray-500">
          Write it once. Everyone follows the same playbook.
        </p>
      </div>

      {err && (
        <div className="p-3 rounded-lg border border-red-500/30 bg-red-500/10 text-red-500 text-sm">
          {err}
        </div>
      )}

      <form onSubmit={submit}>
        <GlassCard>
          <div className="space-y-3">
            <Field label="Title" required>
              <input
                type="text"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                required
                placeholder="e.g. Weekly Payroll Run"
                className={inputCls}
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Category">
                <input
                  type="text"
                  value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })}
                  placeholder="Payroll, Compliance…"
                  className={inputCls}
                />
              </Field>
              <Field label="Owner role">
                <select
                  value={form.owner_role}
                  onChange={(e) => setForm({ ...form, owner_role: e.target.value as Role })}
                  className={inputCls}
                >
                  <option value="admin">Admin</option>
                  <option value="operator">Operator</option>
                  <option value="associate">Associate</option>
                </select>
              </Field>
            </div>

            <Field label="Trigger when">
              <input
                type="text"
                value={form.trigger_when}
                onChange={(e) => setForm({ ...form, trigger_when: e.target.value })}
                placeholder="e.g. Every Friday morning"
                className={inputCls}
              />
            </Field>

            <Field label="Content (markdown)" required>
              <textarea
                value={form.content}
                onChange={(e) => setForm({ ...form, content: e.target.value })}
                rows={16}
                required
                placeholder="# Steps&#10;1. …&#10;2. …"
                className={`${inputCls} font-mono text-xs`}
              />
            </Field>
          </div>

          <div className="flex justify-end gap-2 mt-4">
            <Link
              href="/sops"
              className="px-4 py-2 rounded-lg text-sm dark:text-white/60 text-gray-600 dark:hover:bg-white/[0.07] hover:bg-gray-100"
            >
              Cancel
            </Link>
            <button
              type="submit"
              disabled={saving || !form.title.trim() || !form.content.trim()}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-[#667eea] to-[#764ba2] text-white disabled:opacity-50 cursor-pointer inline-flex items-center gap-1"
            >
              <Save className="w-4 h-4" />
              {saving ? 'Creating…' : 'Create SOP'}
            </button>
          </div>
        </GlassCard>
      </form>
    </motion.div>
  )
}

function Field({
  label,
  required,
  children,
}: {
  label: string
  required?: boolean
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium dark:text-white/60 text-gray-600 mb-1.5 block">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </span>
      {children}
    </label>
  )
}

const inputCls =
  'w-full px-3 py-2 rounded-lg text-sm dark:bg-white/[0.04] bg-white border dark:border-white/[0.1] border-gray-200 dark:text-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#667eea]/50'
