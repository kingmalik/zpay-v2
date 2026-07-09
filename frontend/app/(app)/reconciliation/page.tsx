'use client'

import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import StatCard from '@/components/ui/StatCard'
import FilterBar from '@/components/ui/FilterBar'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Badge from '@/components/ui/Badge'
import DepositModal, { ReconBatchRow } from '@/components/reconciliation/DepositModal'

interface ReconBatch extends ReconBatchRow {
  rides?: number
  cost?: number
  profit?: number
  status?: string
  payment_delta?: number
  deposit_date?: string | null
  dispute_deadline?: string | null
  dispute_days_left?: number | null
  disputed?: boolean
}

interface ReconciliationData {
  stats?: {
    total?: number
    healthy?: number
    needs_review?: number
    largest_issue?: number
    deposits_unconfirmed?: number
    dispute_at_risk?: number
  }
  batches?: ReconBatch[]
}

function statusBadge(status?: string) {
  const s = (status || '').toLowerCase()
  if (s === 'ok') return <Badge variant="success" dot>OK</Badge>
  if (s.includes('warn')) return <Badge variant="warning" dot>Warning</Badge>
  if (s.includes('loss')) return <Badge variant="danger" dot>Loss</Badge>
  return <Badge>{status || '—'}</Badge>
}

function paymentCell(b: ReconBatch) {
  const days = b.dispute_days_left
  switch (b.payment_status) {
    case 'match':
      return <Badge variant="success" dot>Paid</Badge>
    case 'unpaid':
      return <Badge variant="danger" dot>Unpaid</Badge>
    case 'underpaid':
      return (
        <div className="space-y-0.5">
          <Badge variant="danger" dot>Short {formatCurrency(Math.abs(b.payment_delta || 0))}</Badge>
          {b.disputed ? (
            <p className="text-[11px] text-blue-400">Disputed in writing</p>
          ) : days != null && (
            <p className={`text-[11px] ${days <= 5 ? 'text-red-400 font-semibold' : 'dark:text-white/40 text-gray-400'}`}>
              {days < 0 ? 'Dispute window CLOSED' : `Dispute closes in ${days}d`}
            </p>
          )}
        </div>
      )
    case 'overpaid':
      return <Badge variant="warning" dot>Over {formatCurrency(b.payment_delta || 0)}</Badge>
    default:
      return <span className="text-xs dark:text-white/25 text-gray-300">—</span>
  }
}

