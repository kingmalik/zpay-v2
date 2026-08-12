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

/** "AM 1 — Kirkland↔Redmond (1 ride)" → "AM 1" (chip-sized loop reference). */
export function shortLoopLabel(label: string): string {
  return label.split(' — ')[0] || label
}

/** Pull the student line out of a ride's imported notes.
 * Handles "Student: Aiden Sakoda. …" and bare "Jamal Abu Dayeh + monitor. …". */
export function studentFromNotes(notes: string | null | undefined): string | null {
  if (!notes) return null
  const tagged = /Students?:\s*([^.]+)/i.exec(notes)
  const line = (tagged ? tagged[1] : notes.split('.')[0] || '').trim()
  if (!line) return null
  return line.length > 60 ? `${line.slice(0, 57)}…` : line
}
