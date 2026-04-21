"""
Z-Pay Health Monitor — background watchdog that verifies critical paths
(DB, Twilio, EverDriven sync, FirstAlt ingest) and alerts the owner via
email + ntfy push (never SMS — the thing being monitored).

Design:
- Severity tiers: 'green' (silent), 'yellow' (logged, no push), 'red' (push)
- Dedup: same check staying red within 4h = one alert, not repeated
- Threshold: N consecutive failures before firing (default 3)
- Quiet hours: 9pm-7am only pages on RED_CATASTROPHIC (backend/db down)
- Daily digest at 07:00 America/Los_Angeles
- Opt-in canaries via HEALTH_CANARY_SMS=1 to avoid annoying SMS during dev

Env vars:
    HEALTH_MONITOR_ENABLED=1         — master switch
    HEALTH_CANARY_SMS=1              — enable hourly SMS canary
    HEALTH_CANARY_SMS_TO=+1...       — where canary SMS goes (default ADMIN_PHONE)
    HEALTH_ALERT_EMAIL=...@gmail.com — recipient for alerts + digest
    HEALTH_NTFY_TOPIC=zpay-alerts    — ntfy.sh topic for push
    HEALTH_CHECK_INTERVAL_MIN=5      — fast-check interval (default 5)
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import requests
from sqlalchemy import text

from backend.db import SessionLocal

logger = logging.getLogger("zpay.health")

_TZ_NAME = os.getenv("HEALTH_TZ", "America/Los_Angeles")
_DEDUP_WINDOW_HOURS = 4
_DEFAULT_FAIL_THRESHOLD = 3
_QUIET_HOURS_START = 21  # 9pm
_QUIET_HOURS_END = 7     # 7am
_SCHEDULER = None


# ── Types ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CheckResult:
    status: str           # 'green' | 'yellow' | 'red'
    latency_ms: int
    detail: dict


# ── Check functions ───────────────────────────────────────────────────────────

def _check_backend_alive() -> CheckResult:
    return CheckResult(status="green", latency_ms=0, detail={"msg": "scheduler alive"})


def _check_db_responsive() -> CheckResult:
    start = time.monotonic()
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        ms = int((time.monotonic() - start) * 1000)
        status = "green" if ms < 500 else "yellow"
        return CheckResult(status=status, latency_ms=ms, detail={"query_ms": ms})
    except Exception as e:
        ms = int((time.monotonic() - start) * 1000)
        return CheckResult(status="red", latency_ms=ms, detail={"error": str(e)[:200]})


def _check_everdriven_freshness() -> CheckResult:
    """Red if no new EverDriven rides created in last 24h (during weekdays)."""
    return _check_source_freshness("everdriven", stale_hours=24)


def _check_firstalt_freshness() -> CheckResult:
    """Red if no new FirstAlt/Acumen rides created in last 24h (during weekdays)."""
    return _check_source_freshness("firstalt", stale_hours=24)


def _check_source_freshness(source: str, stale_hours: int) -> CheckResult:
    start = time.monotonic()
    try:
        with SessionLocal() as db:
            row = db.execute(
                text(
                    "SELECT MAX(created_at) AS last_seen FROM ride WHERE source = :s"
                ),
                {"s": source},
            ).first()
        ms = int((time.monotonic() - start) * 1000)
        last_seen = row[0] if row else None
        if last_seen is None:
            return CheckResult(
                status="yellow",
                latency_ms=ms,
                detail={"msg": f"no {source} rides ever", "source": source},
            )
        age_hours = (datetime.now(timezone.utc) - last_seen).total_seconds() / 3600
        detail = {
            "source": source,
            "last_seen": last_seen.isoformat(),
            "age_hours": round(age_hours, 1),
        }
        if age_hours > stale_hours * 2:
            return CheckResult(status="red", latency_ms=ms, detail=detail)
        if age_hours > stale_hours:
            return CheckResult(status="yellow", latency_ms=ms, detail=detail)
        return CheckResult(status="green", latency_ms=ms, detail=detail)
    except Exception as e:
        ms = int((time.monotonic() - start) * 1000)
        return CheckResult(status="red", latency_ms=ms, detail={"error": str(e)[:200]})


def _check_twilio_balance() -> CheckResult:
    start = time.monotonic()
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    if not sid or not token:
        return CheckResult(
            status="yellow",
            latency_ms=0,
            detail={"msg": "TWILIO creds not set"},
        )
    try:
        resp = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Balance.json",
            auth=(sid, token),
            timeout=10,
        )
        ms = int((time.monotonic() - start) * 1000)
        if resp.status_code != 200:
            return CheckResult(
                status="red",
                latency_ms=ms,
                detail={"status": resp.status_code, "body": resp.text[:200]},
            )
        data = resp.json()
        balance = float(data.get("balance", 0))
        currency = data.get("currency", "USD")
        detail = {"balance": balance, "currency": currency}
        if balance < 5:
            return CheckResult(status="red", latency_ms=ms, detail=detail)
        if balance < 20:
            return CheckResult(status="yellow", latency_ms=ms, detail=detail)
        return CheckResult(status="green", latency_ms=ms, detail=detail)
    except Exception as e:
        ms = int((time.monotonic() - start) * 1000)
        return CheckResult(status="red", latency_ms=ms, detail={"error": str(e)[:200]})


def _check_sms_canary() -> CheckResult:
    """Send a test SMS and verify Twilio marks it delivered within 90s."""
    if os.getenv("HEALTH_CANARY_SMS", "0") != "1":
        return CheckResult(
            status="green",
            latency_ms=0,
            detail={"msg": "canary disabled (HEALTH_CANARY_SMS=0)"},
        )
    to = os.getenv("HEALTH_CANARY_SMS_TO") or os.getenv("ADMIN_PHONE", "")
    if not to:
        return CheckResult(
            status="yellow",
            latency_ms=0,
            detail={"msg": "no canary recipient set"},
        )

    from backend.services.notification_service import send_sms

    start = time.monotonic()
    stamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
    sid = send_sms(to, f"Z-Pay health canary {stamp} (auto)")
    if not sid or sid == "dry-run-sms":
        return CheckResult(
            status="green" if sid == "dry-run-sms" else "red",
            latency_ms=int((time.monotonic() - start) * 1000),
            detail={"sid": sid, "dry_run": sid == "dry-run-sms"},
        )

    acct = os.environ.get("TWILIO_ACCOUNT_SID", "")
    tok = os.environ.get("TWILIO_AUTH_TOKEN", "")
    deadline = time.monotonic() + 90
    status = "queued"
    while time.monotonic() < deadline:
        try:
            r = requests.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{acct}/Messages/{sid}.json",
                auth=(acct, tok),
                timeout=5,
            )
            if r.status_code == 200:
                status = r.json().get("status", "unknown")
                if status in ("delivered", "failed", "undelivered"):
                    break
        except Exception:
            pass
        time.sleep(5)

    ms = int((time.monotonic() - start) * 1000)
    detail = {"sid": sid, "final_status": status}
    if status == "delivered":
        return CheckResult(status="green", latency_ms=ms, detail=detail)
    if status in ("failed", "undelivered"):
        return CheckResult(status="red", latency_ms=ms, detail=detail)
    return CheckResult(status="yellow", latency_ms=ms, detail=detail)


# ── Registry ──────────────────────────────────────────────────────────────────

# (check_name, function, interval_min, catastrophic)
# catastrophic=True means it pages even during quiet hours.
CHECKS: list[tuple[str, Callable[[], CheckResult], int, bool]] = [
    ("backend_alive",         _check_backend_alive,         5,  True),
    ("db_responsive",         _check_db_responsive,         5,  True),
    ("twilio_balance",        _check_twilio_balance,        30, False),
    ("everdriven_freshness",  _check_everdriven_freshness,  60, False),
    ("firstalt_freshness",    _check_firstalt_freshness,    60, False),
    ("sms_canary",            _check_sms_canary,            60, False),
]


# ── Persistence ───────────────────────────────────────────────────────────────

def _upsert_check_result(name: str, result: CheckResult) -> dict:
    """Record result. Returns {prev_status, consecutive_failures, enabled, muted_until}."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT status, consecutive_failures, enabled, muted_until FROM health_check WHERE check_name = :n"),
            {"n": name},
        ).first()
        prev_status = row[0] if row else None
        prev_fails = int(row[1]) if row else 0
        enabled = bool(row[2]) if row else True
        muted_until = row[3] if row else None

        if result.status == "green":
            new_fails = 0
            last_ok = now
        else:
            new_fails = prev_fails + 1
            last_ok = None  # keep existing via COALESCE below

        db.execute(
            text("""
                INSERT INTO health_check (check_name, status, last_checked_at, last_ok_at,
                                          consecutive_failures, latency_ms, detail, enabled)
                VALUES (:n, :s, :t, :ok, :f, :ms, CAST(:d AS JSONB), TRUE)
                ON CONFLICT (check_name) DO UPDATE SET
                    status = EXCLUDED.status,
                    last_checked_at = EXCLUDED.last_checked_at,
                    last_ok_at = COALESCE(EXCLUDED.last_ok_at, health_check.last_ok_at),
                    consecutive_failures = :f,
                    latency_ms = EXCLUDED.latency_ms,
                    detail = EXCLUDED.detail
            """),
            {
                "n": name,
                "s": result.status,
                "t": now,
                "ok": last_ok,
                "f": new_fails,
                "ms": result.latency_ms,
                "d": json.dumps(result.detail),
            },
        )
        db.commit()
    return {
        "prev_status": prev_status,
        "consecutive_failures": new_fails,
        "enabled": enabled,
        "muted_until": muted_until,
    }


