'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Loader2, Pencil } from 'lucide-react'
import SeasonDialog from './SeasonDialog'
import { patchRide } from './seasonApi'
import { apiErrorMessage } from './utils'
import type { RideOut } from './types'

interface RideEditDialogProps {
  ride: RideOut | null
  onClose: () => void
  onSaved: () => void
}

export default function RideEditDialog({ ride, onClose, onSaved }: RideEditDialogProps) {
  const [pickupAddress, setPickupAddress] = useState('')
  const [dropoffAddress, setDropoffAddress] = useState('')
  const [pickupTime, setPickupTime] = useState('')
  const [dropoffTime, setDropoffTime] = useState('')
  const [saving, setSaving] = useState(false)

  // Reset local form state whenever a new ride is opened
  useEffect(() => {
    if (!ride) return
    setPickupAddress(ride.pickup_address || '')
    setDropoffAddress(ride.dropoff_address || '')
    setPickupTime(ride.pickup_time || '')
    setDropoffTime(ride.dropoff_time || '')
  }, [ride])

  async function save() {
    if (!ride) return
    setSaving(true)
    try {
      await patchRide(ride.season_ride_id, {
        pickup_address: pickupAddress.trim() || undefined,
        dropoff_address: dropoffAddress.trim() || undefined,
        pickup_time: pickupTime.trim() || undefined,
        dropoff_time: dropoffTime.trim() || undefined,
      })
      toast.success('Ride updated')
      onSaved()
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Failed to update ride'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <SeasonDialog
      open={!!ride}
      onOpenChange={o => { if (!o) onClose() }}
      title={ride?.school_display || 'Edit ride'}
      description={ride ? `#${ride.number} · ${ride.direction}` : undefined}
      icon={<Pencil className="w-5 h-5 text-[#667eea]" />}
    >
      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Pickup address</label>
          <input
            type="text"
            value={pickupAddress}
            onChange={e => setPickupAddress(e.target.value)}
            placeholder="123 Main St, Kirkland, WA"
            className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
          />
        </div>
        <div>
          <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Dropoff address</label>
          <input
            type="text"
            value={dropoffAddress}
            onChange={e => setDropoffAddress(e.target.value)}
            placeholder="456 School Rd, Redmond, WA"
            className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Pickup time</label>
            <input
              type="time"
              value={pickupTime}
              onChange={e => setPickupTime(e.target.value)}
              className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
            />
          </div>
          <div>
            <label className="block text-xs font-medium dark:text-white/60 text-gray-500 mb-1">Dropoff time</label>
            <input
              type="time"
              value={dropoffTime}
              onChange={e => setDropoffTime(e.target.value)}
              className="w-full px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
            />
          </div>
        </div>
      </div>

      <div className="flex justify-end gap-2 mt-5">
        <button
          onClick={onClose}
          className="px-4 py-2 rounded-xl text-sm dark:text-white/60 text-gray-500 dark:hover:bg-white/5 hover:bg-gray-100"
        >
          Cancel
        </button>
        <button
          onClick={save}
          disabled={saving}
          className="px-4 py-2 rounded-xl text-sm font-medium text-white flex items-center gap-2 disabled:opacity-50 bg-[#667eea] hover:bg-[#5a72d8]"
        >
          {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          Save
        </button>
      </div>
    </SeasonDialog>
  )
}
