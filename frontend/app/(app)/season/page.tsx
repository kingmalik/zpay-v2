'use client'

import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import BoardHeader from './BoardHeader'
import CorridorGrid from './CorridorGrid'
import ImportDialog from './ImportDialog'
import LoopsPanel from './LoopsPanel'
import RideEditDialog from './RideEditDialog'
import UnplacedBucket from './UnplacedBucket'
import { getBoard, getCapabilities, getLoops, proposeLoops, unassignRide } from './seasonApi'
import { apiErrorMessage } from './utils'
import { DEFAULT_SEASON } from './types'
import type { BoardResponse, DayPart, DriverCapabilityRow, LoopOut, RideOut } from './types'

export default function SeasonBoardPage() {
  const [board, setBoard] = useState<BoardResponse | null>(null)
  const [loops, setLoops] = useState<LoopOut[]>([])
  const [drivers, setDrivers] = useState<DriverCapabilityRow[]>([])
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const [district, setDistrict] = useState('all')
  const [dayPart, setDayPart] = useState<DayPart>('AM')
  const [weekday, setWeekday] = useState('M')

  const [importOpen, setImportOpen] = useState(false)
  const [proposing, setProposing] = useState(false)
  const [editingRide, setEditingRide] = useState<RideOut | null>(null)

  const loadBoard = useCallback(async () => {
    try {
      const b = await getBoard({
        season: DEFAULT_SEASON,
        district: district === 'all' ? undefined : district,
        day_part: dayPart,
        weekday,
      })
      setBoard(b)
      setFetchError(null)
    } catch (e) {
      setFetchError(apiErrorMessage(e, 'Failed to load season board'))
    }
  }, [district, dayPart, weekday])

  const loadLoops = useCallback(async () => {
    try {
      const l = await getLoops(DEFAULT_SEASON)
      setLoops(l)
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Failed to load loops'))
    }
  }, [])

  const loadDrivers = useCallback(async () => {
    try {
      const d = await getCapabilities()
      setDrivers(d)
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Failed to load driver capabilities'))
    }
  }, [])

  const loadAll = useCallback(async () => {
    setLoading(true)
    await Promise.all([loadBoard(), loadLoops(), loadDrivers()])
    setLoading(false)
  }, [loadBoard, loadLoops, loadDrivers])

  useEffect(() => { loadAll() }, [loadAll])

  async function handleUnassign(ride: RideOut) {
    try {
      await unassignRide(ride.season_ride_id)
      toast.success(`Unassigned ${ride.school_display} #${ride.number}`)
      await Promise.all([loadBoard(), loadLoops()])
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Failed to unassign ride'))
    }
  }

  async function handlePropose() {
    setProposing(true)
    try {
      await proposeLoops({ season: DEFAULT_SEASON, day_part: dayPart, weekday })
      toast.success('Loops proposed')
      await loadLoops()
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Failed to propose loops'))
    } finally {
      setProposing(false)
    }
  }

  if (loading && !board) return <LoadingSpinner fullPage />

  if (fetchError && !board) {
    return (
      <div className="max-w-7xl mx-auto py-10">
        <div className="rounded-2xl p-6 bg-red-500/10 border border-red-500/20 text-center">
          <p className="text-red-400 font-medium">Failed to load season board</p>
          <p className="text-sm dark:text-white/40 text-gray-400 mt-1">{fetchError}</p>
          <button
            onClick={loadAll}
            className="mt-4 px-4 py-2 rounded-xl text-sm bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  const stats = board?.stats || { total: 0, assigned: 0, unassigned: 0, needs_info: 0 }
  const corridors = board?.corridors || []
  const unplaced = board?.unplaced || []
  const districts = board?.districts || []

  return (
    <div className="max-w-[1600px] mx-auto space-y-5 py-6">
      <BoardHeader
        stats={stats}
        districts={districts}
        district={district}
        onDistrictChange={setDistrict}
        dayPart={dayPart}
        onDayPartChange={setDayPart}
        weekday={weekday}
        onWeekdayChange={setWeekday}
        onImportClick={() => setImportOpen(true)}
        onProposeClick={handlePropose}
        proposing={proposing}
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_320px] items-start">
        <div className="space-y-5 min-w-0">
          <CorridorGrid corridors={corridors} onUnassign={handleUnassign} />
          <UnplacedBucket rides={unplaced} onEdit={setEditingRide} />
        </div>
        <LoopsPanel loops={loops} drivers={drivers} onChanged={() => { loadBoard(); loadLoops() }} />
      </div>

      <ImportDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        onImported={() => { loadBoard() }}
      />

      <RideEditDialog
        ride={editingRide}
        onClose={() => setEditingRide(null)}
        onSaved={() => { setEditingRide(null); loadBoard() }}
      />
    </div>
  )
}
