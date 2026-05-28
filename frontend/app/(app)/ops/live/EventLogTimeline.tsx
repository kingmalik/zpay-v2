'use client'

import { useCallback, useEffect, useState } from 'react'
import { History, RefreshCw, AlertTriangle, Activity } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

type EventSeverity = 'critical' | 'urgent' | 'normal' | 'silent' | string

interface EventLogRow {
  id: number
  severity: EventSeverity
  title: string
  message: string
  trip_id: string | null
  notif_id: number | null
  source: string | null
  created_at: string | null
}

interface EventLogResponse {
  events: EventLogRow[]
  count: number
  generated_at: string
}

type SeverityFilter = 'all' | 'critical' | 'urgent' | 'normal' | 'silent'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatRelative(iso: string | null): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  const now = Date.now()
  const seconds = Math.max(0, Math.floor((now - then) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function formatClock(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

interface SeverityStyle {
  ring: string
  text: string
  bg: string
  dot: string
  label: string
}

function severityStyle(sev: EventSeverity): SeverityStyle {
  switch (sev) {
    case 'critical':
      return {
        ring: 'border-red-500/30',
        text: 'text-red-300',
        bg: 'bg-red-500/[0.06]',
        dot: 'bg-red-500',
        label: 'CRITICAL',
      }
    case 'urgent':
      return {
        ring: 'border-amber-500/30',
        text: 'text-amber-300',
        bg: 'bg-amber-500/[0.06]',
        dot: 'bg-amber-500',
        label: 'URGENT',
      }
    case 'normal':
      return {
        ring: 'border-sky-500/25',
        text: 'text-sky-300',
        bg: 'bg-sky-500/[0.05]',
        dot: 'bg-sky-500',
        label: 'NORMAL',
      }
    case 'silent':
      return {
        ring: 'border-white/10',
        text: 'text-white/55',
        bg: 'bg-white/[0.03]',
        dot: 'bg-white/40',
        label: 'SILENT',
      }
    default:
      return {
        ring: 'border-white/10',
        text: 'text-white/55',
        bg: 'bg-white/[0.03]',
        dot: 'bg-white/40',
        label: sev.toUpperCase(),
      }
  }
}

const FILTERS: { key: SeverityFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'critical', label: 'Critical' },
  { key: 'urgent', label: 'Urgent' },
  { key: 'normal', label: 'Normal' },
  { key: 'silent', label: 'Silent' },
]

// ── Component ─────────────────────────────────────────────────────────────────

export default function EventLogTimeline() {
  const [rows, setRows] = useState<EventLogRow[]>([])
  const [filter, setFilter] = useState<SeverityFilter>('all')
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [generatedAt, setGeneratedAt] = useState<string | null>(null)

  const fetchEvents = useCallback(async (active: SeverityFilter) => {
    setError(null)
    try {
      const sevParam = active === 'all' ? '' : `&severity=${active}`
      const data = await api.get<EventLogResponse>(`/ops-dashboard/event-log?limit=100${sevParam}`)
      setRows(data.events)
      setGeneratedAt(data.generated_at)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load event log')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    fetchEvents(filter)
  }, [filter, fetchEvents])

  // Auto-refresh every 30s
  useEffect(() => {
    const handle = setInterval(() => fetchEvents(filter), 30_000)
    return () => clearInterval(handle)
  }, [filter, fetchEvents])

  return (
    <div className="rounded-2xl border border-white/[0.07] bg-white/[0.02] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-white/[0.05]">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-white/60" />
          <span className="text-sm font-semibold text-white/85">Event Timeline</span>
          <span className="text-xs text-white/40">
            {loading ? 'loading…' : `${rows.length} entries · refreshed ${formatRelative(generatedAt)}`}
          </span>
        </div>

        <div className="flex items-center gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                'px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all cursor-pointer',
                filter === f.key
                  ? 'bg-white/[0.10] text-white/90 border border-white/15'
                  : 'text-white/45 hover:text-white/75 border border-transparent',
              )}
            >
              {f.label}
            </button>
          ))}
          <button
            onClick={() => fetchEvents(filter)}
            title="Refresh"
            className="ml-1 p-1.5 rounded-lg text-white/40 hover:text-white/75 hover:bg-white/[0.06] transition-all cursor-pointer"
          >
            <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="max-h-[480px] overflow-y-auto">
        {error && (
          <div className="flex items-center gap-2 px-4 py-3 text-xs text-red-400 bg-red-500/[0.06] border-b border-red-500/[0.15]">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            {error}
          </div>
        )}

        {!error && rows.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-white/35">
            <Activity className="w-5 h-5" />
            <div className="text-xs">No events in this window.</div>
          </div>
        )}

        <ul className="divide-y divide-white/[0.04]">
          {rows.map((row) => {
            const sty = severityStyle(row.severity)
            return (
              <li key={row.id} className={cn('px-4 py-3 flex gap-3', sty.bg)}>
                <div className="flex flex-col items-center pt-1">
                  <span className={cn('w-2 h-2 rounded-full', sty.dot)} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className={cn('text-[10px] font-bold tracking-wider', sty.text)}>
                      {sty.label}
                    </span>
                    <span className="text-sm font-semibold text-white/90 truncate">
                      {row.title}
                    </span>
                    <span className="text-[11px] text-white/35 ml-auto whitespace-nowrap">
                      {formatClock(row.created_at)} · {formatRelative(row.created_at)}
                    </span>
                  </div>
                  <div className="mt-0.5 text-xs text-white/55 leading-snug whitespace-pre-wrap break-words">
                    {row.message}
                  </div>
                  <div className="mt-1 flex items-center gap-3 text-[10px] text-white/30">
                    {row.source && <span>src: {row.source}</span>}
                    {row.trip_id && <span>trip: {row.trip_id}</span>}
                    {row.notif_id != null && <span>notif: {row.notif_id}</span>}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