export default function ReconciliationPage() {
  const [data, setData] = useState<ReconciliationData | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [company, setCompany] = useState('all')
  const [modal, setModal] = useState<{ batch: ReconBatch; mode: 'record' | 'dispute' } | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    api.get<ReconciliationData>('/api/data/reconciliation')
      .then(d => { setData(d); setFetchError(null) })
      .catch(e => setFetchError(e instanceof Error ? e.message : 'Failed to load reconciliation data'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  if (loading && !data) return <LoadingSpinner fullPage />

  if (fetchError && !data) {
    return (
      <div className="max-w-7xl mx-auto py-10">
        <div className="rounded-2xl p-6 bg-red-500/10 border border-red-500/20 text-center">
          <p className="text-red-400 font-medium">Failed to load reconciliation data</p>
          <p className="text-sm dark:text-white/40 text-gray-400 mt-1">{fetchError}</p>
          <button
            onClick={load}
            className="mt-4 px-4 py-2 rounded-xl text-sm bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  const s = data?.stats || {}
  const batches = (data?.batches || []).filter(b => {
    if (company === 'all') return true
    const src = (b.source || b.company || '').toLowerCase()
    return company === 'fa' ? src.includes('first') || src.includes('fa') || src.includes('acumen') : src.includes('ever') || src.includes('ed') || src.includes('maz')
  })

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Reconciliation</h1>
        <FilterBar company={company} onCompanyChange={setCompany} />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Batches" value={s.total || 0} index={0} />
        <StatCard label="Healthy Margin" value={s.healthy || 0} color="success" index={1} />
        <StatCard
          label="Deposits Unconfirmed"
          value={s.deposits_unconfirmed || 0}
          color={(s.deposits_unconfirmed || 0) > 0 ? 'warning' : 'default'}
          index={2}
        />
        <StatCard
          label="Dispute At-Risk"
          value={s.dispute_at_risk || 0}
          color={(s.dispute_at_risk || 0) > 0 ? 'danger' : 'default'}
          index={3}
        />
      </div>

      {(s.dispute_at_risk || 0) > 0 && (
        <div className="rounded-2xl px-4 py-3 bg-red-500/10 border border-red-500/25 text-sm text-red-400">
          A shortfall&apos;s 14-day written-dispute window (FA TPA §6b) is about to close — dispute it in
          writing now or the claim is waived permanently.
        </div>
      )}

      <div className="rounded-2xl overflow-hidden dark:bg-white/3 bg-white border dark:border-white/8 border-gray-200">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b dark:border-white/8 border-gray-100">
                {['Week', 'Source', 'Rides', 'Expected', 'Deposited', 'Cost', 'Profit', 'Margin', 'Payment', ''].map((h, i) => (
                  <th key={i} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {batches.map((b, i) => {
                const status = (b.status || '').toLowerCase()
                const atRisk = b.payment_status === 'underpaid' && !b.disputed && b.dispute_days_left != null && b.dispute_days_left <= 5
                const rowColor = atRisk
                  ? 'dark:bg-red-500/10 bg-red-50 border-l-2 border-red-500/60'
                  : status === 'ok' ? '' : status.includes('warn') ? 'dark:bg-amber-500/5 bg-amber-50/50 border-l-2 border-amber-500/40' : status.includes('loss') ? 'dark:bg-red-500/5 bg-red-50/50 border-l-2 border-red-500/40' : ''
                const isFa = (b.source || b.company || '').toLowerCase().includes('first') || (b.source || '').toLowerCase() === 'acumen'
                const canRecord = b.payment_status !== 'match'
                const canDispute = b.payment_status === 'underpaid' && !b.disputed
                return (
                  <tr key={b.batch_id ?? i} className={`border-b last:border-0 dark:border-white/5 border-gray-50 ${rowColor}`}>
                    <td className="px-4 py-3 dark:text-white/80 text-gray-700 whitespace-nowrap">{b.week}</td>
                    <td className="px-4 py-3"><Badge variant={isFa ? 'fa' : 'ed'}>{b.source || b.company}</Badge></td>
                    <td className="px-4 py-3 dark:text-white/60 text-gray-600">{b.rides}</td>
                    <td className="px-4 py-3 dark:text-white/70 text-gray-700">{formatCurrency(b.revenue)}</td>
                    <td className="px-4 py-3 dark:text-white/70 text-gray-700">
                      {b.payment_status === 'untracked' ? <span className="dark:text-white/25 text-gray-300">—</span> : formatCurrency(b.deposited)}
                    </td>
                    <td className="px-4 py-3 dark:text-white/60 text-gray-600">{formatCurrency(b.cost)}</td>
                    <td className={`px-4 py-3 font-medium ${(b.profit || 0) >= 0 ? 'text-emerald-500' : 'text-red-400'}`}>{formatCurrency(b.profit)}</td>
                    <td className="px-4 py-3">{statusBadge(b.status)}</td>
                    <td className="px-4 py-3">{paymentCell(b)}</td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <div className="flex gap-1.5 justify-end">
                        {canRecord && (
                          <button
                            onClick={() => setModal({ batch: b, mode: 'record' })}
                            className="px-2.5 py-1 rounded-lg text-xs dark:bg-emerald-500/10 bg-emerald-50 text-emerald-500 dark:hover:bg-emerald-500/20 hover:bg-emerald-100 border dark:border-emerald-500/20 border-emerald-200"
                          >
                            + Deposit
                          </button>
                        )}
                        {canDispute && (
                          <button
                            onClick={() => setModal({ batch: b, mode: 'dispute' })}
                            className="px-2.5 py-1 rounded-lg text-xs dark:bg-red-500/10 bg-red-50 text-red-400 dark:hover:bg-red-500/20 hover:bg-red-100 border dark:border-red-500/20 border-red-200"
                          >
                            Dispute
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
              {batches.length === 0 && (
                <tr><td colSpan={10} className="px-4 py-10 text-center text-sm dark:text-white/30 text-gray-400">No batches found</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {modal && (
        <DepositModal
          batch={modal.batch}
          mode={modal.mode}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load() }}
        />
      )}
    </div>
  )
}
