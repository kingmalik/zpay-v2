'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { AlertTriangle, ExternalLink, RefreshCw, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { toast } from 'sonner'

interface MissingDriver {
  person_id: number
  name: string
  rides_last_30d: number
  paycheck_code: string | null
  paycheck_code_maz: string | null
}

interface MissingCodesData {
  missing_acumen: MissingDriver[]
  missing_maz: MissingDriver[]
  missing_both: MissingDriver[]
}

function DriverTable({
  drivers,
  emptyLabel,
}: {
  drivers: MissingDriver[]
  emptyLabel: string
}) {
  if (drivers.length === 0) {
    return (
      <div className="px-4 py-8 text-center text-sm dark:text-white/30 text-gray-400">
        {emptyLabel}
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b dark:border-white/[0.08] border-gray-100">
            {['Driver', 'Rides (30d)', 'Acumen Code', 'Maz Code', ''].map((h) => (
              <th
                key={h}
                className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400 whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {drivers.map((d, i) => (
            <motion.tr
              key={d.person_id}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
              className="border-b last:border-0 dark:border-white/[0.06] border-gray-100 dark:hover:bg-white/[0.03] hover:bg-gray-50 transition-colors"
            >
              <td className="px-4 py-2.5 font-medium dark:text-white/80 text-gray-800">
                {d.name}
              </td>
              <td className="px-4 py-2.5 dark:text-white/50 text-gray-500">
                {d.rides_last_30d}
              </td>
              <td className="px-4 py-2.5">
                {d.paycheck_code ? (
                  <span className="font-mono text-xs dark:text-emerald-400 text-emerald-600">
                    {d.paycheck_code}
                  </span>
                ) : (
                  <span className="text-xs dark:text-red-400 text-red-500 font-medium">
                    Missing
                  </span>
                )}
              </td>
              <td className="px-4 py-2.5">
                {d.paycheck_code_maz ? (
                  <span className="font-mono text-xs dark:text-emerald-400 text-emerald-600">
                    {d.paycheck_code_maz}
                  </span>
                ) : (
                  <span className="text-xs dark:text-red-400 text-red-500 font-medium">
                    Missing
                  </span>
                )}
              </td>
              <td className="px-4 py-2.5">
                <Link
                  href={`/people?search=${encodeURIComponent(d.name)}`}
                  className="flex items-center gap-1 text-xs text-[#667eea] hover:text-[#7c93f0] transition-colors whitespace-nowrap"
                >
                  Edit profile
                  <ExternalLink className="w-3 h-3" />
                </Link>
              </td>
            </motion.tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function MissingPaychexCodesPage() {
  const [data, setData] = useState<MissingCodesData | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  async function load(isRefresh = false) {
    if (isRefresh) setRefreshing(true)
    try {
      const d = await api.get<MissingCodesData>('/admin/missing-paychex-codes')
      setData(d)
    } catch (e) {
      console.error(e)
      toast.error('Failed to load missing codes data')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  const acumenCount = data?.missing_acumen.length ?? 0
  const mazCount = data?.missing_maz.length ?? 0
  const bothCount = data?.missing_both.length ?? 0
  const totalMissing = acumenCount + mazCount + bothCount

  return (
    <div className="max-w-5xl mx-auto space-y-5 py-6">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">
            Missing Paychex Codes
          </h1>
          <p className="text-sm dark:text-white/40 text-gray-500 mt-0.5">
            Active drivers with rides in the last 30 days who are missing a Paychex worker ID.
            Payroll exports will fail for these drivers.
          </p>
        </div>
        <button
          onClick={() => load(true)}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white cursor-pointer disabled:opacity-60 transition-all"
          style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
        >
          {refreshing ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Summary banner */}
      {totalMissing > 0 && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-3 px-4 py-3 rounded-xl dark:bg-amber-500/10 bg-amber-50 border dark:border-amber-500/20 border-amber-200"
        >
          <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0" />
          <p className="text-sm dark:text-amber-300 text-amber-800">
            <span className="font-semibold">{totalMissing} driver{totalMissing !== 1 ? 's' : ''}</span>{' '}
            need Paychex codes before payroll can export correctly.
          </p>
        </motion.div>
      )}

      {totalMissing === 0 && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-3 px-4 py-3 rounded-xl dark:bg-emerald-500/10 bg-emerald-50 border dark:border-emerald-500/20 border-emerald-200"
        >
          <span className="text-sm dark:text-emerald-300 text-emerald-800 font-medium">
            All active drivers have their Paychex codes set.
          </span>
        </motion.div>
      )}

      {/* Missing Acumen Code */}
      <GlassCard padding={false}>
        <div className="p-4 border-b dark:border-white/[0.08] border-gray-100 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-red-400 flex-shrink-0" />
          <h3 className="font-semibold dark:text-white/80 text-gray-700 text-sm">
            Missing Acumen Code
            <span className="ml-2 px-2 py-0.5 rounded-full text-xs font-medium dark:bg-red-500/15 bg-red-100 dark:text-red-300 text-red-700">
              {acumenCount}
            </span>
          </h3>
          <p className="ml-auto text-xs dark:text-white/30 text-gray-400 hidden sm:block">
            Drivers with FirstAlt rides but no <code className="font-mono">paycheck_code</code>
          </p>
        </div>
        <DriverTable
          drivers={data?.missing_acumen ?? []}
          emptyLabel="No drivers missing Acumen codes"
        />
      </GlassCard>

      {/* Missing Maz Code */}
      <GlassCard padding={false}>
        <div className="p-4 border-b dark:border-white/[0.08] border-gray-100 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-orange-400 flex-shrink-0" />
          <h3 className="font-semibold dark:text-white/80 text-gray-700 text-sm">
            Missing Maz Code
            <span className="ml-2 px-2 py-0.5 rounded-full text-xs font-medium dark:bg-orange-500/15 bg-orange-100 dark:text-orange-300 text-orange-700">
              {mazCount}
            </span>
          </h3>
          <p className="ml-auto text-xs dark:text-white/30 text-gray-400 hidden sm:block">
            Drivers with EverDriven rides but no <code className="font-mono">paycheck_code_maz</code>
          </p>
        </div>
        <DriverTable
          drivers={data?.missing_maz ?? []}
          emptyLabel="No drivers missing Maz codes"
        />
      </GlassCard>

      {/* Missing Both */}
      <GlassCard padding={false}>
        <div className="p-4 border-b dark:border-white/[0.08] border-gray-100 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-rose-500 flex-shrink-0" />
          <h3 className="font-semibold dark:text-white/80 text-gray-700 text-sm">
            Missing Both Codes
            <span className="ml-2 px-2 py-0.5 rounded-full text-xs font-medium dark:bg-rose-500/15 bg-rose-100 dark:text-rose-300 text-rose-700">
              {bothCount}
            </span>
          </h3>
          <p className="ml-auto text-xs dark:text-white/30 text-gray-400 hidden sm:block">
            Drivers missing both Acumen and Maz codes
          </p>
        </div>
        <DriverTable
          drivers={data?.missing_both ?? []}
          emptyLabel="No drivers missing both codes"
        />
      </GlassCard>
    </div>
  )
}
