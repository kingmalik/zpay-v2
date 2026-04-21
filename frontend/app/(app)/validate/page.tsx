'use client'

import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, CheckCircle2, XCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import StatCard from '@/components/ui/StatCard'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface ValidateData {
  source?: string
  stats?: { partner_net_pay?: number; calc_driver_pay?: number; stored_driver_pay?: number; variance?: number }
  weeks?: {
    week?: string
    drivers?: {
      name?: string; rides_file?: number; rides_db?: number; pay_file?: number; pay_db?: number; variance?: number; match?: boolean
    }[]
  }[]
}

type WeekItem = { week?: string; drivers?: { name?: string; rides_file?: number; rides_db?: number; pay_file?: number; pay_db?: number; variance?: number; match?: boolean }[] }
function WeekCard({ week }: { week: WeekItem }) {
  const [open, setOpen] = useState(false)
  const drivers = week?.drivers || []
  const hasIssue = drivers.some(d => !d.match)

  return (
    <div className="rounded-xl overflow-hidden border dark:border-white/8 border-gray-200">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 dark:bg-white/5 bg-gray-50 text-left cursor-pointer hover:dark:bg-white/8 hover:bg-gray-100 transition-all"
      >
        <div className="flex items-center gap-3">
          <span className="font-medium dark:text-white text-gray-800 text-sm">{week?.week}</span>
          {hasIssue ? (
            <span className="text-xs text-red-400 bg-red-500/10 px-2 py-0.5 rounded-full">{drivers.filter(d => !d.match).length} issues</span>
          ) : (
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          )}
        </div>
        <ChevronDown className={`w-4 h-4 dark:text-white/40 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: 'auto' }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b dark:border-white/8 border-gray-100">
                    {['Driver', 'Rides (File)', 'Rides (DB)', 'Pay (File)', 'Pay (DB)', 'Variance', 'Match'].map(h => (
                      <th key={h} className="px-3 py-2 text-left font-medium dark:text-white/40 text-gray-400">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {drivers.map((d, i) => (
                    <tr key={i} className={`border-b last:border-0 dark:border-white/5 border-gray-50 ${!d.match ? 'dark:bg-red-500/5 bg-red-50/50 border-l-2 border-red-500/40' : ''}`}>
                      <td className="px-3 py-2 dark:text-white/80 text-gray-700">{d.name}</td>
                      <td className="px-3 py-2 dark:text-white/60 text-gray-600">{d.rides_file}</td>
                      <td className="px-3 py-2 dark:text-white/60 text-gray-600">{d.rides_db}</td>
                      <td className="px-3 py-2 dark:text-white/70 text-gray-700">{formatCurrency(d.pay_file)}</td>
                      <td className="px-3 py-2 dark:text-white/70 text-gray-700">{formatCurrency(d.pay_db)}</td>
                      <td className={`px-3 py-2 font-mono ${(d.variance || 0) !== 0 ? 'text-red-400' : 'text-emerald-400'}`}>{formatCurrency(d.variance)}</td>
                      <td className="px-3 py-2">
                        {d.match ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <XCircle className="w-4 h-4 text-red-400" />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default function ValidatePage() {
  const [data, setData] = useState<ValidateData | null>(null)
  const [loading, setLoading] = useState(true)
  const [source, setSource] = useState<'fa' | 'ed'>('fa')

  useEffect(() => {
    api.get<ValidateData>('/api/data/validate').then(setData).catch(console.error).finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  const s = data?.stats || {}

  return (
    <div className="max-w-5xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Validate</h1>
        <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100">
          <button onClick={() => setSource('fa')} className={`px-4 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer ${source === 'fa' ? 'bg-[#667eea] text-white' : 'dark:text-white/50 text-gray-500'}`}>FirstAlt</button>
          <button onClick={() => setSource('ed')} className={`px-4 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer ${source === 'ed' ? 'bg-[#06b6d4] text-white' : 'dark:text-white/50 text-gray-500'}`}>EverDriven</button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-xs dark:text-white/40 text-gray-400">
        <span className="flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Match</span>
        <span className="flex items-center gap-1"><XCircle className="w-3.5 h-3.5 text-red-400" /> Mismatch</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-red-500/20 border border-red-500/40" /> Issue row</span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Partner Net Pay" value={formatCurrency(s.partner_net_pay)} index={0} />
        <StatCard label="Calc Driver Pay" value={formatCurrency(s.calc_driver_pay)} index={1} />
        <StatCard label="Stored Driver Pay" value={formatCurrency(s.stored_driver_pay)} index={2} />
        <StatCard label="Variance" value={formatCurrency(s.variance)} color={(s.variance || 0) !== 0 ? 'danger' : 'success'} index={3} />
      </div>

      <div className="space-y-2">
        {(data?.weeks || []).map((week, i) => (
          <WeekCard key={i} week={week} />
        ))}
        {(data?.weeks || []).length === 0 && (
          <div className="text-center py-12 dark:text-white/30 text-gray-400">No validation data</div>
        )}
      </div>
    </div>
  )
}