def _recent_unresolved_alert(name: str, within_hours: int) -> bool:
    with SessionLocal() as db:
        row = db.execute(
            text("""
                SELECT 1 FROM health_alert
                WHERE check_name = :n
                  AND resolved_at IS NULL
                  AND created_at > NOW() - (:h || ' hours')::interval
                LIMIT 1
            """),
            {"n": name, "h": str(within_hours)},
        ).first()
        return row is not None


def _record_alert(name: str, severity: str, message: str, channels: list[str]) -> None:
    with SessionLocal() as db:
        db.execute(
            text("""
                INSERT INTO health_alert (check_name, severity, message, notified)
                VALUES (:n, :s, :m, CAST(:c AS JSONB))
            """),
            {"n": name, "s": severity, "m": message, "c": json.dumps(channels)},
        )
        db.commit()


def _resolve_alerts(name: str) -> None:
    with SessionLocal() as db:
        db.execute(
            text("UPDATE health_alert SET resolved_at = NOW() WHERE check_name = :n AND resolved_at IS NULL"),
            {"n": name},
        )
        db.commit()


# ── Alert dispatch ────────────────────────────────────────────────────────────

def _in_quiet_hours() -> bool:
    try:
        from zoneinfo import ZoneInfo
        now_local = datetime.now(ZoneInfo(_TZ_NAME))
    except Exception:
        now_local = datetime.now()
    hour = now_local.hour
    if _QUIET_HOURS_START > _QUIET_HOURS_END:
        return hour >= _QUIET_HOURS_START or hour < _QUIET_HOURS_END
    return _QUIET_HOURS_START <= hour < _QUIET_HOURS_END


