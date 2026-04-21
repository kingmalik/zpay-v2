'use client'

import { useEffect, useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Activity,
  RefreshCw,
  Pause,
  Play,
  Check,
  Bell,
  Zap,
  AlertTriangle,
} from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'
import PageHeader from '@/components/ui/PageHeader'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { cn } from '@/lib/utils'

type CheckStatus = 'green' | 'yellow' | 'red' | 'unknown'

interface HealthCheck {
  name: string
  status: CheckStatus
  last_checked_at: string | null
  last_ok_at: string | null
  consecutive_failures: number
  latency_ms: number
  detail: Record<string, unknown>
  enabled: boolean
  muted_until: string | null
}

interface HealthStatus {
  overall: CheckStatus
  checks: HealthCheck[]
  open_alerts: number
  scheduler: Record<string, unknown>
  server_time: string
}

interface HealthAlert {
  alert_id: number
  check_name: string
  severity: string
  message: string
  created_at: string | null
  resolved_at: string | null
  acked_at: string | null
  notified: string[]
}

const POLL_MS = 30000

function formatRelative(iso: string | null): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  const diff = Date.now() - t
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

function statusBadgeVariant(status: CheckStatus): 'success' | 'warning' | 'danger' | 'inactive' {
  if (status === 'green') return 'success'
  if (status === 'yellow') return 'warning'
  if (status === 'red') return 'danger'
  return 'inactive'
}

function statusColor(status: CheckStatus): string {
  if (status === 'green') return 'text-emerald-400'
  if (status === 'yellow') return 'text-amber-400'
  if (status === 'red') return 'text-red-400'
  return 'text-gray-400'
}

function statusDot(status: CheckStatus): string {
  if (status === 'green') return 'bg-emerald-400'
  if (status === 'yellow') return 'bg-amber-400'
  if (status === 'red') return 'bg-red-400'
  return 'bg-gray-400'
}

