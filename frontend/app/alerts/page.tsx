'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { AlertTriangle, AlertCircle, Info, CheckCircle2, ExternalLink } from 'lucide-react'
import { api } from '@/lib/api'
import StatCard from '@/components/ui/StatCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import PageHeader from '@/components/ui/PageHeader'

interface AlertItem {
  id?: string | number
  title?: string
  description?: string
  type?: 'unmatched_rate' | 'withheld' | 'inactive' | 'general'
  severity?: 'warning' | 'danger' | 'info'
  action_url?: string
  action_label?: string
  count?: number
}

interface AlertsData {
  stats?: { unmatched_rates?: number; withheld_balances?: number; inactive_drivers?: number; total_issues?: number }
  alerts?: AlertItem[]
}

export default function AlertsPage() {
  const [data, setData] = useState<AlertsData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<AlertsData>('/alerts/data').then(setData).catch(console.error).finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  const s = data?.stats || {}
  const alerts = data?.alerts || []

  return (
    <div className="max-w-5xl mx-auto space-y-5 py-6">
      <PageHeader
        title="Alerts"
        subtitle="Flagged items that need your attention"
        icon={<AlertTriangle className="w-4 h-4" />}
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Unmatched Rates" value={s.unmatched_rates || 0} color={(s.unmatched_rates || 0) > 0 ? 'warning' : 'default'} index={0} />
        <StatCard label="Withheld Balances" value={s.withheld_balances || 0} color={(s.withheld_balances || 0) > 0 ? 'warning' : 'default'} index={1} />
        <StatCard label="Inactive Drivers" value={s.inactive_drivers || 0} color="info" index={2} />
        <StatCard label="Total Issues" value={s.total_issues || 0} color={(s.total_issues || 0) > 0 ? 'danger' : 'success'} index={3} />
      </div>

      {alerts.length === 0 ? (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="flex flex-col items-center justify-center py-16 gap-3"
        >
          <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 flex items-center justify-center">
            <CheckCircle2 className="w-8 h-8 text-emerald-400" />
          </div>
          <h3 className="text-lg font-semibold text-emerald-400">All Clear!</h3>
          <p className="text-sm dark:text-white/40 text-gray-400">No alerts at this time. Everything looks good.</p>
        </motion.div>
      ) : (
        <div data-tour="alerts-list" className="space-y-3">
          {alerts.map((alert, i) => {
            const sev = alert.severity || 'info'
            const config = {
              warning: { Icon: AlertTriangle, color: 'text-amber-400', bg: 'dark:bg-amber-500/8 bg-amber-50 border-amber-500/30', btn: 'bg-amber-500/15 text-amber-400 hover:bg-amber-500/25' },
              danger: { Icon: AlertCircle, color: 'text-red-400', bg: 'dark:bg-red-500/8 bg-red-50 border-red-500/30', btn: 'bg-red-500/15 text-red-400 hover:bg-red-500/25' },
              info: { Icon: Info, color: 'text-blue-400', bg: 'dark:bg-blue-500/8 bg-blue-50 border-blue-500/30', btn: 'bg-blue-500/15 text-blue-400 hover:bg-blue-500/25' },
            }[sev]

            return (
              <motion.div
                key={alert.id || i}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.06 }}
                className={`rounded-2xl border p-4 flex items-start gap-3 ${config.bg}`}
              >
                <config.Icon className={`w-5 h-5 mt-0.5 flex-shrink-0 ${config.color}`} />
                <div className="flex-1 min-w-0">
                  <p className={`font-semibold text-sm ${config.color}`}>{alert.title}</p>
                  <p className="text-sm dark:text-white/60 text-gray-600 mt-0.5">{alert.description}</p>
                </div>
                {alert.action_url && (
                  <Link
                    href={alert.action_url}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium flex-shrink-0 transition-all ${config.btn}`}
                  >
                    {alert.action_label || 'Fix'}
                    <ExternalLink className="w-3 h-3" />
                  </Link>
                )}
              </motion.div>
            )
          })}
        </div>
      )}
    </div>
  )
}