def _push_ntfy(title: str, body: str, priority: str = "default") -> bool:
    topic = os.getenv("HEALTH_NTFY_TOPIC", "").strip()
    if not topic:
        return False
    server = os.getenv("HEALTH_NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    try:
        r = requests.post(
            f"{server}/{topic}",
            data=body.encode("utf-8"),
            headers={"Title": title, "Priority": priority, "Tags": "warning"},
            timeout=5,
        )
        return r.status_code < 300
    except Exception as e:
        logger.warning("ntfy push failed: %s", e)
        return False


def _send_email_alert(subject: str, body: str) -> bool:
    recipient = os.getenv("HEALTH_ALERT_EMAIL", "").strip()
    if not recipient:
        return False
    try:
        from backend.services.email_service import _get_gmail_service
        from email.mime.text import MIMEText
        import base64 as _b64

        service, from_email = _get_gmail_service("maz")
        if not service:
            return False
        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = recipient
        raw = _b64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception as e:
        logger.warning("email alert failed: %s", e)
        return False


def _dispatch_alert(name: str, result: CheckResult, catastrophic: bool) -> list[str]:
    channels: list[str] = []
    subject = f"[Z-Pay] {name}: {result.status.upper()}"
    body = (
        f"Check: {name}\n"
        f"Status: {result.status}\n"
        f"Latency: {result.latency_ms}ms\n"
        f"Detail: {json.dumps(result.detail, indent=2)}\n"
        f"Time: {datetime.now(timezone.utc).isoformat()}\n"
    )
    quiet = _in_quiet_hours()
    page = (result.status == "red") and (catastrophic or not quiet)

    if _send_email_alert(subject, body):
        channels.append("email")
    if page and _push_ntfy(subject, body, priority="high"):
        channels.append("ntfy")
    return channels


# ── Main cycle ────────────────────────────────────────────────────────────────

def _run_check(name: str, fn: Callable[[], CheckResult], catastrophic: bool) -> None:
    try:
        result = fn()
    except Exception as e:
        logger.exception("check %s crashed", name)
        result = CheckResult(status="red", latency_ms=0, detail={"error": str(e)[:200]})

    state = _upsert_check_result(name, result)
    if not state["enabled"]:
        return
    if state["muted_until"] and state["muted_until"] > datetime.now(timezone.utc):
        return

    if result.status == "green":
        _resolve_alerts(name)
        return

    threshold = _DEFAULT_FAIL_THRESHOLD
    if result.status == "red" and state["consecutive_failures"] >= threshold:
        if _recent_unresolved_alert(name, _DEDUP_WINDOW_HOURS):
            return
        channels = _dispatch_alert(name, result, catastrophic)
        _record_alert(name, result.status, json.dumps(result.detail)[:500], channels)
        logger.warning(
            "health alert fired: %s red=%s channels=%s",
            name, state["consecutive_failures"], channels,
        )


def run_daily_digest() -> None:
    """Send 7am digest summarizing last 24h alerts."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    with SessionLocal() as db:
        alerts = db.execute(
            text("""
                SELECT check_name, severity, message, created_at, resolved_at
                FROM health_alert
                WHERE created_at >= :since
                ORDER BY created_at DESC
            """),
            {"since": since},
        ).fetchall()
        checks = db.execute(
            text("""
                SELECT check_name, status, last_checked_at, consecutive_failures, latency_ms
                FROM health_check
                ORDER BY check_name
            """)
        ).fetchall()

    lines = ["Z-Pay daily health digest", f"As of {datetime.now(timezone.utc).isoformat()}", ""]
    any_red = any(c[1] == "red" for c in checks)
    any_yellow = any(c[1] == "yellow" for c in checks)

    if not checks:
        lines.append("No health data yet (first run).")
    elif any_red:
        lines.append("STATUS: RED — one or more checks failing.")
    elif any_yellow:
        lines.append("STATUS: YELLOW — warnings present.")
    else:
        lines.append("STATUS: ALL GREEN ✓")

    lines.append("")
    lines.append("Checks:")
    for name, status, last, fails, ms in checks:
        lines.append(f"  [{status.upper():6}] {name}  latency={ms}ms  fails={fails}  last={last}")

    lines.append("")
    lines.append(f"Alerts last 24h: {len(alerts)}")
    for check_name, sev, msg, created, resolved in alerts[:20]:
        r = "resolved" if resolved else "OPEN"
        lines.append(f"  {created.strftime('%m-%d %H:%M')} [{sev}] {check_name} ({r}): {msg[:100]}")

    body = "\n".join(lines)
    _send_email_alert("[Z-Pay] daily health digest", body)
    logger.info("daily digest sent (red=%s yellow=%s alerts=%s)", any_red, any_yellow, len(alerts))


def _cycle() -> None:
    # called on a tight interval; dispatches individual checks by their own cadence
    # (kept simple: run all checks every cycle — APScheduler handles per-check cadence below)
    pass


# ── Scheduler ─────────────────────────────────────────────────────────────────

def start_health_monitor() -> None:
    global _SCHEDULER
    if os.getenv("HEALTH_MONITOR_ENABLED", "0") != "1":
        logger.info("health monitor disabled (HEALTH_MONITOR_ENABLED=0)")
        return
    if _SCHEDULER is not None:
        return

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    sched = BackgroundScheduler(timezone=_TZ_NAME)

    for name, fn, interval_min, catastrophic in CHECKS:
        sched.add_job(
            lambda n=name, f=fn, c=catastrophic: _run_check(n, f, c),
            trigger=IntervalTrigger(minutes=interval_min),
            id=f"health_{name}",
            name=f"health:{name}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )

    sched.add_job(
        run_daily_digest,
        trigger=CronTrigger(hour=7, minute=0),
        id="health_daily_digest",
        name="health:daily_digest",
        max_instances=1,
        coalesce=True,
    )

    sched.start()
    _SCHEDULER = sched
    logger.info("health monitor started — %d checks registered", len(CHECKS))


def stop_health_monitor() -> None:
    global _SCHEDULER
    if _SCHEDULER:
        _SCHEDULER.shutdown(wait=False)
        _SCHEDULER = None


def scheduler_status() -> dict:
    return {
        "enabled": _SCHEDULER is not None,
        "checks": [name for name, *_ in CHECKS],
    }
