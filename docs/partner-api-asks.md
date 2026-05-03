# Partner API Asks — Driver Scorecard Data Gaps

## Why We Need These Fields

Z-Pay now runs a weekly driver scorecard that grades every driver across six axes: acceptance rate, on-time start, pickup arrival, dropoff completion, responsiveness, and reliability. The scorecard drives priority dispatch — Gold-tier drivers get offered trips first, Probation-tier drivers get coaching nudges. Right now two of those axes are either disabled or running on partial data because the timing information we need does not come through in the current report formats. Closing these gaps does not just help us — it helps FA and EverDriven too, because the drivers covering their routes become measurably better, and we have the receipts to prove it.

---

## FirstAlt — What We Need

### Current state

The weekly `Prod_SP_Acumen International_*.xlsx` Brandon emails has two useful tabs:
- `SP PAY SUMMARY` — per-driver roll-up (days, runs, miles, gross, deductions, net)
- `SP ITEMIZED REPORT` — per-trip detail (trip code, date, route name, miles, gross)

The itemized tab is the workhorse for billing reconciliation. What it's missing is timing.

### Fields we need added

| Field | What it is | Format preferred |
|---|---|---|
| `scheduled_dropoff_time` | The time the student is supposed to arrive at school / be dropped off | `HH:MM` in the same timezone column as pickup, or an ISO datetime |
| `driver_arrived_at_pickup_timestamp` | The moment the driver marked themselves "at pickup" in FA's driver app | ISO datetime (UTC or local with offset) |

The `scheduled_dropoff_time` is the bigger unlock. Without it, the On-time Dropoff axis (10% of the composite score) is completely disabled — we cannot tell whether drivers are getting kids to school on time because we have no target to compare against. The driver arrival timestamp is the second priority — right now we infer pickup arrival from status transitions we watch in real time, but the FA-side timestamp would give us a ground-truth fallback for trips where the live poll missed the transition.

### What to ask Brandon

> "Brandon — as we improve our tracking on the driver side, two timestamps from your system would help us a lot. First, the scheduled dropoff time per trip (when the student is supposed to arrive). Second, if your driver app records when the driver taps 'at pickup', that timestamp per trip. Could those be added as columns to the SP ITEMIZED tab in the weekly export? Even just the scheduled dropoff time would unlock a full reliability metric we currently have to skip."

### Does FA have an API?

Currently the only data exchange is the xlsx Brandon emails weekly. We do not have confirmed access to a live FA API endpoint. Asking about API access is a reasonable follow-up after confirming whether the xlsx export can be extended — it's lower friction to ask for two new columns first before proposing a full integration change.

---

## EverDriven — What We Need

### Current state

Z-Pay polls the EverDriven GraphQL API during active dispatch to track trip status in real time. The introspection script lives at `backend/scripts/ed_introspect.py` (Phase 4 of the scorecard build) — it has not been run against production yet. Running it would confirm exactly which timestamp fields exist on their schema. Until then, we're working from what ED has documented and what we can infer from current polling behavior.

### Fields we need added (or confirmed available)

| Field | GraphQL location (likely) | What it unlocks |
|---|---|---|
| `driverArrivedAtPickupAt` | `Trip.statusHistory` or `Trip.driverEvents` | Ground-truth pickup arrival timestamp for On-time Pickup axis |
| `scheduledDropoffTime` | `Trip.dropoff.scheduledAt` or similar | Enables On-time Dropoff axis (same gap as FA) |
| `callAttempted` / `callAnswered` | `Trip.communicationEvents[]` | Responsiveness axis — right now we count any call placed as answered; we can't distinguish unanswered calls |

### What to ask ED

The ED contact is more technical so you can reference the GraphQL schema directly.

> "Hi — we're building a driver reliability scoring system on top of the ED dispatch feed. We're currently polling the GraphQL API for real-time status transitions. A few fields would complete our picture: (1) the driver-confirmed 'at pickup' timestamp on each trip — does that exist on `Trip.statusHistory` or a driver events array? (2) scheduled dropoff time — we have pickup time but not dropoff target. (3) call communication events — specifically whether a call to a driver was attempted vs. answered. If any of these are on the schema already, pointing us to the right field names would be enough. If not, is there a roadmap conversation we could have?"

### Introspection follow-up

Before sending the ED email, it's worth running the introspection script to see exactly what's on the schema. That way the ask is specific rather than exploratory:

```bash
railway login
railway link
railway run python -m backend.scripts.ed_introspect
```

If the hidden timestamp fields already exist, we skip the ask entirely and just update `driver_scorecard.py` to read them. If they're missing, the email above gives ED exactly what they need to scope the addition.

---

## Email Templates — Ready to Send

### To Brandon (FirstAlt)

