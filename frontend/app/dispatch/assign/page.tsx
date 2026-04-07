'use client'

import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  UserPlus, Zap, Search, CheckCircle2, AlertTriangle, Loader2,
  MapPin, Clock, FileText, Star, ChevronRight, ArrowLeft,
  Sparkles, Users, Route
} from 'lucide-react'
import { api } from '@/lib/api'
import { todayStr } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Link from 'next/link'

// ── Types ──────────────────────────────────────────────────────────────

interface Trip {
  id?: string | number
  firstPickUp?: string
  tripStatus?: string
  status?: string
  name?: string
  serviceName?: string
  service_name?: string
  service_code?: string
  _source?: string
  pickupAddress?: string
  dropoffAddress?: string
  origin?: string
  destination?: string
}

interface Driver {
  person_id?: number
  name?: string
  phone?: string
  address?: string
  sources?: string[]
  trips?: Trip[]
  trip_count?: number
}

interface DispatchData {
  date?: string
  drivers?: Driver[]
  unassigned?: Trip[]
  dashboard?: Record<string, number>
}

interface Recommendation {
  person_id: number
  name: string
  tier: number
  tier_label: string
  reason: string
}

interface Suggestion {
  trip_name: string
  recommendations: Recommendation[]
}

// ── Tier Styling ───────────────────────────────────────────────────────

function tierStyle(tier: number) {
  switch (tier) {
    case 1: return { bg: 'bg-emerald-500/15 border-emerald-500/30', text: 'text-emerald-400', label: 'Best Match' }
    case 2: return { bg: 'bg-blue-500/15 border-blue-500/30', text: 'text-blue-400', label: 'Great' }
    case 3: return { bg: 'bg-amber-500/15 border-amber-500/30', text: 'text-amber-400', label: 'Good' }
    case 4: return { bg: 'bg-orange-500/15 border-orange-500/30', text: 'text-orange-400', label: 'Possible' }
    default: return { bg: 'bg-red-500/15 border-red-500/30', text: 'text-red-400', label: 'Conflict' }
  }
}

// ── Main Page ──────────────────────────────────────────────────────────

