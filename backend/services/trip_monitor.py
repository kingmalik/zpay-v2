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
_INTERVAL = int(os.environ.get("MONITOR_INTERVAL_MINUTES", "15"))
_START_HOUR = int(os.environ.get("MONITOR_START_HOUR", "5"))
_END_HOUR = int(os.environ.get("MONITOR_END_HOUR", "20"))
_REMINDER_WINDOW = int(os.environ.get("MONITOR_REMINDER_WINDOW_MINUTES", "75"))
_CALL_DELAY = int(os.environ.get("MONITOR_CALL_DELAY_MINUTES", "30"))
_ESCALATION_DELAY = int(os.environ.get("MONITOR_ESCALATION_DELAY_MINUTES", "15"))
_TZ_NAME = os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles")

# Start stage timing
_START_REMINDER_MINUTES = 15  # SMS 15 min before pickup
_START_CALL_DELAY = 10        # Call 10 min after start SMS
_START_ESCALATION_DELAY = 5   # Escalate 5 min after start call

_scheduler = None
_last_run_info: dict = {"last_run": None, "summary": None, "error": None}

# ── FirstAlt acceptance detection ─────────────────────────────
_FA_TERMINAL = ("ACCEPT", "COMPLET", "CANCEL", "CLOSE")
_FA_STARTED = ("IN_PROGRESS", "PROGRESS")


def _fa_is_unaccepted(status: str) -> bool:
    s = (status or "").upper()
    return not any(t in s for t in _FA_TERMINAL)


def _fa_is_accepted(status: str) -> bool:
    s = (status or "").upper()
    return any(t in s for t in ("ACCEPT",)) and not any(t in s for t in ("COMPLET", "CANCEL", "CLOSE"))


def _fa_is_started(status: str) -> bool:
    s = (status or "").upper()
    return any(t in s for t in _FA_STARTED)


# ── EverDriven detection ──────────────────────────────────────
_ED_ACTIVE = {"Active", "AtStop"}
_ED_TERMINAL = {"Completed", "Declined"}


def _ed_is_unaccepted(status: str, driver_guid: str | None) -> bool:
    return status not in (_ED_ACTIVE | _ED_TERMINAL) or not driver_guid


