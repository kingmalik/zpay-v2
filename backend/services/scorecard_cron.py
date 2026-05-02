"""
backend/services/scorecard_cron.py
====================================
Weekly scorecard SMS + email cron — Phase 10.

Fires every Sunday at 8 PM PT (America/Los_Angeles).
Registered in trip_monitor.start_monitor() alongside the hot/cold loops.

Public API
----------
run_scorecard_cron(db_override=None)
    Main entry point. Iterates all active drivers with a phone or email,
    computes their scorecard for the just-completed week, and sends an
    SMS + HTML email. Gated by SCORECARD_CRON_ENABLED=1 env var.

send_scorecard_to_driver(person, scorecard, week_iso, db)
    Send to a single driver. Called by the main loop and the manual trigger.

opt_out_driver(person_id, db)
    Set alert_profile.unsubscribed_scorecard = True. Called by the Twilio
    STOP webhook and the email unsubscribe link handler.

build_sms_text(first_name, week_iso, tier_label, composite_score, scorecard_url)
build_email_html(first_name, week_iso, tier_label, composite_score,
                 focus_area, scorecard_url, unsubscribe_url)
    Pure builders — no side effects, fully testable.

Idempotency
-----------
_already_ran(person_id, week_iso, db) → bool
_record_cron_run(person_id, week_iso, db, *, sms_sent, email_sent, ...)

    scorecard_cron_run table has UNIQUE(week_iso, person_id). A second run
    in the same week is a no-op per driver (skip if row exists).

Env vars
--------
SCORECARD_CRON_ENABLED      "1" to enable (default "0" — safety gate)
PUBLIC_BASE_URL              Vercel frontend root (default: hardcoded Vercel URL)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

from zoneinfo import ZoneInfo

logger = logging.getLogger("zpay.scorecard_cron")

_TZ = ZoneInfo("America/Los_Angeles")

# Module-level imports — kept at module scope so tests can patch them directly.
# These are lightweight; notification_service defers Twilio client init to first call.
from backend.services.notification_service import send_sms, normalize_phone
from backend.services.driver_scorecard import compute_driver_scorecard
_DEFAULT_BASE = "https://frontend-ruddy-ten-82.vercel.app"

# ── Tier display colours (inline CSS for email clients) ──────────────────────
_TIER_COLORS: dict[str, str] = {
    "gold":      "#B8860B",
    "silver":    "#708090",
    "bronze":    "#8B4513",
    "probation": "#CC0000",
    "no_activity": "#888888",
}
_TIER_BG: dict[str, str] = {
    "gold":      "#FFF8DC",
    "silver":    "#F5F5F5",
    "bronze":    "#FDF5E6",
    "probation": "#FFF0F0",
    "no_activity": "#F9F9F9",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Pure text builders
# ═══════════════════════════════════════════════════════════════════════════════

def build_sms_text(
    first_name: str,
    week_iso: str,
    tier_label: str,
    composite_score: float,
    scorecard_url: str,
) -> str:
    """Return the scorecard SMS body (under 320 chars).

    Format: "Hi {first_name}! Your Week {N} scorecard: {url}
    Tier: {tier_label}. Score: {score}/100."
    """
    week_num = _week_number(week_iso)
    score_str = str(round(composite_score))
    return (
        f"Hi {first_name}! Your Week {week_num} Maz Services scorecard: "
        f"{scorecard_url}\n"
        f"Tier: {tier_label}. Score: {score_str}/100.\n"
        f"Reply STOP to unsubscribe."
    )


def build_email_html(
    first_name: str,
    week_iso: str,
    tier_label: str,
    composite_score: float,
    focus_area: str,
    scorecard_url: str,
    unsubscribe_url: str,
) -> str:
    """Return an HTML email body for the driver scorecard.

    Designed for Gmail/Outlook rendering — inline CSS, no external assets.
    """
    week_num = _week_number(week_iso)
    score_int = round(composite_score)
    tier_key = tier_label.lower().replace(" ", "_")
    color = _TIER_COLORS.get(tier_key, "#333333")
    bg = _TIER_BG.get(tier_key, "#FFFFFF")

    # Progress bar fill (capped at 100%)
    bar_pct = min(score_int, 100)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your Week {week_num} Scorecard</title>
</head>
<body style="margin:0;padding:0;background:#F4F4F4;font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:#F4F4F4;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:#FFFFFF;border-radius:8px;
                    overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">

        <!-- Header -->
        <tr>
          <td style="background:#1A1A2E;padding:24px 32px;text-align:center;">
            <p style="margin:0;color:#FFFFFF;font-size:13px;letter-spacing:1px;
                      text-transform:uppercase;opacity:.7;">Maz Services</p>
            <h1 style="margin:8px 0 0;color:#FFFFFF;font-size:22px;font-weight:700;">
              Week {week_num} Scorecard
            </h1>
          </td>
        </tr>

        <!-- Greeting -->
        <tr>
          <td style="padding:28px 32px 0;">
            <p style="margin:0;font-size:16px;color:#333333;">
              Hi <strong>{first_name}</strong>,
            </p>
            <p style="margin:8px 0 0;font-size:14px;color:#666666;line-height:1.6;">
              Here's your performance summary for the week ending {_week_end_label(week_iso)}.
            </p>
          </td>
        </tr>

        <!-- Score card -->
        <tr>
          <td style="padding:20px 32px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                   style="background:{bg};border:2px solid {color};border-radius:8px;">
              <tr>
                <td style="padding:20px 24px;text-align:center;">
                  <!-- Tier badge -->
                  <span style="display:inline-block;background:{color};color:#FFFFFF;
                               font-size:12px;font-weight:700;letter-spacing:1px;
                               text-transform:uppercase;padding:4px 12px;
                               border-radius:12px;">{tier_label}</span>
                  <!-- Score -->
                  <p style="margin:12px 0 4px;font-size:48px;font-weight:700;
                             color:{color};line-height:1;">{score_int}</p>
                  <p style="margin:0;font-size:13px;color:#888888;">out of 100</p>

                  <!-- Progress bar -->
                  <div style="margin:16px auto 0;width:80%;max-width:280px;
                              background:#E8E8E8;border-radius:4px;height:8px;overflow:hidden;">
                    <div style="width:{bar_pct}%;background:{color};height:8px;
                                border-radius:4px;"></div>
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Focus area -->
        <tr>
          <td style="padding:0 32px 20px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                   style="background:#F8F9FF;border-left:4px solid #4A6CF7;border-radius:4px;">
              <tr>
                <td style="padding:14px 18px;">
                  <p style="margin:0 0 4px;font-size:11px;font-weight:700;
                             color:#4A6CF7;text-transform:uppercase;letter-spacing:.8px;">
                    Focus Area
                  </p>
                  <p style="margin:0;font-size:14px;color:#333333;line-height:1.5;">
                    {focus_area}
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td style="padding:0 32px 28px;text-align:center;">
            <a href="{scorecard_url}"
               style="display:inline-block;background:#1A1A2E;color:#FFFFFF;
                      font-size:14px;font-weight:600;padding:12px 32px;
                      border-radius:6px;text-decoration:none;">
              View Full Scorecard
            </a>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#F9F9F9;padding:16px 32px;border-top:1px solid #EEEEEE;">
            <p style="margin:0;font-size:12px;color:#AAAAAA;text-align:center;line-height:1.6;">
              Maz Services &bull; Questions? Reply to this email.<br>
              <a href="{unsubscribe_url}"
                 style="color:#AAAAAA;text-decoration:underline;">Unsubscribe</a>
              from weekly scorecard emails.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# URL helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", _DEFAULT_BASE).rstrip("/")


def _mint_url(person_id: int, week_iso: str) -> str:
    """Return the public scorecard URL.

    Uses scorecard_card.build_card_link for the base path.
    In Phase 10 context the scorecard lives at /driver/{id}/scorecard.
    """
    from backend.services.scorecard_card import build_card_link
    return build_card_link(person_id)


def _unsub_url(person_id: int) -> str:
    """Return the unsubscribe link for this driver."""
    base = _base_url()
    return f"{base}/api/scorecard/unsubscribe/{person_id}"


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotency
# ═══════════════════════════════════════════════════════════════════════════════

def _already_ran(person_id: int, week_iso: str, db) -> bool:
    """Return True if a cron run row exists for (week_iso, person_id)."""
    from backend.db.models import ScorecardCronRun
    row = (
        db.query(ScorecardCronRun)
        .filter(
            ScorecardCronRun.person_id == person_id,
            ScorecardCronRun.week_iso == week_iso,
        )
        .first()
    )
    return row is not None


def _record_cron_run(
    person_id: int,
    week_iso: str,
    db,
    *,
    sms_sent: bool = False,
    email_sent: bool = False,
    sms_error: str | None = None,
    email_error: str | None = None,
) -> None:
    """Insert a scorecard_cron_run row. Silently swallows IntegrityError
    (race condition where two processes write at the same time)."""
    from backend.db.models import ScorecardCronRun
    from sqlalchemy.exc import IntegrityError

    row = ScorecardCronRun(
        person_id=person_id,
        week_iso=week_iso,
        sms_sent=sms_sent,
        email_sent=email_sent,
        sms_error=sms_error,
        email_error=email_error,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.debug(
            "[scorecard-cron] duplicate run row for person_id=%d week=%s — skipped",
            person_id, week_iso,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Opt-out
# ═══════════════════════════════════════════════════════════════════════════════

def opt_out_driver(person_id: int, db) -> None:
    """Set alert_profile.unsubscribed_scorecard = True for the driver.

    Called by:
    - POST /api/scorecard/unsubscribe/{person_id}  (email unsubscribe link)
    - Twilio STOP inbound webhook
    """
    from backend.db.models import Person

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        logger.warning("[scorecard-cron] opt_out_driver: person_id=%d not found", person_id)
        return

    profile: dict = dict(person.alert_profile or {})
    profile["unsubscribed_scorecard"] = True
    person.alert_profile = profile
    db.commit()
    logger.info("[scorecard-cron] driver person_id=%d unsubscribed from scorecard", person_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Email send (wraps email_service with no PDF attachment)
# ═══════════════════════════════════════════════════════════════════════════════

def _send_scorecard_email(
    to_email: str,
    first_name: str,
    week_iso: str,
    tier_label: str,
    composite_score: float,
    focus_area: str,
    scorecard_url: str,
    unsubscribe_url: str,
) -> None:
    """Send the scorecard HTML email via Gmail API (no PDF attachment).

    Uses the Acumen Gmail account (noreply.acumenpay@gmail.com).
    """
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from backend.services.email_service import _get_gmail_service, _html_to_plain
    from backend.utils.test_mode import redirect_email, test_subject

    to_email = redirect_email(to_email)
    gmail_service, from_email = _get_gmail_service("acumen")

    week_num = _week_number(week_iso)
    subject = test_subject(f"Your Week {week_num} Scorecard — {tier_label}")

    html_body = build_email_html(
        first_name=first_name,
        week_iso=week_iso,
        tier_label=tier_label,
        composite_score=composite_score,
        focus_area=focus_area,
        scorecard_url=scorecard_url,
        unsubscribe_url=unsubscribe_url,
    )
    plain_body = _html_to_plain(html_body)

    msg = MIMEMultipart("alternative")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    gmail_service.users().messages().send(userId="me", body={"raw": raw}).execute()


# ═══════════════════════════════════════════════════════════════════════════════
# Per-driver send
# ═══════════════════════════════════════════════════════════════════════════════

def send_scorecard_to_driver(person, scorecard, week_iso: str, db) -> dict[str, Any]:
    """Send SMS + email to one driver. Returns a result dict.

    Never raises — all failures are caught and returned in the result.
    Caller is responsible for calling _record_cron_run() with the result.

    Returns
    -------
    {
        "person_id": int,
        "sms_sent": bool,
        "email_sent": bool,
        "sms_error": str | None,
        "email_error": str | None,
    }
    """
    first_name = (person.full_name or "").split()[0] or "Driver"
    scorecard_url = _mint_url(person.person_id, week_iso)
    unsub_url = _unsub_url(person.person_id)

    result: dict[str, Any] = {
        "person_id": person.person_id,
        "sms_sent": False,
        "email_sent": False,
        "sms_error": None,
        "email_error": None,
    }

    # ── SMS ───────────────────────────────────────────────────────────────────
    phone = normalize_phone(person.phone) if person.phone else None
    if phone:
        sms_body = build_sms_text(
            first_name=first_name,
            week_iso=week_iso,
            tier_label=scorecard.tier_label,
            composite_score=scorecard.composite_score or 0,
            scorecard_url=scorecard_url,
        )
        try:
            send_sms(phone, sms_body)
            result["sms_sent"] = True
            logger.info(
                "[scorecard-cron] SMS sent to person_id=%d week=%s tier=%s",
                person.person_id, week_iso, scorecard.tier,
            )
        except Exception as exc:
            result["sms_error"] = str(exc)[:200]
            logger.error(
                "[scorecard-cron] SMS failed for person_id=%d week=%s: %s",
                person.person_id, week_iso, exc,
            )
    else:
        logger.debug("[scorecard-cron] person_id=%d has no phone — skipping SMS", person.person_id)

    # ── Email ─────────────────────────────────────────────────────────────────
    if person.email:
        try:
            _send_scorecard_email(
                to_email=person.email,
                first_name=first_name,
                week_iso=week_iso,
                tier_label=scorecard.tier_label,
                composite_score=scorecard.composite_score or 0,
                focus_area=scorecard.focus_area or "",
                scorecard_url=scorecard_url,
                unsubscribe_url=unsub_url,
            )
            result["email_sent"] = True
            logger.info(
                "[scorecard-cron] Email sent to person_id=%d week=%s",
                person.person_id, week_iso,
            )
        except Exception as exc:
            result["email_error"] = str(exc)[:200]
            logger.error(
                "[scorecard-cron] Email failed for person_id=%d week=%s: %s",
                person.person_id, week_iso, exc,
            )
    else:
        logger.debug("[scorecard-cron] person_id=%d has no email — skipping email", person.person_id)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Week helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_week_iso() -> str:
    """Return the ISO week string for the week just completed (as of Sunday PT).

    On Sunday at 8 PM PT, the week that just ended is the current ISO week
    (Monday–Sunday). We return the ISO week of the current day.
    """
    now_pt = datetime.now(_TZ)
    today = now_pt.date()
    iso = today.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _week_number(week_iso: str) -> int:
    """Extract week number from '2026-W18' → 18."""
    return int(week_iso.split("-W")[1])


def _week_end_label(week_iso: str) -> str:
    """Return human-readable week-end date e.g. 'May 3, 2026'."""
    year_s, week_s = week_iso.split("-W")
    # ISO week: week ends on Sunday (day 7)
    sunday = date.fromisocalendar(int(year_s), int(week_s), 7)
    return sunday.strftime("%b %-d, %Y")


# ═══════════════════════════════════════════════════════════════════════════════
# DB session factory (allows test injection via db_override)
# ═══════════════════════════════════════════════════════════════════════════════

def get_db_session():
    """Return a database session for use inside the background job."""
    from backend.db.db import SessionLocal
    return SessionLocal()


# ═══════════════════════════════════════════════════════════════════════════════
# Main cron entry point
# ═══════════════════════════════════════════════════════════════════════════════

def run_scorecard_cron(db_override=None) -> dict[str, int]:
    """Iterate active drivers and send weekly scorecard SMS + email.

    Gated by SCORECARD_CRON_ENABLED=1.  Safe to call manually (idempotent).

    Parameters
    ----------
    db_override:
        Inject a DB session in tests. Production always uses get_db_session().

    Returns
    -------
    {"sent": int, "skipped": int, "errors": int}
    """
    if os.environ.get("SCORECARD_CRON_ENABLED", "0") != "1":
        logger.info("[scorecard-cron] SCORECARD_CRON_ENABLED != 1 — cron disabled, skipping")
        return {"sent": 0, "skipped": 0, "errors": 0}

    logger.info("[scorecard-cron] Starting weekly scorecard send")

    from backend.db.models import Person

    week_iso = _compute_week_iso()
    # week_start is the Monday of the current ISO week
    year_s, week_s = week_iso.split("-W")
    week_start = date.fromisocalendar(int(year_s), int(week_s), 1)

    db = db_override if db_override is not None else get_db_session()
    own_db = db_override is None

    sent = 0
    skipped = 0
    errors = 0

    try:
        active_persons = (
            db.query(Person)
            .filter(Person.active.is_(True))
            .all()
        )

        logger.info(
            "[scorecard-cron] week=%s drivers=%d",
            week_iso, len(active_persons),
        )

        for person in active_persons:
            # Skip if no contact info
            has_phone = bool(person.phone and person.phone.strip())
            has_email = bool(person.email and person.email.strip())
            if not has_phone and not has_email:
                logger.debug(
                    "[scorecard-cron] Skipping person_id=%d — no phone or email",
                    person.person_id,
                )
                skipped += 1
                continue

            # Skip unsubscribed
            profile = person.alert_profile or {}
            if profile.get("unsubscribed_scorecard"):
                logger.debug(
                    "[scorecard-cron] Skipping person_id=%d — unsubscribed",
                    person.person_id,
                )
                skipped += 1
                continue

            # Idempotency check
            if _already_ran(person_id=person.person_id, week_iso=week_iso, db=db):
                logger.debug(
                    "[scorecard-cron] Skipping person_id=%d week=%s — already sent",
                    person.person_id, week_iso,
                )
                skipped += 1
                continue

            # Compute scorecard
            try:
                scorecard = compute_driver_scorecard(person.person_id, week_start, db)
            except Exception as exc:
                logger.error(
                    "[scorecard-cron] scorecard compute failed person_id=%d: %s",
                    person.person_id, exc,
                )
                errors += 1
                continue

            # Send — errors are caught inside send_scorecard_to_driver
            try:
                result = send_scorecard_to_driver(person, scorecard, week_iso, db)
            except Exception as exc:
                # Catch any unexpected crash so one driver never stops the run
                logger.error(
                    "[scorecard-cron] Unexpected error for person_id=%d: %s",
                    person.person_id, exc,
                )
                errors += 1
                continue

            # Record the run (idempotency log)
            _record_cron_run(
                person_id=person.person_id,
                week_iso=week_iso,
                db=db,
                sms_sent=result["sms_sent"],
                email_sent=result["email_sent"],
                sms_error=result["sms_error"],
                email_error=result["email_error"],
            )

            if result["sms_sent"] or result["email_sent"]:
                sent += 1
            else:
                errors += 1

    except Exception as exc:
        logger.exception("[scorecard-cron] Fatal error in cron loop: %s", exc)
    finally:
        if own_db:
            db.close()

    logger.info(
        "[scorecard-cron] Done. sent=%d skipped=%d errors=%d week=%s",
        sent, skipped, errors, week_iso,
    )
    return {"sent": sent, "skipped": skipped, "errors": errors}