export default function DispatchAssignPage() {
  const [mode, setMode] = useState<'menu' | 'assign' | 'optimize'>('menu')
  const [date, setDate] = useState(todayStr())
  const [loading, setLoading] = useState(true)
  const [dispatchData, setDispatchData] = useState<DispatchData | null>(null)

  // Assign form state
  const [pickupAddress, setPickupAddress] = useState('')
  const [dropoffAddress, setDropoffAddress] = useState('')
  const [pickupTime, setPickupTime] = useState('')
  const [dropoffTime, setDropoffTime] = useState('')
  const [notes, setNotes] = useState('')
  const [searching, setSearching] = useState(false)
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])
  const [searchDone, setSearchDone] = useState(false)

  // Optimize state
  const [optimizing, setOptimizing] = useState(false)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [optimizeDone, setOptimizeDone] = useState(false)

  // Confirm state
  const [confirming, setConfirming] = useState<number | null>(null)
  const [confirmed, setConfirmed] = useState<{ id: number; name: string; message: string } | null>(null)

  async function fetchDispatch() {
    setLoading(true)
    try {
      const d = await api.get<DispatchData>(`/dispatch/data?date=${date}`)
      setDispatchData(d)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  useEffect(() => { fetchDispatch() }, [date])

  // ── Assign: search for driver recommendations ──

  async function handleSearch() {
    if (!pickupAddress || !pickupTime) return
    setSearching(true)
    setSearchDone(false)
    setRecommendations([])
    setConfirmed(null)
    try {
      const form = new FormData()
      form.append('pickup_address', pickupAddress)
      form.append('dropoff_address', dropoffAddress)
      form.append('pickup_time', pickupTime)
      form.append('dropoff_time', dropoffTime)
      form.append('ride_date', date)
      form.append('notes', notes)

      const res = await api.postForm<{ recommendations: Recommendation[]; no_drivers: boolean }>(
        '/dispatch/assign/search', form
      )
      setRecommendations(res.recommendations || [])
      setSearchDone(true)
    } catch (e) { console.error(e) }
    finally { setSearching(false) }
  }

  // ── Assign: confirm a driver ──

  async function handleConfirm(rec: Recommendation) {
    setConfirming(rec.person_id)
    try {
      const form = new FormData()
      form.append('person_id', String(rec.person_id))
      form.append('pickup_address', pickupAddress)
      form.append('dropoff_address', dropoffAddress)
      form.append('pickup_time', pickupTime)
      form.append('dropoff_time', dropoffTime)
      form.append('ride_date', date)
      form.append('notes', notes)

      const res = await api.postForm<{ ok: boolean; assignment_id: number; driver_name: string; message: string }>(
        '/dispatch/assign/confirm', form
      )
      if (res.ok) {
        setConfirmed({ id: res.assignment_id, name: res.driver_name, message: res.message })
      }
    } catch (e) { console.error(e) }
    finally { setConfirming(null) }
  }

  // ── Optimize: auto-assign unassigned trips ──

  async function handleOptimize() {
    const drivers = dispatchData?.drivers || []
    const unassigned = dispatchData?.unassigned || []
    if (unassigned.length === 0) return

    setOptimizing(true)
    setOptimizeDone(false)
    setSuggestions([])
    try {
      const body = {
        drivers: drivers.map(d => ({
          person_id: d.person_id,
          name: d.name,
          address: d.address || '',
          trips: d.trips || [],
        })),
        trips_to_optimize: unassigned.map(t => ({
          name: t.serviceName || t.service_name || t.name || t.service_code || 'Unnamed',
          pickup_time: t.firstPickUp || '',
          dropoff_time: '',
          pickup_address: t.pickupAddress || t.origin || '',
        })),
      }
      const res = await api.post<{ suggestions: Suggestion[] }>('/dispatch/simulate/optimize', body)
      setSuggestions(res.suggestions || [])
      setOptimizeDone(true)
    } catch (e) { console.error(e) }
    finally { setOptimizing(false) }
  }

  const unassigned = dispatchData?.unassigned || []
  const driverCount = dispatchData?.drivers?.length || 0

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-5xl mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/dispatch"
          className="p-2 rounded-xl dark:bg-white/5 bg-gray-100 dark:hover:bg-white/10 hover:bg-gray-200 transition-all">
          <ArrowLeft className="w-4 h-4 dark:text-white/60 text-gray-500" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-bold dark:text-white text-gray-900">Dispatch Command Center</h1>
          <p className="text-sm dark:text-white/40 text-gray-400">Assign drivers or auto-optimize trips</p>
        </div>
        <input
          type="date"
          value={date}
          onChange={e => { setDate(e.target.value); setMode('menu'); setSearchDone(false); setOptimizeDone(false) }}
          className="px-3 py-1.5 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
        />
      </div>

      {/* Status bar */}
      <div className="flex gap-3 flex-wrap">
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200">
          <Users className="w-4 h-4 dark:text-white/40 text-gray-400" />
          <span className="text-sm dark:text-white/70 text-gray-600"><strong>{driverCount}</strong> drivers today</span>
        </div>
        {unassigned.length > 0 && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-500/10 border border-amber-500/20">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <span className="text-sm text-amber-400"><strong>{unassigned.length}</strong> unassigned trips</span>
          </div>
        )}
      </div>

      <AnimatePresence mode="wait">
        {/* ── MENU MODE ── */}
        {mode === 'menu' && (
          <motion.div
            key="menu"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="grid md:grid-cols-2 gap-5"
          >
            {/* Assign card */}
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => setMode('assign')}
              className="text-left cursor-pointer"
            >
              <GlassCard hover className="h-full">
                <div className="flex items-start gap-4">
                  <div className="w-14 h-14 rounded-2xl bg-[#667eea]/15 flex items-center justify-center flex-shrink-0">
                    <UserPlus className="w-7 h-7 text-[#667eea]" />
                  </div>
                  <div>
                    <h2 className="text-lg font-bold dark:text-white text-gray-900 mb-1">Assign a Driver</h2>
                    <p className="text-sm dark:text-white/50 text-gray-500 leading-relaxed">
                      Enter pickup & drop-off details and Z-Pay will find the best available driver for the trip.
                    </p>
                    <div className="flex items-center gap-1 mt-3 text-[#667eea] text-sm font-medium">
                      Get started <ChevronRight className="w-4 h-4" />
                    </div>
                  </div>
                </div>
              </GlassCard>
            </motion.button>

            {/* Optimize card */}
            <motion.button
              whileHover={{ scale: unassigned.length > 0 ? 1.02 : 1 }}
              whileTap={{ scale: unassigned.length > 0 ? 0.98 : 1 }}
              onClick={() => unassigned.length > 0 && setMode('optimize')}
              className={`text-left ${unassigned.length > 0 ? 'cursor-pointer' : 'cursor-default'}`}
            >
              <GlassCard hover={unassigned.length > 0} className={`h-full ${unassigned.length === 0 ? 'opacity-50' : ''}`}>
                <div className="flex items-start gap-4">
                  <div className="w-14 h-14 rounded-2xl bg-amber-500/15 flex items-center justify-center flex-shrink-0">
                    <Sparkles className="w-7 h-7 text-amber-400" />
                  </div>
                  <div>
                    <h2 className="text-lg font-bold dark:text-white text-gray-900 mb-1">Auto-Optimize</h2>
                    <p className="text-sm dark:text-white/50 text-gray-500 leading-relaxed">
                      {unassigned.length > 0
                        ? `Automatically find the best drivers for ${unassigned.length} unassigned trip${unassigned.length > 1 ? 's' : ''}.`
                        : 'No unassigned trips right now. All drivers are covered!'}
                    </p>
                    {unassigned.length > 0 && (
                      <div className="flex items-center gap-1 mt-3 text-amber-400 text-sm font-medium">
                        Optimize now <ChevronRight className="w-4 h-4" />
                      </div>
                    )}
                  </div>
                </div>
              </GlassCard>
            </motion.button>
          </motion.div>
        )}

        {/* ── ASSIGN MODE ── */}
        {mode === 'assign' && (
          <motion.div
            key="assign"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="space-y-5"
          >
            <button onClick={() => { setMode('menu'); setSearchDone(false); setRecommendations([]); setConfirmed(null) }}
              className="flex items-center gap-2 text-sm dark:text-white/50 text-gray-400 hover:text-[#667eea] transition-colors cursor-pointer">
              <ArrowLeft className="w-4 h-4" /> Back to menu
            </button>

            {/* Success banner */}
            {confirmed && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="rounded-2xl bg-emerald-500/10 border border-emerald-500/20 p-5 flex items-start gap-4"
              >
                <CheckCircle2 className="w-6 h-6 text-emerald-400 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="font-semibold text-emerald-400 text-sm">Driver Assigned!</p>
                  <p className="text-sm dark:text-white/60 text-gray-500 mt-1">{confirmed.message}</p>
                </div>
              </motion.div>
            )}

            {/* Assignment form */}
            <GlassCard>
              <h2 className="text-lg font-bold dark:text-white text-gray-900 mb-4 flex items-center gap-2">
                <Search className="w-5 h-5 text-[#667eea]" />
                Trip Details
              </h2>
              <div className="grid md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium dark:text-white/50 text-gray-500 mb-1.5">
                    <MapPin className="w-3.5 h-3.5 inline mr-1" />
                    Pickup Address
                  </label>
                  <input
                    type="text"
                    value={pickupAddress}
                    onChange={e => setPickupAddress(e.target.value)}
                    placeholder="123 Main St, Seattle WA"
                    className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/25 placeholder:text-gray-300 focus:outline-none focus:border-[#667eea]/60 transition-colors"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium dark:text-white/50 text-gray-500 mb-1.5">
                    <MapPin className="w-3.5 h-3.5 inline mr-1" />
                    Drop-off Address
                  </label>
                  <input
                    type="text"
                    value={dropoffAddress}
                    onChange={e => setDropoffAddress(e.target.value)}
                    placeholder="456 School Rd, Bellevue WA"
                    className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/25 placeholder:text-gray-300 focus:outline-none focus:border-[#667eea]/60 transition-colors"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium dark:text-white/50 text-gray-500 mb-1.5">
                    <Clock className="w-3.5 h-3.5 inline mr-1" />
                    Pickup Time
                  </label>
                  <input
                    type="time"
                    value={pickupTime}
                    onChange={e => setPickupTime(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60 transition-colors"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium dark:text-white/50 text-gray-500 mb-1.5">
                    <Clock className="w-3.5 h-3.5 inline mr-1" />
                    Drop-off Time
                  </label>
                  <input
                    type="time"
                    value={dropoffTime}
                    onChange={e => setDropoffTime(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60 transition-colors"
                  />
                </div>
              </div>
              <div className="mt-4">
                <label className="block text-xs font-medium dark:text-white/50 text-gray-500 mb-1.5">
                  <FileText className="w-3.5 h-3.5 inline mr-1" />
                  Notes (optional)
                </label>
                <input
                  type="text"
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                  placeholder="Special instructions, student name, etc."
                  className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/25 placeholder:text-gray-300 focus:outline-none focus:border-[#667eea]/60 transition-colors"
                />
              </div>
              <button
                onClick={handleSearch}
                disabled={searching || !pickupAddress || !pickupTime}
                className="mt-5 w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-[#667eea] hover:bg-[#5a6fd6] text-white text-sm font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              >
                {searching ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Finding best drivers...</>
                ) : (
                  <><Search className="w-4 h-4" /> Find Best Drivers</>
                )}
              </button>
            </GlassCard>

            {/* Recommendations */}
            {searchDone && (
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                className="space-y-3"
              >
                <h3 className="text-sm font-semibold dark:text-white/70 text-gray-600 uppercase tracking-wide flex items-center gap-2">
                  <Star className="w-4 h-4 text-[#667eea]" />
                  Top Recommendations ({recommendations.length})
                </h3>
                {recommendations.length === 0 ? (
                  <GlassCard>
                    <p className="text-sm dark:text-white/50 text-gray-400 text-center py-4">
                      No available drivers found for this time slot. Try adjusting the times.
                    </p>
                  </GlassCard>
                ) : (
                  <div className="grid gap-3">
                    {recommendations.map((rec, i) => {
                      const style = tierStyle(rec.tier)
                      const isConfirmed = confirmed?.name === rec.name
                      return (
                        <motion.div
                          key={rec.person_id}
                          initial={{ opacity: 0, x: -20 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: i * 0.08 }}
                        >
                          <GlassCard className={isConfirmed ? 'ring-2 ring-emerald-500/50' : ''}>
                            <div className="flex items-center gap-4">
                              {/* Rank */}
                              <div className={`w-12 h-12 rounded-2xl ${style.bg} border flex items-center justify-center text-lg font-bold flex-shrink-0 ${style.text}`}>
                                #{i + 1}
                              </div>
                              {/* Info */}
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <p className="font-semibold dark:text-white text-gray-900 text-sm">{rec.name}</p>
                                  <span className={`text-xs px-2 py-0.5 rounded-full ${style.bg} ${style.text} border font-medium`}>
                                    {rec.tier_label}
                                  </span>
                                </div>
                                <p className="text-xs dark:text-white/40 text-gray-400 mt-1 line-clamp-2">{rec.reason}</p>
                              </div>
                              {/* Action */}
                              {isConfirmed ? (
                                <div className="flex items-center gap-1 text-emerald-400 text-sm font-medium flex-shrink-0">
                                  <CheckCircle2 className="w-5 h-5" /> Assigned
                                </div>
                              ) : (
                                <button
                                  onClick={() => handleConfirm(rec)}
                                  disabled={confirming !== null || confirmed !== null}
                                  className="px-4 py-2.5 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-sm font-semibold hover:bg-emerald-500/25 transition-all disabled:opacity-40 cursor-pointer flex-shrink-0"
                                >
                                  {confirming === rec.person_id ? (
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                  ) : (
                                    'Assign'
                                  )}
                                </button>
                              )}
                            </div>
                          </GlassCard>
                        </motion.div>
                      )
                    })}
                  </div>
                )}
              </motion.div>
            )}
          </motion.div>
        )}

        {/* ── OPTIMIZE MODE ── */}
        {mode === 'optimize' && (
          <motion.div
            key="optimize"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="space-y-5"
          >
            <button onClick={() => { setMode('menu'); setOptimizeDone(false); setSuggestions([]) }}
              className="flex items-center gap-2 text-sm dark:text-white/50 text-gray-400 hover:text-amber-400 transition-colors cursor-pointer">
              <ArrowLeft className="w-4 h-4" /> Back to menu
            </button>

            {/* Unassigned trips list */}
            <GlassCard>
              <h2 className="text-lg font-bold dark:text-white text-gray-900 mb-4 flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-amber-400" />
                Unassigned Trips ({unassigned.length})
              </h2>
              {unassigned.length === 0 ? (
                <p className="text-sm dark:text-white/50 text-gray-400 text-center py-4">
                  All trips are assigned! Nothing to optimize.
                </p>
              ) : (
                <div className="space-y-2">
                  {unassigned.map((trip, i) => (
                    <div key={trip.id || i}
                      className="flex items-center gap-3 px-3 py-2.5 rounded-xl dark:bg-white/5 bg-gray-50 border dark:border-white/8 border-gray-100">
                      <Route className="w-4 h-4 text-amber-400 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm dark:text-white/80 text-gray-700 font-medium truncate">
                          {trip.serviceName || trip.service_name || trip.name || trip.service_code || 'Unnamed Trip'}
                        </p>
                        <p className="text-xs dark:text-white/40 text-gray-400">
                          {trip.firstPickUp || 'No time'} {trip.pickupAddress ? ` \u2022 ${trip.pickupAddress}` : ''}
                        </p>
                      </div>
                      <Badge variant="warning">{trip.tripStatus || trip.status || 'Unassigned'}</Badge>
                    </div>
                  ))}
                </div>
              )}

              {unassigned.length > 0 && (
                <button
                  onClick={handleOptimize}
                  disabled={optimizing}
                  className="mt-5 w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-amber-500 hover:bg-amber-600 text-white text-sm font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                >
                  {optimizing ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Analyzing all trips...</>
                  ) : (
                    <><Sparkles className="w-4 h-4" /> Auto-Optimize All Trips</>
                  )}
                </button>
              )}
            </GlassCard>

            {/* Optimization results */}
            {optimizeDone && (
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                className="space-y-4"
              >
                <h3 className="text-sm font-semibold dark:text-white/70 text-gray-600 uppercase tracking-wide flex items-center gap-2">
                  <Zap className="w-4 h-4 text-amber-400" />
                  Optimization Results
                </h3>
                {suggestions.length === 0 ? (
                  <GlassCard>
                    <p className="text-sm dark:text-white/50 text-gray-400 text-center py-4">
                      Could not generate suggestions. Try refreshing dispatch data.
                    </p>
                  </GlassCard>
                ) : (
                  suggestions.map((sug, si) => (
                    <motion.div
                      key={si}
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: si * 0.1 }}
                    >
                      <GlassCard>
                        <div className="flex items-center gap-2 mb-3">
                          <Route className="w-4 h-4 text-amber-400" />
                          <p className="font-semibold dark:text-white text-gray-900 text-sm">{sug.trip_name}</p>
                        </div>
                        {sug.recommendations.length === 0 ? (
                          <p className="text-xs dark:text-white/40 text-gray-400 italic">No drivers available</p>
                        ) : (
                          <div className="space-y-2">
                            {sug.recommendations.map((rec, ri) => {
                              const style = tierStyle(rec.tier)
                              return (
                                <div key={rec.person_id}
                                  className={`flex items-center gap-3 px-3 py-2.5 rounded-xl ${style.bg} border`}>
                                  <div className={`w-8 h-8 rounded-lg dark:bg-white/10 bg-white flex items-center justify-center text-sm font-bold flex-shrink-0 ${style.text}`}>
                                    {ri + 1}
                                  </div>
                                  <div className="flex-1 min-w-0">
                                    <p className={`text-sm font-medium ${style.text}`}>{rec.name}</p>
                                    <p className="text-xs dark:text-white/40 text-gray-500 truncate">{rec.reason}</p>
                                  </div>
                                  <span className={`text-xs px-2 py-0.5 rounded-full ${style.bg} ${style.text} border font-medium flex-shrink-0`}>
                                    {rec.tier_label}
                                  </span>
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </GlassCard>
                    </motion.div>
                  ))
                )}
              </motion.div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
