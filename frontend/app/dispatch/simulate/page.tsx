'use client'

import { useEffect, useState } from 'react'
import { Loader2, GitBranch, Settings, AlertTriangle } from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface SimTrip { id?: string | number; pickup_time?: string; service_name?: string; origin?: string }
interface SimDriver { id?: string | number; name?: string; address?: string; trips?: SimTrip[]; conflicts?: number }
interface SimData { drivers?: SimDriver[]; unassigned?: SimTrip[]; stats?: { total?: number; conflicts?: number } }

export default function SimulatePage() {
  const [data, setData] = useState<SimData | null>(null)
  const [loading, setLoading] = useState(true)
  const [optimizing, setOptimizing] = useState(false)
  const [date, setDate] = useState(new Date().toISOString().split('T')[0])
  const [testDriver, setTestDriver] = useState({ name: '', address: '' })
  const [showTestForm, setShowTestForm] = useState(false)

  useEffect(() => {
    // Load initial data if endpoint available
    setLoading(false)
  }, [])

  async function optimize() {
    setOptimizing(true)
    try {
      const res = await api.post<SimData>('/dispatch/simulate/optimize', { date, test_driver: testDriver.name ? testDriver : undefined })
      setData(res)
    } catch (e) { console.error(e) }
    finally { setOptimizing(false) }
  }

  if (loading) return <LoadingSpinner fullPage />

  const stats = data?.stats || {}
  const drivers = data?.drivers || []
  const unassigned = data?.unassigned || []

  return (
    <div className="max-w-7xl mx-auto space-y-5 py-6">
      {/* Header controls */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Dispatch Simulator</h1>
        <div className="flex items-center gap-3">
          <input type="date" value={date} onChange={e => setDate(e.target.value)}
            className="px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
          <button onClick={() => setShowTestForm(!showTestForm)}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm dark:bg-white/8 bg-gray-100 dark:text-white/70 text-gray-600 hover:dark:bg-white/12 hover:bg-gray-200 transition-all cursor-pointer">
            <Settings className="w-4 h-4" />
            Test Driver
          </button>
          <button onClick={optimize} disabled={optimizing}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all cursor-pointer disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #667eea, #10B981)' }}>
            {optimizing ? <Loader2 className="w-4 h-4 animate-spin" /> : <GitBranch className="w-4 h-4" />}
            {optimizing ? 'Optimizing...' : 'Optimize'}
          </button>
        </div>
      </div>

      {/* Test driver form */}
      {showTestForm && (
        <GlassCard>
          <h3 className="text-sm font-semibold dark:text-white/70 text-gray-700 mb-3">Add Test Driver</h3>
          <div className="flex gap-3">
            <input value={testDriver.name} onChange={e => setTestDriver(s => ({ ...s, name: e.target.value }))} placeholder="Driver name"
              className="flex-1 px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
            <input value={testDriver.address} onChange={e => setTestDriver(s => ({ ...s, address: e.target.value }))} placeholder="Home address"
              className="flex-1 px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
          </div>
        </GlassCard>
      )}

      {/* Status bar */}
      {data && (
        <div className="flex gap-4 px-4 py-3 rounded-2xl dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 text-sm">
          <span className="dark:text-white/60 text-gray-600">Total: <strong className="dark:text-white text-gray-800">{stats.total || 0}</strong></span>
          <span className={stats.conflicts ? 'text-red-400' : 'text-emerald-400'}>
            Conflicts: <strong>{stats.conflicts || 0}</strong>
          </span>
        </div>
      )}

      {!data ? (
        <div className="text-center py-16 dark:text-white/30 text-gray-400">
          <GitBranch className="w-12 h-12 mx-auto mb-3 opacity-20" />
          <p>Select a date and click Optimize to simulate dispatch</p>
        </div>
      ) : (
        <>
          {/* Driver cards */}
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
            {drivers.map((driver, i) => (
              <div key={driver.id || i} className="rounded-2xl dark:bg-white/5 dark:border dark:border-white/10 bg-white border border-gray-200 overflow-hidden">
                <div className="px-4 py-3 border-b dark:border-white/8 border-gray-100 flex items-center justify-between">
                  <div>
                    <p className="font-semibold dark:text-white text-gray-800 text-sm">{driver.name}</p>
                    <p className="text-xs dark:text-white/40 text-gray-400">{driver.address}</p>
                  </div>
                  {(driver.conflicts || 0) > 0 && (
                    <span className="flex items-center gap-1 text-xs text-red-400 bg-red-500/10 px-2 py-0.5 rounded-full">
                      <AlertTriangle className="w-3 h-3" />{driver.conflicts}
                    </span>
                  )}
                </div>
                <div className="divide-y dark:divide-white/5 divide-gray-50">
                  {(driver.trips || []).map((trip, j) => (
                    <div key={trip.id || j} className="px-4 py-2.5 flex items-center justify-between">
                      <div>
                        <p className="text-xs font-medium dark:text-white/80 text-gray-700">{trip.pickup_time}</p>
                        <p className="text-xs dark:text-white/40 text-gray-400">{trip.service_name}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Unassigned */}
          {unassigned.length > 0 && (
            <div>
              <h2 className="text-sm text-amber-400 font-semibold mb-2">Unassigned ({unassigned.length})</h2>
              <div className="rounded-xl border-2 border-amber-500/30 bg-amber-500/5 divide-y dark:divide-amber-500/10 divide-amber-100">
                {unassigned.map((t, i) => (
                  <div key={t.id || i} className="px-4 py-2.5 text-sm dark:text-white/70 text-gray-600">
                    {t.pickup_time} — {t.service_name}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