function prettyCheckName(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export default function HealthPage() {
  const [status, setStatus] = useState<HealthStatus | null>(null)
  const [alerts, setAlerts] = useState<HealthAlert[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function refresh() {
    try {
      const [s, a] = await Promise.all([
        api.get<HealthStatus>('/api/data/health/status'),
        api.get<{ alerts: HealthAlert[] }>('/api/data/health/alerts?limit=25'),
      ])
      setStatus(s)
      setAlerts(a.alerts || [])
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    pollRef.current = setInterval(refresh, POLL_MS)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  async function runCheck(name: string) {
    setBusy(`run:${name}`)
    try {
      await api.post(`/api/data/health/run/${name}`)
      await refresh()
    } finally {
      setBusy(null)
    }
  }

  async function pauseCheck(name: string, hours: number) {
    setBusy(`pause:${name}`)
    try {
      await api.post(`/api/data/health/pause/${name}?hours=${hours}`)
      await refresh()
    } finally {
      setBusy(null)
    }
  }

  async function resumeCheck(name: string) {
    setBusy(`resume:${name}`)
    try {
      await api.post(`/api/data/health/resume/${name}`)
      await refresh()
    } finally {
      setBusy(null)
    }
  }

  async function ackAlert(id: number) {
    setBusy(`ack:${id}`)
    try {
      await api.post(`/api/data/health/ack/${id}`)
      await refresh()
    } finally {
      setBusy(null)
    }
  }

  async function runDigest() {
    setBusy('digest')
    try {
      await api.post('/api/data/health/digest')
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <LoadingSpinner fullPage />

  const overall = status?.overall ?? 'unknown'
  const checks = status?.checks ?? []
  const openAlerts = status?.open_alerts ?? 0

  const overallLabel =
    overall === 'green'
      ? 'All systems operational'
      : overall === 'yellow'
      ? 'Some checks degraded'
      : overall === 'red'
      ? 'Outage detected'
      : 'No data'

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      <PageHeader
        title="System Health"
        subtitle="Continuous verification of Z-Pay critical paths. Silence = everything works."
        icon={<Activity className="w-5 h-5" />}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => refresh()}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold dark:bg-white/[0.06] dark:border dark:border-white/[0.08] bg-gray-100 border border-gray-200 dark:text-white/70 text-gray-600 hover:dark:bg-white/[0.1] hover:bg-gray-200 transition flex items-center gap-1.5"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Refresh
            </button>
            <button
              onClick={runDigest}
              disabled={busy === 'digest'}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-500/15 text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/25 transition flex items-center gap-1.5 disabled:opacity-50"
            >
              <Bell className="w-3.5 h-3.5" />
              Send digest
            </button>
          </div>
        }
      />

      {/* Overall banner */}
      <GlassCard className="!p-6">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-4">
            <div className="relative">
              <span
                className={cn(
                  'w-4 h-4 rounded-full block',
                  statusDot(overall),
                  overall !== 'green' && 'animate-pulse',
                )}
              />
              {overall === 'green' && (
                <span className="absolute inset-0 rounded-full bg-emerald-400/40 animate-ping" />
              )}
            </div>
            <div>
              <div className={cn('text-xl font-bold', statusColor(overall))}>
                {overallLabel}
              </div>
              <div className="text-xs dark:text-white/40 text-gray-500 mt-0.5">
                Last checked {formatRelative(status?.server_time || null)} • {checks.length} checks
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={openAlerts > 0 ? 'danger' : 'success'} dot>
              {openAlerts} open alert{openAlerts === 1 ? '' : 's'}
            </Badge>
          </div>
        </div>
      </GlassCard>

      {/* Check grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {checks.map((c) => {
          const isMuted = !!c.muted_until && new Date(c.muted_until).getTime() > Date.now()
          return (
            <motion.div
              key={c.name}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <GlassCard className="!p-4 h-full">
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={cn('w-2 h-2 rounded-full flex-shrink-0', statusDot(c.status))} />
                    <div className="font-semibold dark:text-white text-gray-900 text-sm truncate">
                      {prettyCheckName(c.name)}
                    </div>
                  </div>
                  <Badge variant={statusBadgeVariant(c.status)} className="flex-shrink-0">
                    {c.status}
                  </Badge>
                </div>

                <div className="space-y-1 text-xs dark:text-white/50 text-gray-500 mb-3">
                  <div className="flex justify-between gap-2">
                    <span>Last check</span>
                    <span className="dark:text-white/70 text-gray-700">
                      {formatRelative(c.last_checked_at)}
                    </span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span>Last green</span>
                    <span className="dark:text-white/70 text-gray-700">
                      {formatRelative(c.last_ok_at)}
                    </span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span>Latency</span>
                    <span className="dark:text-white/70 text-gray-700">{c.latency_ms}ms</span>
                  </div>
                  {c.consecutive_failures > 0 && (
                    <div className="flex justify-between gap-2">
                      <span>Consecutive fails</span>
                      <span className="text-red-400 font-semibold">
                        {c.consecutive_failures}
                      </span>
                    </div>
                  )}
                  {isMuted && (
                    <div className="flex justify-between gap-2">
                      <span>Muted until</span>
                      <span className="text-amber-400">
                        {c.muted_until ? new Date(c.muted_until).toLocaleTimeString() : '—'}
                      </span>
                    </div>
                  )}
                </div>

                {c.detail && Object.keys(c.detail).length > 0 && (
                  <details className="mb-3">
                    <summary className="text-xs dark:text-white/40 text-gray-400 cursor-pointer hover:dark:text-white/60 hover:text-gray-600">
                      Detail
                    </summary>
                    <pre className="mt-1.5 text-[10px] dark:text-white/50 text-gray-500 dark:bg-black/30 bg-gray-50 rounded p-2 overflow-x-auto">
                      {JSON.stringify(c.detail, null, 2)}
                    </pre>
                  </details>
                )}

                <div className="flex items-center gap-1.5 pt-2 border-t dark:border-white/[0.06] border-gray-100">
                  <button
                    onClick={() => runCheck(c.name)}
                    disabled={busy === `run:${c.name}`}
                    className="flex-1 px-2 py-1 rounded text-[11px] font-medium bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20 transition flex items-center justify-center gap-1 disabled:opacity-50"
                  >
                    <Zap className="w-3 h-3" />
                    Run
                  </button>
                  {isMuted ? (
                    <button
                      onClick={() => resumeCheck(c.name)}
                      disabled={busy === `resume:${c.name}`}
                      className="flex-1 px-2 py-1 rounded text-[11px] font-medium bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition flex items-center justify-center gap-1 disabled:opacity-50"
                    >
                      <Play className="w-3 h-3" />
                      Resume
                    </button>
                  ) : (
                    <button
                      onClick={() => pauseCheck(c.name, 4)}
                      disabled={busy === `pause:${c.name}`}
                      className="flex-1 px-2 py-1 rounded text-[11px] font-medium bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition flex items-center justify-center gap-1 disabled:opacity-50"
                    >
                      <Pause className="w-3 h-3" />
                      Mute 4h
                    </button>
                  )}
                </div>
              </GlassCard>
            </motion.div>
          )
        })}
      </div>

      {/* Recent alerts */}
      <GlassCard className="!p-5">
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle className="w-4 h-4 dark:text-white/60 text-gray-500" />
          <h2 className="text-sm font-semibold dark:text-white text-gray-900">
            Recent alerts
          </h2>
          <span className="text-xs dark:text-white/40 text-gray-400">
            ({alerts.length})
          </span>
        </div>

        {alerts.length === 0 ? (
          <div className="text-sm dark:text-white/40 text-gray-400 text-center py-8">
            No alerts. Nothing broken.
          </div>
        ) : (
          <div className="space-y-2">
            <AnimatePresence initial={false}>
              {alerts.map((a) => {
                const resolved = !!a.resolved_at
                const acked = !!a.acked_at
                return (
                  <motion.div
                    key={a.alert_id}
                    layout
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 8 }}
                    className={cn(
                      'rounded-lg border px-3 py-2.5 flex items-start justify-between gap-3',
                      resolved
                        ? 'dark:border-white/[0.06] border-gray-100 dark:bg-white/[0.02]'
                        : a.severity === 'red'
                        ? 'border-red-500/30 bg-red-500/5'
                        : 'border-amber-500/30 bg-amber-500/5',
                    )}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge
                          variant={
                            resolved
                              ? 'inactive'
                              : a.severity === 'red'
                              ? 'danger'
                              : 'warning'
                          }
                        >
                          {resolved ? 'resolved' : a.severity}
                        </Badge>
                        <span className="text-xs font-semibold dark:text-white/80 text-gray-800">
                          {prettyCheckName(a.check_name)}
                        </span>
                        <span className="text-[11px] dark:text-white/40 text-gray-400">
                          {formatRelative(a.created_at)}
                        </span>
                        {acked && !resolved && (
                          <Badge variant="info">acked</Badge>
                        )}
                      </div>
                      <div className="text-xs dark:text-white/60 text-gray-600 mt-1 break-words">
                        {a.message}
                      </div>
                    </div>
                    {!resolved && !acked && (
                      <button
                        onClick={() => ackAlert(a.alert_id)}
                        disabled={busy === `ack:${a.alert_id}`}
                        className="px-2 py-1 rounded text-[11px] font-medium bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20 transition flex items-center gap-1 flex-shrink-0 disabled:opacity-50"
                      >
                        <Check className="w-3 h-3" />
                        Ack
                      </button>
                    )}
                  </motion.div>
                )
              })}
            </AnimatePresence>
          </div>
        )}
      </GlassCard>

      <div className="text-[11px] dark:text-white/30 text-gray-400 text-center pt-2">
        Auto-refreshes every 30s • Alerts via email + ntfy • Silent 9pm–7am except catastrophic
      </div>
    </div>
  )
}
