'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { motion } from 'framer-motion'
import {
  FileText, Upload, UserPlus, ArrowRight, RefreshCw,
  CheckCircle2, Clock, AlertTriangle, Target, TrendingUp
} from 'lucide-react'
import { api } from '@/lib/api'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface OpsData {
  fa: { total: number; accepted: number; not_accepted: number; started: number; not_started: number; escalations: number }
  ed: { total: number; accepted: number; not_accepted: number; started: number; not_started: number; escalations: number }
  total_today: number
  avg_rides_per_day: number
  goal: number
  goal_pct: number
}

const QUICK_ACTIONS = [
  { label: 'Run Payroll', desc: 'Generate payroll summary', href: '/payroll/workflow', icon: <FileText className="w-5 h-5" />, color: '#667eea' },
  { label: 'Add Driver', desc: 'Start driver onboarding', href: '/onboarding', icon: <UserPlus className="w-5 h-5" />, color: '#10B981' },
  { label: 'Upload Files', desc: 'Import FA or ED data', href: '/upload', icon: <Upload className="w-5 h-5" />, color: '#06b6d4' },
]

function getGreeting(): string {
  const h = new Date().getHours()
  if (h >= 5 && h < 12) return 'Good morning, Malik'
  if (h >= 12 && h < 17) return 'Good afternoon, Malik'
  return 'Good evening, Malik'
}