```
Subject: Quick question on the weekly SP ITEMIZED report

Hey Brandon,

Hope you're doing well. As we've been building out our driver tracking on our end, there are two data points from your side that would help us close a gap in reliability reporting.

The first is the scheduled dropoff time per trip — the time the student is supposed to arrive at their destination. We have the pickup time already, but without the dropoff target we can't measure whether drivers are completing trips on schedule.

The second is the driver's "at pickup" timestamp — if your driver app records when the driver taps that they've arrived at the pickup location, that timestamp per trip would let us cross-check what we're tracking on our end.

Could either of those be added as columns in the SP ITEMIZED tab of the weekly export? Even just the scheduled dropoff time would unlock a reporting axis we currently have to disable.

No rush — just want to flag it while we're actively building this out.

Thanks,
Malik
```

---

### To EverDriven (Technical Contact)

```
Subject: GraphQL schema question — driver arrival + call events

Hi [Name],

We're building a driver reliability scoring layer on top of the EverDriven dispatch feed. We're already polling the GraphQL API for live status transitions and it's been working well.

A few fields would complete our scoring model:

1. Driver-confirmed "at pickup" timestamp — does this exist on Trip.statusHistory or a separate driver events type? We're looking for the moment the driver confirms they've arrived at the pickup location.

2. Scheduled dropoff time — we have pickup time but not the target dropoff time. Looking for the field name if it exists (something like Trip.dropoff.scheduledAt).

3. Call communication events — we track responsiveness, and right now we can't distinguish between a call that was attempted vs. one that was answered. If there are call event types on the schema (callAttempted / callAnswered or equivalent), pointing us to those would let us report this accurately.

If these are already on the schema, field names are enough. If not, happy to discuss whether they're on the roadmap.

Thanks,
Malik
```

---

## What Unlocks When Each Field Ships

| Field | Axis affected | Current state | After field is available |
|---|---|---|---|
| `scheduled_dropoff_time` (FA or ED) | On-time Dropoff (10% weight) | Disabled — `available=False`, weight redistributed to other 5 axes | Live — axis re-enabled, composite score recalculates with full 6 axes |
| `driver_arrived_at_pickup_timestamp` (FA) | On-time Pickup (25% weight) | Active but inferred from live poll — misses transitions if poll window is off | Full accuracy — FA ground-truth fills gaps where real-time polling missed the status change |
| `driverArrivedAtPickupAt` (ED GraphQL) | On-time Pickup (25% weight) | Same — inferred from status transitions | Same improvement as FA version, applies to ED trips |
| `callAttempted` / `callAnswered` events | Responsiveness (10% weight) | Degraded — any trip with `accept_call_at` or `start_call_at` non-null is counted as "call answered"; unanswered calls are invisible | Accurate — we can distinguish drivers who picked up from drivers who didn't; unanswered calls correctly penalize the axis |

---

## Appendix — Current Scorecard Axes

### All six axes and their weights

| Axis | Weight | Current state |
|---|---|---|
| Acceptance | 25% (rescaled to ~27.8% while dropoff is disabled) | Live |
| On-time Start | 20% (rescaled to ~22.2%) | Live |
| On-time Pickup Arrival | 25% (rescaled to ~27.8%) | Live — degraded on FA (inferred vs. ground truth) |
| On-time Dropoff Completion | 10% | **Disabled — no `scheduled_dropoff` column** |
| Responsiveness | 10% (rescaled to ~11.1%) | Live — degraded (can't distinguish unanswered calls) |
| Reliability | 10% (rescaled to ~11.1%) | Live |

Tier thresholds: Gold >= 90, Silver 80-89, Bronze 70-79, Probation < 70.

### Code reference — disabled axis

From `backend/services/driver_scorecard.py`:

```python
# ── On-time completion — UNAVAILABLE (no scheduled_dropoff column) ────────
# Axis is excluded from composite by setting available=False.
# Weights for remaining axes are renormalized below.
completion_available = False

# ...

available_axes = {
    "acceptance": True,
    "on_time_start": True,
    "on_time_pickup_arrival": True,
    "on_time_completion": False,  # no scheduled_dropoff
    "responsiveness": True,
    "reliability": True,
}
total_available_weight = sum(
    AXIS_WEIGHTS[k] for k, avail in available_axes.items() if avail
)
# Scale factor so available axes still sum to 100
weight_scale = 1.0 / total_available_weight if total_available_weight > 0 else 1.0
```

To re-enable on-time completion once the data is available:
1. Add `scheduled_dropoff` column to `trip_notification` table (migration needed)
2. Backfill from FA xlsx / ED GraphQL
3. Flip `"on_time_completion": True` in the `available_axes` dict
4. Remove the `weight_scale` override for that axis — weights will rebalance automatically

To fix responsiveness once call events are instrumented:
1. Add `call_attempted` / `call_answered` event types to `notification_event` table
2. Update `trip_monitor.py` to write those rows on call placement + Twilio `answeredBy` webhook
3. Update `_compute_responsiveness()` in `driver_scorecard.py` to read from `notification_event` instead of `trip_notification.accept_call_at`
