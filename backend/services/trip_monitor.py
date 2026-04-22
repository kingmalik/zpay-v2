"""
Trip acceptance & start monitor — background scheduler that checks live trip
data from FirstAlt and EverDriven, notifies drivers who haven't accepted or
started, and escalates to admin.

Uses APScheduler BackgroundScheduler (in-process, single instance).
WARNING: single-instance only — if Railway auto-scales, duplicates will occur.
"""

import os
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("zpay.trip-monitor")

# ── Configuration from env ────────────────────────────────────
_INTERVAL = int(os.environ.get("MONITOR_INTERVAL_MINUTES", "5"))
_START_HOUR = int(os.environ.get("MONITOR_START_HOUR", "5"))
_END_HOUR = int(os.environ.get("MONITOR_END_HOUR", "21"))
_REMINDER_WINDOW = int(os.environ.get("MONITOR_REMINDER_WINDOW_MINUTES", "60"))  # drivers can accept ~60 min before pickup
_CALL_DELAY = int(os.environ.get("MONITOR_CALL_DELAY_MINUTES", "20"))            # call 20 min after SMS if still unaccepted
_ESCALATION_DELAY = int(os.environ.get("MONITOR_ESCALATION_DELAY_MINUTES", "0")) # escalate immediately after call goes unanswered
_TZ_NAME = os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles")

# Start stage timing — matches accept chain so driver has lead time to roll,
# not scrambling at the pickup minute. Overridable via env vars.
_START_REMINDER_MINUTES = int(os.environ.get("MONITOR_START_REMINDER_MINUTES", "15"))
_START_CALL_DELAY = int(os.environ.get("MONITOR_START_CALL_DELAY_MINUTES", "10"))
_START_ESCALATION_DELAY = int(os.environ.get("MONITOR_START_ESCALATION_DELAY_MINUTES", "0"))
_ACCEPT_ESC_WINDOW = int(os.environ.get("MONITOR_ACCEPT_ESC_WINDOW_MINUTES", "20"))
_START_ESC_WINDOW = int(os.environ.get("MONITOR_START_ESC_WINDOW_MINUTES", "10"))
_DRY_RUN = os.environ.get("MONITOR_DRY_RUN", "false").lower() == "true"
_OVERDUE_GRACE = int(os.environ.get("MONITOR_OVERDUE_GRACE_MINUTES", "15"))

_scheduler = None
_last_run_info: dict = {"last_run": None, "summary": None, "error": None}
_blind_cycle_alerted: set = set()
_partner_fail_alerted: set = set()  # keyed by (date_iso, source) tuples
_liveness_alerted: dict = {}  # keyed by date_iso → True

# ── Trip classification — explicit, zero silent failures ─────────────
# Every trip pulled from the partner APIs is classified into EXACTLY ONE
# bucket. If we ever see a status string we don't recognize, we DO NOT
# silently skip — we alert Malik so he knows there's a gap AND can tell
# us which bucket to add it to.
#
# Buckets:
#   declined    — driver opted out / sub needed. Alert Malik immediately.
#   unaccepted  — driver assigned, needs to tap accept. SMS → call → escalate.
#   accepted    — driver accepted, not yet started. Start-stage tracking.
#   started     — driver is actively en route / on the run.
#   completed   — trip finished. No action.
#   cancelled   — trip cancelled by partner/rider. No action.
#   unknown     — we have NO idea. Alert Malik with the raw status.

# FirstAlt — keyword-based because FA occasionally varies status casing/phrasing.
# Checked in priority order: decline > complete/cancel > started > accepted > unaccepted.
_FA_DECLINED_MARKERS  = ("DECLIN", "SUBSTITUTE", "SUB_NEEDED", "REMOVED", "REJECT")
_FA_COMPLETED_MARKERS = ("COMPLET", "FINISH", "DONE")
_FA_CANCELLED_MARKERS = ("CANCEL", "CLOSE", "VOID")
_FA_STARTED_MARKERS   = ("IN_PROGRESS", "IN PROGRESS", "INPROGRESS", "PROGRESS",
                         "ENROUTE", "EN_ROUTE", "EN ROUTE", "PICKED_UP", "PICKED UP",
                         "ONBOARD", "ON_BOARD", "ARRIVED")
_FA_ACCEPTED_MARKERS  = ("ACCEPT",)
_FA_UNACCEPTED_MARKERS = ("DISPATCH", "PENDING", "ASSIGN", "OFFER", "OPEN",
                          "NOT_ACCEPTED", "NOT ACCEPTED", "AWAITING", "UNACCEPT")


def classify_fa(status: str) -> str:
    s = (status or "").upper().strip()
    if not s:
        return "unknown"
    # Exact-match check for ambiguous FA statuses that share substrings with
    # other markers. "SCHEDULED" = driver assigned, not yet accepted.
    if s == "SCHEDULED":
        return "unaccepted"
    # Priority order matters. Unaccepted checked BEFORE accepted because
    # strings like "NOT_ACCEPTED" / "AWAITING_ACCEPTANCE" contain "ACCEPT".
    if any(m in s for m in _FA_DECLINED_MARKERS):   return "declined"
    if any(m in s for m in _FA_COMPLETED_MARKERS):  return "completed"
    if any(m in s for m in _FA_CANCELLED_MARKERS):  return "cancelled"
    if any(m in s for m in _FA_STARTED_MARKERS):    return "started"
    if any(m in s for m in _FA_UNACCEPTED_MARKERS): return "unaccepted"
    if any(m in s for m in _FA_ACCEPTED_MARKERS):   return "accepted"
    return "unknown"


