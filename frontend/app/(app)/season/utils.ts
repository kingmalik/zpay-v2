/** Formats a 'HH:MM' 24h time string (season_ride.pickup_time convention) to h:mm AM/PM. */
export function formatHHMM(time: string | null | undefined): string {
  if (!time) return '—'
  const match = /^(\d{1,2}):(\d{2})/.exec(time)
  if (!match) return time
  let hour = parseInt(match[1], 10)
  const minute = match[2]
  const suffix = hour >= 12 ? 'PM' : 'AM'
  hour = hour % 12
  if (hour === 0) hour = 12
  return `${hour}:${minute} ${suffix}`
}

export function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message
  return fallback
}
