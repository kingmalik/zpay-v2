# Dispatcher Runbook — One Page

> DRAFT by Fable 2026-07-09 from history + intake notes. Malik: correct by one
> voice note, no sit-down. Written for mom — the screen is `/ops/live`.

## The morning sweep (5:30–8:00am)

Open **/ops/live**. It shows ONLY the drivers who need you — same colors as
FirstAlt's board:

- **RED — act now.** Unaccepted with pickup ≤30 min away, running late, or urgent.
- **YELLOW — watch.** Unaccepted but there's still time. The system is already on it.
- **GREEN — leave them alone.** Hidden by default. An empty queue = everyone's fine.

The system works the ladder before you do: it texts the driver in their own
language when a trip sits unaccepted inside the reminder window, calls ~3 min
later if still nothing, then escalates to you. Your job starts at RED.

## When a row goes RED

1. Call the driver.
2. Tap the call result on the row — one tap, that's the whole report:
   - **✓** answered (say what they told you in your head, move on)
   - **✗** no answer
   - **👻** ghosted — you're done waiting; go straight to finding a replacement.
     The how-dare-you call happens after the kids are covered, not before.
3. Ghost taps train the system: that driver gets watched earlier next time.

Snooze a row if the driver answered and is handling it. Resolve it when it's
truly done. Mute a driver only if the system is nagging about something you
already know.

## Fire playbook

| Fire | First move | Then |
|---|---|---|
| **Accident** | Driver + kids safe? 911 if any doubt | Call partner dispatch, then Malik. Nothing else matters until kids are placed. |
| **Kid meltdown / behavior** | Driver stays parked, does NOT transport a kid in crisis alone | Call school/guardian per partner protocol; log what happened for the partner. |
| **Traffic / running late** | Driver keeps driving — you call the school, not the driver | 20+ min late shows on the board automatically; no separate report needed. |
| **No-show driver (ghost)** | 👻 tap, replacement immediately — nearest driver you trust with that school run | Post-mortem call with the ghost AFTER coverage. Repeat ghosts stop getting first call. |
| **Same-day callout** | Treat as ghost minus the attitude — replacement first | If it's a pattern, it feeds their tier; chronic callouts = coaching conversation. |

## What the system already does (don't duplicate it)

- Watches both boards (FirstAlt + EverDriven) every minute, 4am–10pm.
- Texts unaccepted drivers inside the reminder window, in EN/AR/AM
  (**once languages are filled in at /drivers/language**), calls if ignored,
  escalates to the phone in your pocket.
- Knows the fleet: trusted drivers (most of them) never surface unless
  actually red; the handful of chronic ones surface earliest.
- Notices when a trip disappears from the partner board (cancelled) and stops
  chasing it — a "feed dropped" note explains why the row went quiet.
- Alerts Malik if a partner API goes down or the monitor itself stops.

## Rules of thumb

- If the queue is empty, it's empty — don't go hunting in the partner portals.
- Trust the colors. RED before YELLOW, always.
- Every call gets a one-tap result. Ten seconds of tapping is what makes the
  system smarter than the portals.