# EverDriven — enumerated states from ALC API + driverGUID presence.
_ED_STATE_MAP = {
    "Scheduled":       "accepted",   # with driverGUID; without → unaccepted (handled below)
    "Accepted":        "accepted",
    "Active":          "started",
    "AtStop":          "started",
    "ToStop":          "started",    # en route between pickup and dropoff
    "Completed":       "completed",
    "Declined":        "declined",
    "Cancelled":       "cancelled",
    "Canceled":        "cancelled",
    "NoShow":          "cancelled",  # rider didn't appear; driver did their job, no action needed
    "NoShowReported":  "cancelled",  # explicit report variant of NoShow — same outcome
    "RiderCanceled":   "cancelled",  # rider cancelled before pickup — partner-side cancel
    "Expired":         "cancelled",  # trip window lapsed without pickup — no action needed
}


def classify_ed(status: str, driver_guid: str | None) -> str:
    s = (status or "").strip()
    if not s and not driver_guid:
        return "unaccepted"  # no status, no driver = unassigned
    if not s:
        return "unknown"
    bucket = _ED_STATE_MAP.get(s)
    if bucket is None:
        return "unknown"
    # Scheduled without a driver = unaccepted; with driver = accepted
    if bucket == "accepted" and not driver_guid:
        return "unaccepted"
    return bucket


# ── Speech-friendly time formatter ───────────────────────────
def _speak_time(raw: str) -> str:
    """Format pickup time strings for speech: '2026-04-21T08:17:30' -> '8:17 AM'.
    Pass-through strings already in human format (e.g. '07:40 AM').
    """
    if not raw:
        return "unknown time"
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(raw[:19], fmt)
            return dt.strftime("%-I:%M %p")
        except ValueError:
            continue
    # Try short HH:MM (FirstAlt format like "07:40") — convert to 12-hr
    if len(raw) <= 5 and ":" in raw:
        try:
            h, m = raw.split(":")
            dt = datetime(2000, 1, 1, int(h), int(m))
            return dt.strftime("%-I:%M %p")
        except (ValueError, TypeError):
            pass
    return raw  # already readable (e.g. "7:40 AM") — leave alone


