"""
backend/services/daily_brief.py
================================
Daily operations briefs — emailed twice per day.

  06:00 PT  → Today's Game Plan (forward-looking)
  20:00 PT  → End-of-Day Recap + Tomorrow's Game Plan

Owner decision 2026-05-28:
  - NOT a "yesterday recap" delivered the morning after. Maz operates live,
    24/7 — Malik needs a forward-leaning brief at the start of the day, and
    a recap + next-day preview at the end of the day. Not a delayed report.
  - Email is the boring/reliable starting channel. Once the format settles
    we swap to SMS or ntfy push. For v1 it's email.

Public entrypoints:
  send_morning_brief(to: str) -> dict
  send_evening_brief(to: str) -> dict
  compose_morning_brief() -> tuple[str subject, str body]
  compose_evening_brief() -> tuple[str subject, str body]

Both senders honor DAILY_BRIEF_ENABLED (default "1"). When "0", they
compose + log but do not actually send. Used to ship the cron jobs
quietly until Malik verifies the format on a manual trigger.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger("zpay.daily_brief")

# Pacific tz — operations run on PT regardless of server tz.
try:
    from zoneinfo import ZoneInfo
    _PT = ZoneInfo("America/Los_Angeles")
except Exception:
    _PT = timezone.utc

MODEL = "claude-haiku-4-5-20251001"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_pt() -> datetime:
    return datetime.now(_PT)


def _admin_email() -> str:
    """Where to send the brief. ADMIN_EMAIL env var, or empty when unset."""
    return os.environ.get("ADMIN_EMAIL", "").strip()


def _fetch_trips_for(target_date: date) -> dict[str, Any]:
    """
    Pull live trip lists from FA + ED for a target date.

    Returns:
      {
        "fa":   list[dict] | None,
        "ed":   list[dict] | None,
        "errors": dict — service-name → error string when a fetch fails,
      }

    Failures are non-fatal — the brief still goes out, just with the
    affected partner showing as "unavailable".
    """
    result: dict[str, Any] = {"fa": None, "ed": None, "errors": {}}

    try:
        from backend.services.firstalt_service import get_trips as _fa_trips
        result["fa"] = _fa_trips(target_date)
    except Exception as exc:
        logger.warning("[daily_brief] FA fetch failed for %s: %s", target_date, exc)
        result["errors"]["fa"] = str(exc)

    try:
        from backend.services.everdriven_service import get_runs as _ed_runs
        result["ed"] = _ed_runs(target_date)
    except Exception as exc:
        logger.warning("[daily_brief] ED fetch failed for %s: %s", target_date, exc)
        result["errors"]["ed"] = str(exc)

    return result


def _query_today_event_log(db: Session) -> dict[str, int]:
    """
    Count today's ops_event_log entries by severity. Used by the evening
    recap to summarize "things that happened today".
    """
    from backend.db.models import OpsEventLog

    now = _now_pt()
    start_pt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_pt.astimezone(timezone.utc)

    rows = (
        db.query(OpsEventLog)
        .filter(OpsEventLog.created_at >= start_utc)
        .all()
    )

    counts: dict[str, int] = {
        "critical": 0,
        "urgent": 0,
        "normal": 0,
        "silent": 0,
        "total": len(rows),
    }
    for r in rows:
        sev = (r.severity or "").lower()
        if sev in counts:
            counts[sev] += 1
    return counts


def _trip_count(payload: dict[str, Any], key: str) -> int | None:
    """Return len(payload[key]) when present else None."""
    val = payload.get(key)
    if val is None:
        return None
    try:
        return len(val)
    except TypeError:
        return None


def _summarize_schedule(payload: dict[str, Any]) -> str:
    """
    Build a short factual summary string from a schedule payload.
    Falls back to a clear "unavailable" line when both services error.
    """
    fa_count = _trip_count(payload, "fa")
    ed_count = _trip_count(payload, "ed")
    fa_str = f"{fa_count} FA trips" if fa_count is not None else "FA: data unavailable"
    ed_str = f"{ed_count} ED trips" if ed_count is not None else "ED: data unavailable"

    parts = [fa_str, ed_str]
    total = (fa_count or 0) + (ed_count or 0)
    if fa_count is not None and ed_count is not None:
        parts.append(f"Total scheduled: {total}")

    if payload.get("errors"):
        err_lines = [f"  - {k}: {v}" for k, v in payload["errors"].items()]
        parts.append("Fetch errors:")
        parts.extend(err_lines)

    return "\n".join(parts)


# ── Haiku-drafted summaries ───────────────────────────────────────────────────

_MORNING_SYSTEM_PROMPT = """You write a short morning ops brief for Malik, the owner of Maz Services (a small student-transport company that fulfills rides for FirstAlt and EverDriven contracts).