function SourceCard({
  label, color, accent, data,
}: {
  label: string
  color: string
  accent: string
  data: OpsData['fa']
}) {
  const hasIssues = data.not_accepted > 0 || data.escalations > 0

  return (
    <div
      className="rounded-2xl bg-white dark:bg-white/[0.04] border dark:border-white/[0.08] border-gray-200 p-5"
      style={{ borderLeftWidth: 2, borderLeftColor: color }}
    >
      <div className="flex items-center justify-between mb-4">
        <span
          className="px-2.5 py-0.5 rounded-full text-xs font-semibold border"
          style={{ background: `${color}18`, color, borderColor: `${color}40` }}
        >
          {label}
        </span>
        {hasIssues
          ? <span className="flex items-center gap-1 text-xs text-red-400"><AlertTriangle className="w-3 h-3" />Needs attention</span>
          : data.total > 0
          ? <span className="flex items-center gap-1 text-xs text-emerald-400"><CheckCircle2 className="w-3 h-3" />All good</span>
          : null
        }
      </div>

      {data.total === 0 ? (
        <p className="text-sm dark:text-white/30 text-gray-400">No trips today</p>
      ) : (
        <div className="space-y-3">
          {/* Total */}
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold dark:text-white text-gray-900">{data.total}</span>
            <span className="text-sm dark:text-white/40 text-gray-400">rides today</span>
          </div>

          {/* Accepted row */}
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-xl dark:bg-white/[0.04] bg-gray-50 p-3">
              <p className="text-xs dark:text-white/40 text-gray-400 mb-1">Accepted</p>
              <p className="text-lg font-semibold text-emerald-400">{data.accepted}</p>
            </div>
            <div className="rounded-xl dark:bg-white/[0.04] bg-gray-50 p-3">
              <p className="text-xs dark:text-white/40 text-gray-400 mb-1">Not accepted</p>
              <p className={`text-lg font-semibold ${data.not_accepted > 0 ? 'text-red-400' : 'dark:text-white text-gray-900'}`}>
                {data.not_accepted}
              </p>
            </div>
            <div className="rounded-xl dark:bg-white/[0.04] bg-gray-50 p-3">
              <p className="text-xs dark:text-white/40 text-gray-400 mb-1">Started</p>
              <p className="text-lg font-semibold text-emerald-400">{data.started}</p>
            </div>
            <div className="rounded-xl dark:bg-white/[0.04] bg-gray-50 p-3">
              <p className="text-xs dark:text-white/40 text-gray-400 mb-1">Not started</p>
              <p className={`text-lg font-semibold ${data.not_started > 0 ? 'text-amber-400' : 'dark:text-white text-gray-900'}`}>
                {data.not_started}
              </p>
            </div>
          </div>

          {data.escalations > 0 && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20">
              <AlertTriangle className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
              <p className="text-xs text-red-400 font-medium">{data.escalations} escalation{data.escalations > 1 ? 's' : ''}</p>
              <Link href="/dispatch/monitor" className="ml-auto text-xs text-red-400 underline">View →</Link>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function DashboardPage() {
  const [ops, setOps] = useState<OpsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchOps = useCallback(async () => {
    try {
      const data = await api.get<OpsData>('/api/data/today')
      setOps(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    }
  }, [])

  useEffect(() => {
    fetchOps().finally(() => setLoading(false))
    const id = setInterval(fetchOps, 2 * 60 * 1000)
    return () => clearInterval(id)
  }, [fetchOps])

  if (loading) return <LoadingSpinner fullPage />

  const o = ops || { fa: { total: 0, accepted: 0, not_accepted: 0, started: 0, not_started: 0, escalations: 0 }, ed: { total: 0, accepted: 0, not_accepted: 0, started: 0, not_started: 0, escalations: 0 }, total_today: 0, avg_rides_per_day: 0, goal: 300, goal_pct: 0 }
  const goalPct = o.goal_pct
  const avg = o.avg_rides_per_day

  return (
    <div className="max-w-5xl mx-auto space-y-6 py-6">

      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold dark:text-white text-gray-900">{getGreeting()}</h1>
          <p className="text-sm dark:text-white/50 text-gray-400 mt-0.5">
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}
          </p>
        </div>
        <button
          onClick={() => fetchOps()}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm dark:text-white/50 text-gray-500 dark:hover:bg-white/[0.08] hover:bg-gray-100 transition-all cursor-pointer border dark:border-white/[0.08] border-gray-200"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">{error}</div>
      )}

      {/* Today's total */}
      <div className="rounded-2xl dark:bg-white/[0.04] bg-white border dark:border-white/[0.08] border-gray-200 px-6 py-5 flex items-center justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide dark:text-white/40 text-gray-400 mb-1">Total rides today</p>
          <div className="flex items-baseline gap-3">
            <span className="text-5xl font-bold dark:text-white text-gray-900">{o.total_today}</span>
            {o.total_today === 0 && (
              <span className="text-sm dark:text-white/30 text-gray-400">No trips logged yet</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 dark:text-white/20 text-gray-300">
          <Clock className="w-8 h-8" />
        </div>
      </div>

      {/* Partner cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <SourceCard label="FirstAlt" color="#667eea" accent="indigo" data={o.fa} />
        <SourceCard label="EverDriven" color="#06b6d4" accent="cyan" data={o.ed} />
      </div>

      {/* Goal tracker */}
      <div className="rounded-2xl dark:bg-white/[0.04] bg-white border dark:border-white/[0.08] border-gray-200 p-5">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-8 h-8 rounded-xl bg-[#667eea]/10 flex items-center justify-center text-[#667eea]">
            <Target className="w-4 h-4" />
          </div>
          <div>
            <p className="text-sm font-semibold dark:text-white text-gray-900">Daily Rides Goal</p>
            <p className="text-xs dark:text-white/40 text-gray-400">Target: 300 rides/day average</p>
          </div>
          <div className="ml-auto text-right">
            <p className="text-2xl font-bold dark:text-white text-gray-900">{avg.toFixed(1)}</p>
            <p className="text-xs dark:text-white/40 text-gray-400">avg/day</p>
          </div>
        </div>

        {/* Progress bar */}
        <div className="space-y-2">
          <div className="h-3 rounded-full dark:bg-white/[0.06] bg-gray-100 overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${goalPct}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
              className="h-full rounded-full"
              style={{ background: goalPct >= 100 ? '#10B981' : goalPct >= 66 ? '#667eea' : goalPct >= 33 ? '#f59e0b' : '#ef4444' }}
            />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs dark:text-white/40 text-gray-400">{goalPct.toFixed(1)}% of goal</span>
            <span className="text-xs dark:text-white/40 text-gray-400">
              {avg >= o.goal
                ? <span className="text-emerald-400 font-medium flex items-center gap-1"><TrendingUp className="w-3 h-3" />Goal reached!</span>
                : `${(o.goal - avg).toFixed(1)} rides/day to go`
              }
            </span>
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <div>
        <h2 className="text-xs font-semibold dark:text-white/40 text-gray-400 uppercase tracking-wide mb-3">Quick Actions</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {QUICK_ACTIONS.map((action, i) => (
            <motion.div
              key={action.href}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}
            >
              <Link href={action.href} className="block group">
                <div className="relative rounded-2xl dark:bg-white/[0.04] bg-white border dark:border-white/[0.08] border-gray-200 p-4 flex items-center gap-4 transition-all duration-150 dark:hover:bg-white/[0.07] hover:bg-gray-50 overflow-hidden">
                  <div className="absolute left-0 top-0 bottom-0 w-0.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150" style={{ background: action.color }} />
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 text-white" style={{ background: action.color }}>
                    {action.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold dark:text-white text-gray-800">{action.label}</p>
                    <p className="text-xs dark:text-white/40 text-gray-400">{action.desc}</p>
                  </div>
                  <ArrowRight className="w-4 h-4 dark:text-white/30 text-gray-300 flex-shrink-0 group-hover:translate-x-0.5 transition-transform duration-150" />
                </div>
              </Link>
            </motion.div>
          ))}
        </div>
      </div>

    </div>
  )
}