# ── Time parsing ──────────────────────────────────────────────
def _parse_pickup_time(pickup_str: str, trip_date: date, tz: ZoneInfo) -> datetime | None:
    """Parse pickup time string to a timezone-aware datetime."""
    if not pickup_str:
        return None
    try:
        # Try HH:MM format (FirstAlt)
        if len(pickup_str) <= 5 and ":" in pickup_str:
            h, m = pickup_str.split(":")
            return datetime(trip_date.year, trip_date.month, trip_date.day,
                            int(h), int(m), tzinfo=tz)
        # Try ISO-ish format (EverDriven: "2026-04-06T06:30")
        if "T" in pickup_str:
            dt = datetime.fromisoformat(pickup_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt
        # Try HH:MM AM/PM
        for fmt in ("%I:%M %p", "%I:%M%p"):
            try:
                t = datetime.strptime(pickup_str, fmt)
                return datetime(trip_date.year, trip_date.month, trip_date.day,
                                t.hour, t.minute, tzinfo=tz)
            except ValueError:
                continue
    except (ValueError, TypeError):
        pass
    return None


# ── Main monitoring cycle ─────────────────────────────────────
def run_monitoring_cycle() -> dict:
    """
    Execute one monitoring cycle. Called by APScheduler on interval.
    Returns a summary dict for dashboard consumption.
    """
    tz = ZoneInfo(_TZ_NAME)
    now = datetime.now(tz)

    # Operating hours gate
    if now.hour < _START_HOUR or now.hour >= _END_HOUR:
        logger.debug("[trip-monitor] Outside operating hours (%d:%02d), skipping", now.hour, now.minute)
        _last_run_info["last_run"] = now.isoformat()
        _last_run_info["summary"] = "Skipped — outside operating hours"
        return {"skipped": True}

    from backend.db import SessionLocal
    from backend.db.models import TripNotification, Person
    from backend.services import notification_service as _notify_real
    from backend.services.call_scripts import get_call_script, get_sms_script

    if _DRY_RUN:
        class _DryNotify:
            def send_sms(self, phone, msg): logger.info("[DRY RUN] SMS→%s: %s", phone, msg[:80])
            def make_call(self, phone, msg, **kw): logger.info("[DRY RUN] CALL→%s: %s", phone, msg[:80])
            def alert_admin(self, msg, **kw): logger.info("[DRY RUN] ADMIN: %s", msg[:100])
            def normalize_phone(self, phone): return phone
        notify = _DryNotify()
    else:
        notify = _notify_real

    db = SessionLocal()
    summary = {
        "trips_checked": 0,
        "accept_sms": 0, "accept_calls": 0, "accept_escalations": 0,
        "start_sms": 0, "start_calls": 0, "start_escalations": 0,
        "errors": [],
    }

    try:
        today = now.date()  # must match tz of `now` — Railway runs UTC, drivers are Pacific

        # ── Step 1: Pull live data ──
        fa_trips = []
        ed_runs = []

        fa_ok = False
        ed_ok = False
        try:
            from backend.services import firstalt_service
            fa_trips = firstalt_service.get_trips(today)
            fa_ok = True
        except Exception as e:
            summary["errors"].append(f"FirstAlt: {e}")
            logger.error("[trip-monitor] FirstAlt fetch failed: %s", e)

        try:
            from backend.services import everdriven_service
            ed_runs = everdriven_service.get_runs(today)
            ed_ok = True
        except Exception as e:
            summary["errors"].append(f"EverDriven: {e}")
            logger.error("[trip-monitor] EverDriven fetch failed: %s", e)

        # ── Per-partner failure alerts ──
        # If a single partner fetch fails (but the other is up), we still
        # process what we can — but Malik needs to know one side is blind.
        # Deduped per (source, day) so he only gets one alert per day per partner.
        if not fa_ok:
            _fa_key = (today.isoformat(), "firstalt")
            if _fa_key not in _partner_fail_alerted:
                _fa_err_str = summary["errors"][0] if summary["errors"] else "unknown error"
                try:
                    notify.alert_admin(
                        f"FIRSTALT API DOWN — fetch failed this cycle: {_fa_err_str}. "
                        "Trips from FA won't be monitored until this clears. "
                        "Check cognito/creds.",
                        spoken_message="FirstAlt is down. Trip monitor can't see FirstAlt trips.",
                    )
                except Exception as _fa_alert_err:
                    logger.error("[trip-monitor] Failed to send FA partner-fail alert: %s", _fa_alert_err)
                _partner_fail_alerted.add(_fa_key)

        if not ed_ok:
            _ed_key = (today.isoformat(), "everdriven")
            if _ed_key not in _partner_fail_alerted:
                _ed_err_str = next(
                    (e for e in summary["errors"] if "EverDriven" in e), summary["errors"][-1] if summary["errors"] else "unknown error"
                )
                try:
                    notify.alert_admin(
                        f"EVERDRIVEN API DOWN — fetch failed this cycle: {_ed_err_str}. "
                        "Trips from ED won't be monitored until this clears. "
                        "Check ALC credentials.",
                        spoken_message="EverDriven is down. Trip monitor can't see EverDriven trips.",
                    )
                except Exception as _ed_alert_err:
                    logger.error("[trip-monitor] Failed to send ED partner-fail alert: %s", _ed_alert_err)
                _partner_fail_alerted.add(_ed_key)

        # ── CRITICAL: Both partner APIs failed — monitor is BLIND this cycle ──
        # We can't see trips, so we can't call drivers or escalate. Alert Malik
        # so he knows the automation is down and he should check manually.
        # Deduped via a module-global set keyed to today — one alert per day.
        if not fa_ok and not ed_ok:
            if today.isoformat() not in _blind_cycle_alerted:
                try:
                    notify.alert_admin(
                        "MONITOR BLIND — both FirstAlt and EverDriven API fetches "
                        "failed this cycle. System cannot see any trips. "
                        "Check partner portals manually until this clears.",
                        spoken_message=(
                            "FirstAlt and EverDriven are both down. "
                            "The system can't see any trips."
                        ),
                    )
                except Exception as alert_err:
                    logger.error("[trip-monitor] Failed to send blind-cycle alert: %s", alert_err)
                _blind_cycle_alerted.add(today.isoformat())
                summary.setdefault("blind_cycle_alerts", 0)
                summary["blind_cycle_alerts"] += 1

        # ── Step 2: Build person lookup ──
        persons = db.query(Person).filter(Person.active == True).all()
        fa_id_to_person = {p.firstalt_driver_id: p for p in persons if p.firstalt_driver_id}
        ed_id_to_person = {str(p.everdriven_driver_id): p for p in persons if p.everdriven_driver_id}

        # ── Step 3: Process all trips ──
        all_trips = []

        for t in fa_trips:
            trip_id = str(t.get("tripId") or t.get("id") or "")
            if not trip_id:
                continue
            driver_id = t.get("driverId")
            person = fa_id_to_person.get(driver_id)
            status = t.get("tripStatus") or t.get("status") or ""
            bucket = classify_fa(status)
            all_trips.append({
                "source": "firstalt",
                "trip_ref": trip_id,
                "status": status,
                "bucket": bucket,
                "pickup_time": t.get("firstPickUp") or "",
                "person": person,
                "is_unaccepted": bucket == "unaccepted",
                "is_accepted": bucket == "accepted",
                "is_started": bucket == "started",
                "is_declined": bucket == "declined",
                "driver_name": ((t.get("driverFirstName") or "") + " " + (t.get("driverLastName") or "")).strip(),
            })

        for r in ed_runs:
            key = r.get("keyValue") or ""
            if not key:
                continue
            driver_id = r.get("driverId")
            person = ed_id_to_person.get(str(driver_id)) if driver_id else None
            status = r.get("tripStatus") or ""
            driver_guid = r.get("driverGUID")
            bucket = classify_ed(status, driver_guid)
            all_trips.append({
                "source": "everdriven",
                "trip_ref": key,
                "status": status,
                "bucket": bucket,
                "pickup_time": r.get("firstPickUp") or "",
                "person": person,
                "is_unaccepted": bucket == "unaccepted",
                "is_accepted": bucket == "accepted",
                "is_started": bucket == "started",
                "is_declined": bucket == "declined",
                "driver_name": r.get("driverName") or "",
            })

        summary["trips_checked"] = len(all_trips)
        summary["name_mismatches"] = 0
        summary["unknown_status_alerts"] = 0
        summary["declines"] = 0
        summary["start_suppressed_concurrent"] = 0

        # Drivers currently mid-ride on any trip — used to suppress Start
        # alerts on their *other* trips. A driver dropping off kid A at
        # 08:08 cannot also be picking up kid B at 08:13.
        busy_drivers: set[int] = {
            t["person"].person_id
            for t in all_trips
            if t.get("person") and t.get("is_started")
        }

        # ── Step 4: Upsert TripNotification rows + process ──
        for trip in all_trips:
            person = trip["person"]
            if not person:
                continue  # Can't notify unlinked drivers

            # ── Safety: cross-verify API driver name against DB person ──
            # Partners sometimes reassign driver IDs. A mismatch means the DB
            # has stale data — we never silently skip; we alert Malik so the
            # mapping can be corrected at the source.
            name_mismatch = False
            api_name_raw = (trip.get("driver_name") or "").strip()
            db_name_raw  = (person.full_name or "").strip()
            api_name = api_name_raw.lower()
            db_name = db_name_raw.lower()
            if api_name and db_name:
                api_tokens = {tok for tok in api_name.split() if len(tok) > 1}
                db_tokens = {tok for tok in db_name.split() if len(tok) > 1}
                if api_tokens and db_tokens and not (api_tokens & db_tokens):
                    name_mismatch = True

            if name_mismatch:
                source_label = "FirstAlt" if trip["source"] == "firstalt" else "EverDriven"
                stale_id = getattr(person, f"{trip['source']}_driver_id", "?")
                logger.error(
                    "[trip-monitor] NAME MISMATCH — source=%s ref=%s API='%s' DB='%s' stale_id=%s",
                    trip["source"], trip["trip_ref"], api_name_raw, db_name_raw, stale_id,
                )

                # Upsert a notif so the alert is deduped per trip per day.
                mismatch_notif = db.query(TripNotification).filter(
                    TripNotification.source == trip["source"],
                    TripNotification.trip_ref == trip["trip_ref"],
                    TripNotification.trip_date == today,
                ).first()
                if not mismatch_notif:
                    mismatch_notif = TripNotification(
                        person_id=person.person_id,
                        trip_date=today,
                        source=trip["source"],
                        trip_ref=trip["trip_ref"],
                        trip_status=trip["status"],
                        pickup_time=trip["pickup_time"],
                    )
                    db.add(mismatch_notif)
                    db.flush()

                if not mismatch_notif.accept_escalated_at:
                    notify.alert_admin(
                        f"NAME MISMATCH — {source_label} trip {trip['trip_ref']}: "
                        f"API says driver is '{api_name_raw or '?'}' but DB has "
                        f"'{db_name_raw or '?'}' (stored {trip['source']}_driver_id={stale_id}). "
                        f"Fix the mapping in Z-Pay before this driver's next trip.",
                        spoken_message=(
                            f"Heads up — the API and the database disagree on who's driving trip "
                            f"{trip['trip_ref']}. Check the mapping."
                        ),
                    )
                    mismatch_notif.accept_escalated_at = now
                    summary["name_mismatches"] += 1
                db.commit()
                # Don't run stages — we don't trust the mapping. Alert fires; Malik fixes.
                continue

            # Upsert TripNotification row FIRST so we can dedup alerts against it.
            notif = db.query(TripNotification).filter(
                TripNotification.source == trip["source"],
                TripNotification.trip_ref == trip["trip_ref"],
                TripNotification.trip_date == today,
            ).first()

            if not notif:
                notif = TripNotification(
                    person_id=person.person_id,
                    trip_date=today,
                    source=trip["source"],
                    trip_ref=trip["trip_ref"],
                    trip_status=trip["status"],
                    pickup_time=trip["pickup_time"],
                )
                db.add(notif)
                db.flush()
            else:
                notif.trip_status = trip["status"]

            # ── UNKNOWN STATUS — no silent failures. Alert Malik so he always
            # knows what's happening AND can tell us which bucket this status
            # belongs in. Deduped per trip per day via accept_escalated_at.
            if trip["bucket"] == "unknown":
                logger.error(
                    "[trip-monitor] UNKNOWN STATUS — source=%s ref=%s status=%r driver=%s",
                    trip["source"], trip["trip_ref"], trip["status"], person.full_name,
                )
                if not notif.accept_escalated_at:
                    source_label = "FirstAlt" if trip["source"] == "firstalt" else "EverDriven"
                    _unk_first = (person.full_name or "").split()[0] or "Driver"
                    notify.alert_admin(
                        f"UNKNOWN STATUS — {source_label} trip {trip['trip_ref']} "
                        f"for {person.full_name} at {trip['pickup_time'] or '?'}. "
                        f"Status: '{trip['status']}'. "
                        f"Check the dashboard now — system doesn't know how to handle this.",
                        spoken_message=(
                            f"{_unk_first}'s trip has a status I don't recognize. "
                            f"Check the dashboard."
                        ),
                    )
                    notif.accept_escalated_at = now
                    summary["unknown_status_alerts"] += 1
                # Do NOT run any further stages for an unknown-status trip —
                # the alert is your signal to check it yourself.
                continue

            # Update acceptance/start status
            just_accepted = False
            if trip["is_started"] and not notif.started_at:
                notif.started_at = now
            if (trip["is_accepted"] or trip["is_started"]) and not notif.accepted_at:
                notif.accepted_at = now
                just_accepted = True

            pickup_dt = _parse_pickup_time(trip["pickup_time"], today, tz)
            driver_phone = person.phone
            driver_name = (person.full_name or "").split()[0] or "Driver"
            source_label = "FirstAlt" if trip["source"] == "firstalt" else "EverDriven"

            # ── STAGE 0: DECLINE — highest priority, alert Malik immediately ──
            # Driver tapped "Substitute Needed" / declined. We never contact the
            # driver (they opted out). We alert Malik so he can assign a sub
            # before the partner sees a missed trip. Dedup via accept_escalated_at.
            if trip.get("is_declined"):
                if not notif.accept_escalated_at:
                    mins_left = None
                    if pickup_dt:
                        mins_left = round((pickup_dt - now).total_seconds() / 60)
                    when = (
                        f"{mins_left} min away" if mins_left is not None and mins_left >= 0
                        else (f"{-mins_left} min OVERDUE" if mins_left is not None else trip["pickup_time"])
                    )
                    _dec_first = (person.full_name or "").split()[0] or "Driver"
                    notify.alert_admin(
                        f"DECLINE — {person.full_name} declined {source_label} trip "
                        f"{trip['trip_ref']} at {trip['pickup_time']} ({when}). "
                        f"NEEDS SUB NOW.",
                        spoken_message=(
                            f"{_dec_first} just declined the "
                            f"{_speak_time(trip['pickup_time'])} trip. Needs a sub."
                        ),
                    )
                    notif.accept_escalated_at = now
                    summary["accept_escalations"] += 1
                    summary.setdefault("declines", 0)
                    summary["declines"] += 1
                # Do not run accept/start stages for a declined trip.
                continue
            driver_lang = person.language or "en"

            # ── PICKUP TIME PARSE FAILURE ──
            # If we can't parse the pickup time AND the trip is not already in
            # progress / done, we can't know when to act. Alert Malik so the
            # time format or the trip itself can be investigated. No silent skip.
            if pickup_dt is None and trip["bucket"] in ("unaccepted", "accepted"):
                if not notif.accept_escalated_at:
                    _tpf_first = (person.full_name or "").split()[0] or "Driver"
                    notify.alert_admin(
                        f"TIME PARSE FAIL — {source_label} trip {trip['trip_ref']} "
                        f"for {person.full_name}. Pickup='{trip['pickup_time']}' "
                        f"(can't read it). Status='{trip['status']}'. "
                        f"Check this trip manually NOW.",
                        spoken_message=(
                            f"Can't read the pickup time on {_tpf_first}'s trip. "
                            f"Check it manually."
                        ),
                    )
                    notif.accept_escalated_at = now
                    summary.setdefault("time_parse_failures", 0)
                    summary["time_parse_failures"] += 1
                continue

            # ── OVERDUE — pickup time has passed and trip is NOT on the road ──
            # This is the most critical alert type. Driver either never accepted
            # or accepted but never started, and we're already past pickup time.
            # Fast-track: call Malik immediately, bypass SMS/wait chain entirely.
            if pickup_dt is not None and now >= pickup_dt + timedelta(minutes=_OVERDUE_GRACE) and trip["bucket"] in ("unaccepted", "accepted"):
                mins_overdue = round((now - pickup_dt).total_seconds() / 60)
                problem = (
                    "NEVER ACCEPTED" if trip["bucket"] == "unaccepted"
                    else "ACCEPTED BUT NEVER STARTED"
                )
                # Dedicated overdue_alerted_at field — independent of Stage 1 accept_escalated_at
                # so pre-pickup escalations never silence the overdue alert.
                if not notif.overdue_alerted_at:
                    problem_spoken = (
                        "never accepted the trip"
                        if trip["bucket"] == "unaccepted"
                        else "accepted but never started"
                    )
                    _ov_first = (person.full_name or "").split()[0] or "Driver"
                    notify.alert_admin(
                        f"OVERDUE {mins_overdue} MIN — {source_label} trip "
                        f"{trip['trip_ref']} | {person.full_name} | pickup was "
                        f"{trip['pickup_time']} | {problem}. ACT NOW.",
                        spoken_message=(
                            f"{_ov_first} is {mins_overdue} minutes overdue. "
                            f"{'Accepted but never started' if trip['bucket'] == 'accepted' else 'Never accepted'}. "
                            f"Pickup was {_speak_time(trip['pickup_time'])}."
                        ),
                    )
                    notif.overdue_alerted_at = now
                    summary.setdefault("overdue_alerts", 0)
                    summary["overdue_alerts"] += 1
                # Do not run normal stages — Malik is already calling the shots.
                continue

            # ── Skip trips that are not actionable (cancelled / completed / etc.) ──
            # Only unaccepted or accepted trips need the SMS/call/escalation chain.
            # Without this gate, cancelled trips fall through to Stage 1 because
            # notif.accepted_at is null — and we end up calling drivers for rides
            # that no longer exist.
            if trip["bucket"] not in ("unaccepted", "accepted", "started"):
                continue

            # ── STAGE 1: Accept check ──
            if not notif.accepted_at and trip["is_unaccepted"]:
                mins_until_pickup = (pickup_dt - now).total_seconds() / 60 if pickup_dt else None

                if mins_until_pickup is not None and mins_until_pickup <= _REMINDER_WINDOW:
                    if not driver_phone or not notify.normalize_phone(driver_phone):
                        # No phone — immediate escalation within proximity window
                        if not notif.accept_escalated_at:
                            _accept_within_window = (
                                pickup_dt is None
                                or (pickup_dt - now).total_seconds() <= _ACCEPT_ESC_WINDOW * 60
                            )
                            if _accept_within_window:
                                _nph_first = (person.full_name or "").split()[0] or "Driver"
                                notify.alert_admin(
                                    f"{person.full_name} has an unaccepted {source_label} trip "
                                    f"at {trip['pickup_time']} but has no phone number on file.",
                                    spoken_message=(
                                        f"{_nph_first} has an unaccepted trip at "
                                        f"{_speak_time(trip['pickup_time'])} but no phone on file. "
                                        f"Reach them directly."
                                    ),
                                )
                            notif.accept_escalated_at = now
                            summary["accept_escalations"] += 1
                    else:
                        # SMS
                        if not notif.accept_sms_at:
                            sms_text = get_sms_script(
                                driver_lang, "accept",
                                driver_name=driver_name,
                                source=source_label,
                                pickup_time=_speak_time(trip["pickup_time"]),
                            )
                            notify.send_sms(driver_phone, sms_text)
                            notif.accept_sms_at = now
                            summary["accept_sms"] += 1

                        # Call (30 min after SMS)
                        elif not notif.accept_call_at and notif.accept_sms_at:
                            if (now - notif.accept_sms_at).total_seconds() >= _CALL_DELAY * 60:
                                call_text = get_call_script(
                                    driver_lang, "accept",
                                    driver_name=driver_name,
                                    pickup_time=_speak_time(trip["pickup_time"]),
                                )
                                notify.make_call(driver_phone, call_text, language=driver_lang)
                                notif.accept_call_at = now
                                summary["accept_calls"] += 1

                        # Escalation — immediate after call (_ESCALATION_DELAY=0 by default)
                        elif not notif.accept_escalated_at and notif.accept_call_at:
                            if (now - notif.accept_call_at).total_seconds() >= _ESCALATION_DELAY * 60:
                                mins_left = round((pickup_dt - now).total_seconds() / 60) if pickup_dt else "?"
                                route = trip.get("trip_ref", "?")
                                _accept_within_window = (
                                    pickup_dt is None
                                    or (pickup_dt - now).total_seconds() <= _ACCEPT_ESC_WINDOW * 60
                                )
                                if _accept_within_window:
                                    _esc_first = (person.full_name or "").split()[0] or "Driver"
                                    notify.alert_admin(
                                        f"UNACCEPTED TRIP — {person.full_name} | {source_label} | "
                                        f"Pickup: {trip['pickup_time']} ({mins_left} min away). "
                                        f"SMS + call sent. No response. You need to handle this.",
                                        spoken_message=(
                                            f"{_esc_first} hasn't accepted the "
                                            f"{_speak_time(trip['pickup_time'])} trip. "
                                            f"Texted and called — no response."
                                        ),
                                    )
                                    try:
                                        from backend.services.notification_service import send_whatsapp_alert
                                        send_whatsapp_alert(
                                            f"🚨 *UNACCEPTED TRIP*\n"
                                            f"Driver: {person.full_name}\n"
                                            f"Route: {route} ({source_label})\n"
                                            f"Pickup: {trip['pickup_time']} — {mins_left} min away\n"
                                            f"SMS + call sent. No response. Handle now."
                                        )
                                    except Exception as _wa_err:
                                        logger.warning("WhatsApp escalation alert failed: %s", _wa_err)
                                notif.accept_escalated_at = now
                                summary["accept_escalations"] += 1

            # ── STAGE 2: Start check ──
            elif notif.accepted_at and not notif.started_at and trip["is_accepted"] and not just_accepted:
                # Concurrent-trip suppression: if this driver is currently
                # mid-ride on another trip (ToPickup/ToStop/etc.), they
                # physically cannot start this one yet. Don't nag.
                if person.person_id in busy_drivers:
                    summary["start_suppressed_concurrent"] += 1
                    continue

                mins_until_pickup = (pickup_dt - now).total_seconds() / 60 if pickup_dt else None

                if mins_until_pickup is not None and mins_until_pickup <= _START_REMINDER_MINUTES:
                    if not driver_phone or not notify.normalize_phone(driver_phone):
                        if not notif.start_escalated_at:
                            _start_within_window = (
                                pickup_dt is None
                                or (pickup_dt - now).total_seconds() <= _START_ESC_WINDOW * 60
                            )
                            if _start_within_window:
                                _nph_s_first = (person.full_name or "").split()[0] or "Driver"
                                notify.alert_admin(
                                    f"{person.full_name} accepted their {source_label} trip at "
                                    f"{trip['pickup_time']} but hasn't started. No phone on file.",
                                    spoken_message=(
                                        f"{_nph_s_first} accepted the "
                                        f"{_speak_time(trip['pickup_time'])} trip but hasn't started. "
                                        f"No phone on file — reach them directly."
                                    ),
                                )
                            notif.start_escalated_at = now
                            summary["start_escalations"] += 1
                    else:
                        # Start SMS
                        if not notif.start_sms_at:
                            sms_text = get_sms_script(
                                driver_lang, "start",
                                driver_name=driver_name,
                                source=source_label,
                                pickup_time=_speak_time(trip["pickup_time"]),
                            )
                            notify.send_sms(driver_phone, sms_text)
                            notif.start_sms_at = now
                            summary["start_sms"] += 1

                        # Start call (10 min after SMS)
                        elif not notif.start_call_at and notif.start_sms_at:
                            if (now - notif.start_sms_at).total_seconds() >= _START_CALL_DELAY * 60:
                                call_text = get_call_script(
                                    driver_lang, "start",
                                    driver_name=driver_name,
                                    pickup_time=_speak_time(trip["pickup_time"]),
                                )
                                notify.make_call(driver_phone, call_text, language=driver_lang)
                                notif.start_call_at = now
                                summary["start_calls"] += 1

                        # Start escalation — immediate after call
                        elif not notif.start_escalated_at and notif.start_call_at:
                            if (now - notif.start_call_at).total_seconds() >= _START_ESCALATION_DELAY * 60:
                                mins_left = round((pickup_dt - now).total_seconds() / 60) if pickup_dt else "?"
                                route = trip.get("trip_ref", "?")
                                _start_within_window = (
                                    pickup_dt is None
                                    or (pickup_dt - now).total_seconds() <= _START_ESC_WINDOW * 60
                                )
                                if _start_within_window:
                                    _stesc_first = (person.full_name or "").split()[0] or "Driver"
                                    notify.alert_admin(
                                        f"NOT STARTED — {person.full_name} | {source_label} | "
                                        f"Pickup: {trip['pickup_time']} ({mins_left} min away). "
                                        f"Accepted but hasn't started. SMS + call sent. You need to handle this.",
                                        spoken_message=(
                                            f"{_stesc_first} accepted the "
                                            f"{_speak_time(trip['pickup_time'])} trip but hasn't started. "
                                            f"Texted and called — no response."
                                        ),
                                    )
                                    try:
                                        from backend.services.notification_service import send_whatsapp_alert
                                        send_whatsapp_alert(
                                            f"⚠️ *NOT STARTED*\n"
                                            f"Driver: {person.full_name}\n"
                                            f"Route: {route} ({source_label})\n"
                                            f"Pickup: {trip['pickup_time']} — {mins_left} min away\n"
                                            f"Accepted but hasn't started. SMS + call sent. Handle now."
                                        )
                                    except Exception as _wa_err:
                                        logger.warning("WhatsApp start-escalation alert failed: %s", _wa_err)
                                notif.start_escalated_at = now
                                summary["start_escalations"] += 1

        db.commit()

        logger.info(
            "[trip-monitor] Checked %d trips | Declines:%d | NameMismatch:%d | "
            "Unknown:%d | Accept SMS:%d Call:%d Esc:%d | "
            "Start SMS:%d Call:%d Esc:%d | Errors:%d",
            summary["trips_checked"],
            summary.get("declines", 0),
            summary.get("name_mismatches", 0),
            summary.get("unknown_status_alerts", 0),
            summary["accept_sms"], summary["accept_calls"], summary["accept_escalations"],
            summary["start_sms"], summary["start_calls"], summary["start_escalations"],
            len(summary["errors"]),
        )

    except Exception as e:
        logger.exception("[trip-monitor] Cycle failed: %s", e)
        summary["errors"].append(str(e))
        db.rollback()
    finally:
        db.close()

    _last_run_info["last_run"] = now.isoformat()
    _last_run_info["summary"] = summary
    _last_run_info["error"] = summary["errors"][-1] if summary["errors"] else None
    return summary


# ── Scheduler management ──────────────────────────────────────


def check_liveness() -> dict:
    """
    Check whether the scheduler has been running cycles recently.
    Fires a one-per-day alert to Malik if the monitor appears stale
    (no cycle in > 3x the configured interval) during operating hours.

    Returns a dict with keys: healthy (bool), last_run (str|None), stale_minutes (float|None).
    """
    tz = ZoneInfo(_TZ_NAME)
    now = datetime.now(tz)
    last_run_str = _last_run_info.get("last_run")

    result: dict = {"healthy": True, "last_run": last_run_str, "stale_minutes": None}

    # Only check during operating hours — silence outside them.
    in_hours = _START_HOUR <= now.hour < _END_HOUR
    if _scheduler is None or not in_hours or not last_run_str:
        return result

    try:
        last_run_dt = datetime.fromisoformat(last_run_str)
        if last_run_dt.tzinfo is None:
            last_run_dt = last_run_dt.replace(tzinfo=tz)
        stale_threshold = _INTERVAL * 3 * 60  # seconds
        elapsed = (now - last_run_dt).total_seconds()
        if elapsed > stale_threshold:
            stale_minutes = round(elapsed / 60, 1)
            result["healthy"] = False
            result["stale_minutes"] = stale_minutes
            today_iso = now.date().isoformat()
            if today_iso not in _liveness_alerted:
                try:
                    from backend.services import notification_service as notify_real
                    notify_real.alert_admin(
                        f"TRIP MONITOR STALE — no cycle in {stale_minutes} min "
                        f"(interval={_INTERVAL}m). Scheduler may be frozen. "
                        "Check Railway logs and restart if needed.",
                        spoken_message="Trip monitor stopped running cycles.",
                    )
                except Exception as _lv_err:
                    logger.error("[trip-monitor] Failed to send liveness alert: %s", _lv_err)
                _liveness_alerted[today_iso] = True
    except (ValueError, TypeError) as e:
        logger.warning("[trip-monitor] check_liveness: could not parse last_run: %s", e)

    return result


def _startup_self_test() -> list[str]:
    """
    Verify that every env var needed to alert Malik is set. Returns a list
    of missing-var error strings; empty list means ready to run.
    """
    required = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "ADMIN_PHONE"]
    missing = [v for v in required if not os.environ.get(v, "").strip()]
    return missing


