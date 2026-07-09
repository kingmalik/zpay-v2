# S2 Morning-Sweep Audit — 2026-07-09

**Verdict: the monitor is not parked — it has been LIVE since 2026-05-29 and it passes.**
The master plan's premise ("parked in MONITOR_DRY_RUN=true since 2026-05-08") was stale:
the W22 watcher go-live session (2026-05-29) flipped `MONITOR_DRY_RUN=false`, and prod
has been sending real driver SMS/calls ever since (most recent: 2026-07-08, Mohammed
Reshid MUSSA, accepted 2 min after the text).

## Live performance since go-live (May 29 → Jul 8, prod data)

| Metric | Value |
|---|---|
| Trips monitored | 1,722 |
| Needed zero intervention | 1,691 (98.2%) |
| Accept SMS fired → driver accepted | 29 / 29 actionable (100%) |
| SMS fired, never accepted | 2 — both vanished from the FA feed next poll (cancelled partner-side); correct non-escalation |
| Silent misses (never accepted, monitor did nothing) | **0** |
| Start stage | 1,685 started unprompted · 2 SMS→started · 1 SMS-never-started |
| Escalations to admin | 55 accept-stage (mostly no-phone-on-file path) · 3 calls · 1 dedup |

**The plan's exit test ("one week of dry-run logs that match reality") is exceeded: six
weeks of LIVE logs with zero misses.**

## Chronic-group hypothesis: confirmed

Fleet median nudge rate ≈ 3%. Outliers: Mohammed Reshid MUSSA 17.9% (7/39),
Yonas Yergu 15.8%, Mohammad karim Naseri 15.8% — a small group eats the attention,
exactly as Malik described. Data supports auto-tiering.

## What already exists (plan didn't credit it)

- **Trilingual scripts (en / ar / am)** in `call_scripts.py`, keyed off `person.language` — **but all 135 active drivers have `language` unset**, so everyone gets English. Data gap, not code gap.
- **Scorecard engine** (`driver_scorecard.py`): 7 axes incl. acceptance, on-time start, responsiveness; gold/silver/bronze/probation tiers; `/api/data/reliability/driver/{id}` drilldown.
- **Two UIs**: `/dispatch/monitor` (overview + forensics) and `/ops/live` (live queue with snooze, severity, mute, pause).
- **Severity tiers** on notifications (critical/urgent/normal/silent), set per event (decline→urgent, overdue→critical).
- Operator overrides: snooze, manually-resolve, mute-all, dedup.

## Real gaps (S2 build list)

1. **Tier-aware timing** — thresholds are fleet-flat env vars. Wire Trusted/Watch/Chronic policy into when SMS fires and who surfaces on mom's screen. Ship behind `MONITOR_TIER_POLICY=0` (Malik flips — driver-comms gate honored).
2. **Mom's exception queue in FA traffic-light colors** — `/ops/live` exists but speaks severity jargon, not FA red/yellow/green.
3. **Call-disposition capture** — one-tap answered / no-answer / ghosted on each escalated card; feeds tier + scorecard.
4. **`person.language` backfill** — 135/135 unset; templates are dead code until filled (mom/Malik data task).
5. Minor observability: record "trip dropped from partner feed" so dangling SMS cases are explained (the 2 edge cases above).
6. Minor: 20 IN_PROGRESS trips missing `started_at` inference (poll-gap artifact, not real misses).
