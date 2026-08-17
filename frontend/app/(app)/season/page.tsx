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
import { getBoard, getCapabilities, getLoops, patchRide, proposeLoops, unassignRide } from './seasonApi'
import { apiErrorMessage, formatHHMM, shortLoopLabel, studentFromNotes } from './utils'
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

  /** Single-ride assignment (2026-08-17): one ride straight to one driver,
   * no loop involved — loops stay untouched for when volume comes back. */
  async function handleAssignRide(ride: RideOut, personId: number) {
    const driverName = drivers.find(d => d.person_id === personId)?.name ?? 'driver'
    try {
      await patchRide(ride.season_ride_id, { assigned_person_id: personId })
      toast.success(`Assigned ${ride.school_display} #${ride.number} to ${driverName}`)
      await Promise.all([loadBoard(), loadLoops()])
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Failed to assign ride'))
    }
  }

  async function handlePropose() {
    setProposing(true)
    try {
      // Propose across the whole day (no day_part scope) so AM/PM loops build
      // together and companion pairing can link a driver's morning + afternoon.
      await proposeLoops({ season: DEFAULT_SEASON })
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
  const loopLabels = Object.fromEntries(loops.map(l => [l.loop_id, shortLoopLabel(l.label)]))

  /** CSVs of every assigned ride (driver confirmed), ONE FILE PER COMPANY —
   * the FirstAlt sheet goes to Branden and must never contain EverDriven rides.
   * Reads ONLY the fresh unfiltered board — mixing stale `loops` state with a
   * fresh fetch could duplicate or misattribute rows. Loop-assign stamps
   * assigned_person_id on every ride in the loop, so one pass over the fresh
   * board's rides (corridors + unplaced) covers both assignment modes. */
  async function handleExport() {
    const rowsBySource: Record<string, string[][]> = {}
    const pushRow = (r: RideOut, driverName: string) => {
      const source = r.source || 'firstalt'
      rowsBySource[source] = rowsBySource[source] || []
      rowsBySource[source].push([
        r.school_display, `#${r.number}`, r.direction,
        r.days || 'M,T,W,R,F',
        `${formatHHMM(r.pickup_time)}-${formatHHMM(r.dropoff_time)}`,
        studentFromNotes(r.notes) || '',
        `${r.pickup_city || ''} to ${r.dropoff_city || ''}`,
        driverName,
      ])
    }
    try {
      const fullBoard = await getBoard({ season: DEFAULT_SEASON })
      const assignedRides = [...fullBoard.corridors.flatMap(c => c.rides), ...fullBoard.unplaced]
        .filter(r => r.status === 'assigned' && r.assigned_person)
      for (const r of assignedRides) pushRow(r, r.assigned_person!.name)
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Failed to load season board — export aborted'))
      return
    }
    const sources = Object.keys(rowsBySource)
    if (sources.length === 0) {
      toast.error('No assigned rides to export yet — assign drivers first')
      return
    }
    const header = ['School', 'Route', 'Direction', 'Days', 'Time', 'Student', 'Cities', 'Driver']
    const companyName: Record<string, string> = { firstalt: 'FirstAlt', everdriven: 'EverDriven' }
    for (const source of sources) {
      const csv = [header, ...rowsBySource[source]]
        .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
        .join('\n')
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
      const a = document.createElement('a')
      a.href = url
      a.download = `${(companyName[source] || source).toLowerCase()}-assigned-rides-${DEFAULT_SEASON}.csv`
      a.click()
      URL.revokeObjectURL(url)
    }
    const parts = sources.map(s => `${companyName[s] || s}: ${rowsBySource[s].length}`)
    toast.success(`Exported ${parts.join(' · ')} — one file per company`)
  }

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
        onExportClick={handleExport}
        proposing={proposing}
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_320px] items-start">
        <div className="space-y-5 min-w-0">
          <CorridorGrid
            corridors={corridors}
            loopLabels={loopLabels}
            onUnassign={handleUnassign}
            drivers={drivers}
            rideCounts={board?.driver_ride_counts ?? {}}
            onAssign={handleAssignRide}
          />
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