def start_monitor():
    """Start the background monitoring scheduler."""
    global _scheduler
    if _scheduler is not None:
        logger.warning("[trip-monitor] Scheduler already running")
        return

    # Hard gate: refuse to start blind. If we can't alert Malik, don't run —
    # a running monitor with no alert channel is worse than no monitor.
    # Skip in dry-run mode — no real notifications will be sent anyway.
    if not _DRY_RUN:
        missing = _startup_self_test()
        if missing:
            logger.error(
                "[trip-monitor] REFUSING TO START — missing required env vars: %s. "
                "Monitor disabled until these are set on Railway.",
                ", ".join(missing),
            )
            return
    else:
        logger.info("[trip-monitor] DRY RUN mode — skipping credential check, no SMS/calls will be sent")

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    # Wrap the cycle so a bug in one run can never kill the scheduler.
    def _safe_cycle():
        try:
            run_monitoring_cycle()
        except Exception as e:
            logger.exception("[trip-monitor] Uncaught cycle error: %s", e)
            try:
                from backend.services import notification_service as _real
                _real.alert_admin(
                    f"Monitor cycle crashed with uncaught error: {str(e)[:120]}. "
                    "Check Railway logs.",
                    spoken_message=(
                        "The monitor crashed. Check the Railway logs."
                    ),
                )
            except Exception:
                pass

    _scheduler = BackgroundScheduler(timezone=_TZ_NAME)
    # CronTrigger aligned to clock minutes (e.g. every 5 min → :00, :05, :10…)
    # so cycles are predictable — important for escalation timing. If _INTERVAL
    # doesn't divide 60 evenly we fall back to "every N minutes" cron syntax.
    if 60 % _INTERVAL == 0:
        cron_minute = f"*/{_INTERVAL}"
    else:
        cron_minute = f"*/{_INTERVAL}"  # APScheduler still accepts this
    _scheduler.add_job(
        _safe_cycle,
        trigger=CronTrigger(minute=cron_minute, timezone=_TZ_NAME),
        id="trip_monitor",
        name="Trip Acceptance & Start Monitor",
        replace_existing=True,
        max_instances=1,  # never overlap cycles
        coalesce=True,    # collapse missed runs into one
        misfire_grace_time=300,
    )
    _scheduler.start()
    logger.info("[trip-monitor] Scheduler started — interval: %d min, hours: %d-%d %s",
                _INTERVAL, _START_HOUR, _END_HOUR, _TZ_NAME)


def stop_monitor():
    """Shut down the background scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[trip-monitor] Scheduler stopped")


def get_status() -> dict:
    """Return current monitor status for the dashboard."""
    return {
        "enabled": _scheduler is not None,
        "last_run": _last_run_info.get("last_run"),
        "summary": _last_run_info.get("summary"),
        "error": _last_run_info.get("error"),
        "interval_minutes": _INTERVAL,
        "operating_hours": f"{_START_HOUR}:00 - {_END_HOUR}:00 {_TZ_NAME}",
    }
