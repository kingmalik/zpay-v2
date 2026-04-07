'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, CheckCircle2, XCircle, MapPin, Clock, User, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'
import Badge from '@/components/ui/Badge'

interface DriverRecommendation {
  id?: string | number
  driver?: string
  phone?: string
  address?: string
  tier?: string
  trip_count?: number
  drive_time?: number
  reason?: string
  score?: number
}

export default function DispatchAssignPage() {
  const [form, setForm] = useState({ pickup: '', dropoff: '', pickup_time: '', dropoff_time: '', date: '', notes: '' })
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<DriverRecommendation[]>([])
  const [confirming, setConfirming] = useState<string | number | null>(null)

  async function search() {
    setLoading(true)
    try {
      const res = await api.post<DriverRecommendation[]>('/dispatch/assign/search', form)
      setResults(res || [])
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function confirm(id: string | number) {
    setConfirming(id)
    try {
      await api.post('/dispatch/assign/confirm', { driver_id: id, ...form })
      setResults([])
    } catch (e) { console.error(e) }
    finally { setConfirming(null) }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6 py-6">
      <h1 className="text-2xl font-bold dark:text-white text-gray-900">Assign Driver</h1>

      <GlassCard>
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs dark:text-white/50 text-gray-500 mb-1.5">Pickup Address</label>
              <div className="relative">
                <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
                <input value={form.pickup} onChange={e => setForm(s => ({ ...s, pickup: e.target.value }))} placeholder="123 Main St..."
                  className="w-full pl-9 pr-4 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
              </div>
            </div>
            <div>
              <label className="block text-xs dark:text-white/50 text-gray-500 mb-1.5">Dropoff Address</label>
              <div className="relative">
                <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
                <input value={form.dropoff} onChange={e => setForm(s => ({ ...s, dropoff: e.target.value }))} placeholder="456 Oak Ave..."
                  className="w-full pl-9 pr-4 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
              </div>
            </div>
            <div>
              <label className="block text-xs dark:text-white/50 text-gray-500 mb-1.5">Pickup Time</label>
              <div className="relative">
                <Clock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
                <input type="time" value={form.pickup_time} onChange={e => setForm(s => ({ ...s, pickup_time: e.target.value }))}
                  className="w-full pl-9 pr-4 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
              </div>
            </div>
            <div>
              <label className="block text-xs dark:text-white/50 text-gray-500 mb-1.5">Date</label>
              <input type="date" value={form.date} onChange={e => setForm(s => ({ ...s, date: e.target.value }))}
                className="w-full px-4 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
            </div>
          </div>
          <div>
            <label className="block text-xs dark:text-white/50 text-gray-500 mb-1.5">Notes (optional)</label>
            <input value={form.notes} onChange={e => setForm(s => ({ ...s, notes: e.target.value }))} placeholder="Special instructions..."
              className="w-full px-4 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
          </div>
          <button onClick={search} disabled={loading || !form.pickup || !form.dropoff}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-white font-medium text-sm transition-all cursor-pointer disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}>
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            {loading ? 'Finding drivers...' : 'Find Best Driver'}
          </button>
        </div>
      </GlassCard>

      {/* Results */}
      <AnimatePresence>
        {results.length > 0 && (
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="space-y-3">
            <h2 className="text-sm font-semibold dark:text-white/60 text-gray-500 uppercase tracking-wide">Recommendations</h2>
            {results.map((rec, i) => (
              <motion.div key={rec.id || i} initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.08 }}>
                <GlassCard>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3">
                      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#667eea] to-[#06b6d4] flex items-center justify-center text-white font-bold text-lg flex-shrink-0">
                        {i + 1}
                      </div>
                      <div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="font-semibold dark:text-white text-gray-800">{rec.driver}</p>
                          {rec.tier && <Badge variant="info">{rec.tier}</Badge>}
                        </div>
                        <p className="text-xs dark:text-white/50 text-gray-500 mt-0.5">{rec.phone} • {rec.address}</p>
                        <div className="flex gap-4 mt-2 text-xs">
                          <span className="dark:text-white/40 text-gray-400"><span className="font-medium dark:text-white/70 text-gray-600">{rec.trip_count}</span> trips today</span>
                          {rec.drive_time && <span className="dark:text-white/40 text-gray-400"><span className="font-medium dark:text-white/70 text-gray-600">{rec.drive_time}m</span> drive</span>}
                        </div>
                        {rec.reason && <p className="text-xs text-[#667eea]/80 mt-1.5 italic">{rec.reason}</p>}
                      </div>
                    </div>
                    <div className="flex gap-2 flex-shrink-0">
                      <button
                        onClick={() => confirm(rec.id!)}
                        disabled={confirming === rec.id}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm font-medium bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-all cursor-pointer"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Assign
                      </button>
                      <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm font-medium bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-all cursor-pointer">
                        <XCircle className="w-3.5 h-3.5" />
                        Skip
                      </button>
                    </div>
                  </div>
                </GlassCard>
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
