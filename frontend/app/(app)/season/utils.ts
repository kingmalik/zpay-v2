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

/** Notes fields chain multiple bits together with these separators (PDF intake
 * joins with " · ", see backend/services/ride_pdf_intake.py:270; older imports
 * use "." or ";"). The student line must stop at the first one so it doesn't
 * swallow whatever field comes after it. */
const NOTES_FIELD_STOP = /[.·;\n]/

/** Pull the student line out of a ride's imported notes.
 * Handles "Student: Aiden Sakoda. …" and bare "Jamal Abu Dayeh + monitor. …". */
/** Untagged fallback only accepts something that reads like a person's name:
 * 2–5 Title-Case words (optionally "+ monitor"), no digits, no ALL-CAPS notes,
 * no "note:" prefix. Rejects "STUDENT NEEDS TO BE MET BY AN ADULT". */
const LOOKS_LIKE_NAME = /^[A-Z][a-z'’-]+(?: [A-Z][a-z'’-]+){1,4}(?: \+ .+)?$/

export function studentFromNotes(notes: string | null | undefined): string | null {
  if (!notes) return null
  const tagged = /Students?(?:\(s\))?:\s*([^.·;\n]+)/i.exec(notes)
  const firstSegment = (notes.split(NOTES_FIELD_STOP)[0] || '').trim()
  const line = tagged ? tagged[1].trim() : LOOKS_LIKE_NAME.test(firstSegment) ? firstSegment : ''
  if (!line) return null
  return line.length > 60 ? `${line.slice(0, 57)}…` : line
}