Tone:
- Plain, direct, present-tense. No corporate language.
- Two short paragraphs max. Optional one-line bullets only when listing routes/drivers to watch.
- Forward-looking — what to expect today. NOT a recap of yesterday.
- It is OK to say "no risk flags today" when nothing notable is queued.

Structure suggestion (adapt freely):
- One line: total rides + breakdown by partner.
- Mention peak windows (typically 7:30-8:30 AM and 2:30-3:30 PM PT) when relevant.
- Optional 1-3 bullets for routes or drivers to watch closely.
- One closing line confirming the watcher is live and will text Malik only if something breaks.

Do not invent driver names. Do not promise outcomes. Use only the facts in the input."""


_EVENING_SYSTEM_PROMPT = """You write a short end-of-day ops recap for Malik, the owner of Maz Services.

Tone:
- Plain, direct, conversational. No corporate language.
- Two short paragraphs max.
- First paragraph: today's actuals — total events, what was handled, what got escalated.
- Second paragraph: tomorrow's preview — total rides, anything worth flagging.

Do not invent driver names. Do not invent incidents. Use only the facts in the input.
It is OK to say "quiet day, nothing escalated" when that's the truth."""


def _haiku_compose(system_prompt: str, user_brief: str, fallback: str) -> str:
    """Call Haiku to draft the brief body. Returns fallback on any failure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return fallback

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=system_prompt,
            messages=[{"role": "user", "content": user_brief}],
        )
        text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        body = "\n".join(t.strip() for t in text_parts).strip()
        return body or fallback
    except Exception as exc:
        logger.warning("[daily_brief] Haiku draft failed: %s — using fallback", exc)
        return fallback


# ── Compose entrypoints ───────────────────────────────────────────────────────

def compose_morning_brief(today: date | None = None) -> tuple[str, str]:
    """Build (subject, body) for the 6 AM Game Plan email."""
    if today is None:
        today = _now_pt().date()

    schedule = _fetch_trips_for(today)
    schedule_summary = _summarize_schedule(schedule)

    weekday_long = today.strftime("%A %B %-d")
    subject = f"Z-Pay Game Plan — {weekday_long}"

    user_brief = (
        f"Date: {today.isoformat()} ({weekday_long})\n\n"
        f"Schedule snapshot:\n{schedule_summary}\n\n"
        f"Draft the morning Game Plan email body."
    )

    fallback = (
        f"Good morning.\n\n"
        f"{schedule_summary}\n\n"
        f"Watcher is live. I'll only text if something breaks."
    )

    body = _haiku_compose(_MORNING_SYSTEM_PROMPT, user_brief, fallback)
    return subject, body


def compose_evening_brief(
    db: Session,
    today: date | None = None,
) -> tuple[str, str]:
    """Build (subject, body) for the 8 PM Recap email."""
    if today is None:
        today = _now_pt().date()

    tomorrow = today + timedelta(days=1)

    counts = _query_today_event_log(db)
    tomorrow_schedule = _fetch_trips_for(tomorrow)
    tomorrow_summary = _summarize_schedule(tomorrow_schedule)

    today_summary = (
        f"Total events today: {counts['total']} "
        f"(critical: {counts['critical']}, urgent: {counts['urgent']}, "
        f"normal: {counts['normal']}, silent: {counts['silent']})"
    )

    weekday_long = today.strftime("%A %B %-d")
    tomorrow_long = tomorrow.strftime("%A %B %-d")

    subject = f"Z-Pay Recap — {weekday_long}"

    user_brief = (
        f"Today: {today.isoformat()} ({weekday_long})\n"
        f"{today_summary}\n\n"
        f"Tomorrow: {tomorrow.isoformat()} ({tomorrow_long})\n"
        f"{tomorrow_summary}\n\n"
        f"Draft the end-of-day recap + tomorrow preview email body."
    )

    fallback = (
        f"Today's recap:\n{today_summary}\n\n"
        f"Tomorrow ({tomorrow_long}):\n{tomorrow_summary}"
    )

    body = _haiku_compose(_EVENING_SYSTEM_PROMPT, user_brief, fallback)
    return subject, body


# ── Send entrypoints ──────────────────────────────────────────────────────────

def _send_or_log(
    to: str,
    subject: str,
    body: str,
    *,
    label: str,
) -> dict:
    """
    Send the email via the existing Gmail service unless DAILY_BRIEF_ENABLED=0.

    Returns a status dict the caller can use as a JSON response.
    """
    enabled = os.environ.get("DAILY_BRIEF_ENABLED", "1").strip() != "0"

    result = {
        "label": label,
        "to": to,
        "subject": subject,
        "body_preview": body[:280] + ("..." if len(body) > 280 else ""),
        "enabled": enabled,
        "sent": False,
        "error": None,
    }

    # Paper trail regardless of send outcome.
    try:
        from backend.services.ops_alert import route_dispatch_alert
        route_dispatch_alert(
            severity="silent",
            title=f"DAILY BRIEF — {label}",
            message=f"Subject: {subject}\nTo: {to}\nEnabled: {enabled}",
            sms_already_sent=True,
            source="daily_brief",
        )
    except Exception as exc:
        logger.warning("[daily_brief] paper trail write failed: %s", exc)

    if not enabled:
        logger.info("[daily_brief] %s composed but not sent (DAILY_BRIEF_ENABLED=0)", label)
        return result

    if not to:
        result["error"] = "ADMIN_EMAIL not set"
        return result

    # Mailbox fallback chain — Gmail OAuth refresh tokens expire periodically;
    # try the typically-fresher acumen mailbox first, then maz. When BOTH are
    # expired the operator needs to hit /admin/gmail-reauth manually.
    from backend.services.email_service import send_plain_email

    _mailbox_order = ("acumen", "maz")
    last_err: Exception | None = None
    for mbx in _mailbox_order:
        try:
            send_plain_email(to=to, subject=subject, body=body, company=mbx)
            result["sent"] = True
            result["mailbox_used"] = mbx
            return result
        except Exception as exc:
            last_err = exc
            logger.warning(
                "[daily_brief] %s send via %s failed: %s — trying next mailbox",
                label, mbx, exc,
            )

    result["error"] = (
        f"send failed on all mailboxes; last error: {last_err}. "
        f"Run /admin/gmail-reauth to refresh OAuth tokens."
    )
    logger.error("[daily_brief] %s final send failure: %s", label, last_err)
    return result


def send_morning_brief(to: str | None = None) -> dict:
    """Compose + send today's Game Plan email."""
    subject, body = compose_morning_brief()
    return _send_or_log(
        to or _admin_email(),
        subject,
        body,
        label="morning_game_plan",
    )


def send_evening_brief(db: Session, to: str | None = None) -> dict:
    """Compose + send today's Recap + tomorrow's preview email."""
    subject, body = compose_evening_brief(db)
    return _send_or_log(
        to or _admin_email(),
        subject,
        body,
        label="evening_recap",
    )
