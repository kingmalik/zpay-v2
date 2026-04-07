'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { ArrowRight, Package, Clock, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import EmptyState from '@/components/ui/EmptyState'

interface BatchSummary {
  batch_id: number
  source: string
  company: string
  company_raw: string
  batch_ref: string
  status: string
  period_start: string | null
  period_end: string | null
  uploaded_at: string | null
  rides: number
  revenue: number
  cost: number
  margin: number
  unpriced_rides: number
  driver_count: number
  stubs_sent: number
  stubs_failed: number
}

const STATUS_LABELS: Record<string, string> = {
  uploaded: 'Uploaded',
  rates_review: 'Rates Review',
  payroll_review: 'Payroll Review',
  approved: 'Approved',
  export_ready: 'Export Ready',
  stubs_sending: 'Sending Stubs',
  complete: 'Complete',
}

const STATUS_BADGES: Record<string, 'draft' | 'warning' | 'info' | 'success' | 'final'> = {
  uploaded: 'draft',
  rates_review: 'warning',
  payroll_review: 'info',
  approved: 'success',
  export_ready: 'info',
  stubs_sending: 'warning',
  complete: 'final',
}

function formatPeriod(start: string | null, end: string | null): string {
  if (!start) return 'No period'
  const s = new Date(start + 'T00:00:00')
  const e = end ? new Date(end + 'T00:00:00') : null
  const fmt = (d: Date) => `${d.getMonth() + 1}/${d.getDate()}`
  const fmtFull = (d: Date) => `${d.getMonth() + 1}/${d.getDate()}/${d.getFullYear()}`
  return e ? `${fmt(s)} – ${fmtFull(e)}` : fmt(s)
}

export default function WorkflowPage() {
  const router = useRouter()
  const [batches, setBatches] = useState<BatchSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<{ batches: BatchSummary[] }>('/api/data/workflow/active')
      .then(d => setBatches(d.batches))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  if (batches.length === 0) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold text-white mb-6">Payroll Workflow</h1>
        <EmptyState
          icon={<CheckCircle2 className="w-12 h-12 text-emerald-400" />}
          title="All caught up!"
          subtitle="No active batches. Upload a new batch to get started."
        />
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Payroll Workflow</h1>
        <Badge variant="info">{batches.length} active</Badge>
      </div>

      <div className="grid gap-4">
        {batches.map((batch, i) => (
          <motion.div
            key={batch.batch_id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: i * 0.05 }}
            onClick={() => router.push(`/payroll/workflow/${batch.batch_id}`)}
            className="rounded-2xl p-5 cursor-pointer transition-all duration-200
              dark:bg-white/5 dark:backdrop-blur-xl dark:border dark:border-white/10
              dark:hover:bg-white/8 dark:hover:border-white/20
              bg-white border border-gray-200 shadow-sm hover:shadow-md"
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-3">
                <Badge variant={batch.company === 'FirstAlt' ? 'fa' : 'ed'} dot>
                  {batch.company}
                </Badge>
                <Badge variant={STATUS_BADGES[batch.status] || 'default'}>
                  {STATUS_LABELS[batch.status] || batch.status}
                </Badge>
                {batch.unpriced_rides > 0 && (
                  <Badge variant="danger" dot>
                    <AlertTriangle className="w-3 h-3 mr-0.5" />
                    {batch.unpriced_rides} unpriced
                  </Badge>
                )}
              </div>
              <ArrowRight className="w-5 h-5 text-white/30" />
            </div>

            <div className="flex items-center gap-6 text-sm">
              <div className="flex items-center gap-1.5 text-white/60">
                <Clock className="w-3.5 h-3.5" />
                {formatPeriod(batch.period_start, batch.period_end)}
              </div>
              <div className="flex items-center gap-1.5 text-white/60">
                <Package className="w-3.5 h-3.5" />
                {batch.rides} rides
              </div>
              <div className="text-white/60">
                {batch.driver_count} drivers
              </div>
              <div className="text-emerald-400 font-medium">
                {formatCurrency(batch.margin)} margin
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
