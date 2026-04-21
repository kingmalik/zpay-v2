'use client'

import { useEffect, useState, useMemo, useCallback } from 'react'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { BookOpen, Plus, Search, Tag, AlertCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import EmptyState from '@/components/ui/EmptyState'
import PageHeader from '@/components/ui/PageHeader'
import { primaryBtn, inputCls } from '@/lib/styles'
import { SOPRow, Role } from '@/lib/teamos'

interface Me { role?: Role }

export default function SOPsPage() {
  const [me, setMe] = useState<Me | null>(null)
  const [sops, setSops] = useState<SOPRow[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [meData, list] = await Promise.all([
        api.get<Me>('/users/me'),
        api.get<SOPRow[]>('/sops'),
      ])
      setMe(meData)
      setSops(list)
    } catch (e: unknown) {
      setErr((e as Error).message || 'Failed to load SOPs')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const canManage = me?.role === 'admin' || me?.role === 'operator'

  const categories = useMemo(
    () => Array.from(new Set(sops.map((s) => s.category).filter(Boolean))) as string[],
    [sops]
  )

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim()
    return sops.filter((s) => {
      if (category && s.category !== category) return false
      if (!q) return true
      return (
        s.title.toLowerCase().includes(q) ||
        (s.trigger_when || '').toLowerCase().includes(q) ||
        s.content.toLowerCase().includes(q)
      )
    })
  }, [sops, query, category])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="max-w-5xl mx-auto px-4 py-6 md:py-10 space-y-6"
    >
      <PageHeader
        title="SOP Library"
        subtitle="How we do things at MAZ. Write it once, never re-explain."
        icon={<BookOpen className="w-4 h-4" />}
        actions={canManage ? (
          <Link href="/sops/new" className={cn(primaryBtn, 'inline-flex items-center gap-2 px-4 py-2 text-sm')}>
            <Plus className="w-4 h-4" />
            New SOP
          </Link>
        ) : undefined}
      />

      {err && (
        <div className="flex gap-2 p-3 rounded-lg border border-red-500/30 bg-red-500/10 text-red-500 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{err}</span>
        </div>
      )}

      {/* Search + category */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/40 text-gray-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search SOPs…"
            className={cn(inputCls, 'pl-9')}
          />
        </div>
        {categories.length > 0 && (
          <div className="flex gap-1 overflow-x-auto">
            <Chip
              label="All"
              active={category === null}
              onClick={() => setCategory(null)}
            />
            {categories.map((c) => (
              <Chip
                key={c}
                label={c}
                active={category === c}
                onClick={() => setCategory(c)}
              />
            ))}
          </div>
        )}
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={<BookOpen className="w-8 h-8" />}
          title="No SOPs match"
          subtitle={
            sops.length === 0 && canManage
              ? 'Create the first SOP to start the library.'
              : 'Try a different search or category.'
          }
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {filtered.map((s) => (
            <Link key={s.sop_id} href={`/sops/${s.sop_id}`} className="block group">
              <GlassCard className="h-full transition-all group-hover:-translate-y-0.5">
                <div className="flex items-start justify-between gap-3 mb-1">
                  <h3 className="font-semibold dark:text-white text-gray-900">
                    {s.title}
                  </h3>
                  <span className="text-[10px] dark:text-white/40 text-gray-400 whitespace-nowrap">
                    v{s.version}
                  </span>
                </div>
                {s.category && (
                  <div className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded dark:bg-white/[0.05] bg-gray-100 dark:text-white/60 text-gray-600 mb-2">
                    <Tag className="w-2.5 h-2.5" />
                    {s.category}
                  </div>
                )}
                {s.trigger_when && (
                  <p className="text-xs dark:text-white/50 text-gray-500 line-clamp-2">
                    {s.trigger_when}
                  </p>
                )}
              </GlassCard>
            </Link>
          ))}
        </div>
      )}
    </motion.div>
  )
}

function Chip({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all cursor-pointer ${
        active
          ? 'bg-[#667eea]/15 text-[#667eea]'
          : 'dark:bg-white/[0.04] bg-gray-100 dark:text-white/60 text-gray-600 dark:hover:bg-white/[0.07] hover:bg-gray-200'
      }`}
    >
      {label}
    </button>
  )
}