def _ed_is_started(status: str) -> bool:
    return status in _ED_ACTIVE


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
    from backend.services import notification_service as notify

    db = SessionLocal()
    summary = {
        "trips_checked": 0,
        "accept_sms": 0, "accept_calls": 0, "accept_escalations": 0,
        "start_sms": 0, "start_calls": 0, "start_escalations": 0,
        "errors": [],
    }

    try:
        today = date.today()

        # ── Step 1: Pull live data ──
        fa_trips = []
        ed_runs = []

        try:
            from backend.services import firstalt_service
            fa_trips = firstalt_service.get_trips(today)
        except Exception as e:
            summary["errors"].append(f"FirstAlt: {e}")
            logger.error("[trip-monitor] FirstAlt fetch failed: %s", e)

        try:
            from backend.services import everdriven_service
            ed_runs = everdriven_service.get_runs(today)
        except Exception as e:
            summary["errors"].append(f"EverDriven: {e}")
            logger.error("[trip-monitor] EverDriven fetch failed: %s", e)

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
            all_trips.append({
                "source": "firstalt",
                "trip_ref": trip_id,
                "status": status,
                "pickup_time": t.get("firstPickUp") or "",
                "person": person,
                "is_unaccepted": _fa_is_unaccepted(status),
                "is_accepted": _fa_is_accepted(status),
                "is_started": _fa_is_started(status),
                "driver_name": t.get("driverFirstName", "") + " " + t.get("driverLastName", ""),
            })

        for r in ed_runs:
            key = r.get("keyValue") or ""
            if not key:
                continue
            driver_id = r.get("driverId")
            person = ed_id_to_person.get(str(driver_id)) if driver_id else None
            status = r.get("tripStatus") or ""
            driver_guid = r.get("driverGUID")
            all_trips.append({
                "source": "everdriven",
                "trip_ref": key,
                "status": status,
                "pickup_time": r.get("firstPickUp") or "",
                "person": person,
                "is_unaccepted": _ed_is_unaccepted(status, driver_guid),
                "is_accepted": not _ed_is_unaccepted(status, driver_guid) and not _ed_is_started(status),
                "is_started": _ed_is_started(status),
                "driver_name": r.get("driverName") or "",
            })

        summary["trips_checked"] = len(all_trips)

        # ── Step 4: Upsert TripNotification rows + process ──
        for trip in all_trips:
            person = trip["person"]
            if not person:
                continue  # Can't notify unlinked drivers

            # Upsert
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

            # Update acceptance/start status
            if trip["is_started"] and not notif.started_at:
                notif.started_at = now
            if (trip["is_accepted"] or trip["is_started"]) and not notif.accepted_at:
                notif.accepted_at = now

            pickup_dt = _parse_pickup_time(trip["pickup_time"], today, tz)
            driver_phone = person.phone
            driver_name = (person.full_name or "").split()[0] or "Driver"
            source_label = "FirstAlt" if trip["source"] == "firstalt" else "EverDriven"

            # ── STAGE 1: Accept check ──
            if not notif.accepted_at:
                mins_until_pickup = (pickup_dt - now).total_seconds() / 60 if pickup_dt else None

                if mins_until_pickup is not None and mins_until_pickup <= _REMINDER_WINDOW:
                    if not driver_phone or not notify.normalize_phone(driver_phone):
                        # No phone — immediate escalation
                        if not notif.accept_escalated_at:
                            notify.alert_admin(
                                f"{person.full_name} has an unaccepted {source_label} trip "
                                f"at {trip['pickup_time']} but has no phone number on file."
                            )
                            notif.accept_escalated_at = now
                            summary["accept_escalations"] += 1
                    else:
                        # SMS
                        if not notif.accept_sms_at:
                            notify.send_sms(
                                driver_phone,
                                f"Hi {driver_name}, you have an unaccepted {source_label} trip "
                                f"at {trip['pickup_time']}. Please accept it in your driver app."
                            )
                            notif.accept_sms_at = now
                            summary["accept_sms"] += 1

                        # Call (30 min after SMS)
                        elif not notif.accept_call_at and notif.accept_sms_at:
                            if (now - notif.accept_sms_at).total_seconds() >= _CALL_DELAY * 60:
                                notify.make_call(
                                    driver_phone,
                                    f"This is Z-Pay. You have an unaccepted {source_label} trip "
                                    f"at {trip['pickup_time']}. Please open your driver app and accept the trip."
                                )
                                notif.accept_call_at = now
                                summary["accept_calls"] += 1

                        # Escalation (15 min after call)
                        elif not notif.accept_escalated_at and notif.accept_call_at:
                            if (now - notif.accept_call_at).total_seconds() >= _ESCALATION_DELAY * 60:
                                notify.alert_admin(
                                    f"{person.full_name} has NOT accepted their {source_label} trip "
                                    f"at {trip['pickup_time']}. SMS sent at "
                                    f"{notif.accept_sms_at.strftime('%-I:%M %p') if notif.accept_sms_at else '?'}, "
                                    f"call at {notif.accept_call_at.strftime('%-I:%M %p') if notif.accept_call_at else '?'}."
                                )
                                notif.accept_escalated_at = now
                                summary["accept_escalations"] += 1

            # ── STAGE 2: Start check ──
            elif notif.accepted_at and not notif.started_at:
                mins_until_pickup = (pickup_dt - now).total_seconds() / 60 if pickup_dt else None

                if mins_until_pickup is not None and mins_until_pickup <= _START_REMINDER_MINUTES:
                    if not driver_phone or not notify.normalize_phone(driver_phone):
                        if not notif.start_escalated_at:
                            notify.alert_admin(
                                f"{person.full_name} accepted their {source_label} trip at "
                                f"{trip['pickup_time']} but hasn't started. No phone on file."
                            )
                            notif.start_escalated_at = now
                            summary["start_escalations"] += 1
                    else:
                        # Start SMS
                        if not notif.start_sms_at:
                            notify.send_sms(
                                driver_phone,
                                f"Hi {driver_name}, your {source_label} trip starts at "
                                f"{trip['pickup_time']} — time to head out!"
                            )
                            notif.start_sms_at = now
                            summary["start_sms"] += 1

                        # Start call (10 min after SMS)
                        elif not notif.start_call_at and notif.start_sms_at:
                            if (now - notif.start_sms_at).total_seconds() >= _START_CALL_DELAY * 60:
                                notify.make_call(
                                    driver_phone,
                                    f"Z-Pay reminder. Your {source_label} trip at "
                                    f"{trip['pickup_time']} starts soon. Please start driving now."
                                )
                                notif.start_call_at = now
                                summary["start_calls"] += 1

                        # Start escalation (5 min after call)
                        elif not notif.start_escalated_at and notif.start_call_at:
                            if (now - notif.start_call_at).total_seconds() >= _START_ESCALATION_DELAY * 60:
                                notify.alert_admin(
                                    f"{person.full_name} accepted but has NOT started their "
                                    f"{source_label} trip at {trip['pickup_time']}."
                                )
                                notif.start_escalated_at = now
                                summary["start_escalations"] += 1

        db.commit()

        total_actions = (
            summary["accept_sms"] + summary["accept_calls"] + summary["accept_escalations"]
            + summary["start_sms"] + summary["start_calls"] + summary["start_escalations"]
        )
        logger.info(
            "[trip-monitor] Checked %d trips | Accept SMS:%d Call:%d Esc:%d | "
            "Start SMS:%d Call:%d Esc:%d | Errors:%d",
            summary["trips_checked"],
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

def start_monitor():
    """Start the background monitoring scheduler."""
    global _scheduler
    if _scheduler is not None:
        logger.warning("[trip-monitor] Scheduler already running")
        return

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    _scheduler = BackgroundScheduler(timezone=_TZ_NAME)
    _scheduler.add_job(
        run_monitoring_cycle,
        trigger=IntervalTrigger(minutes=_INTERVAL),
        id="trip_monitor",
        name="Trip Acceptance & Start Monitor",
        replace_existing=True,
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
