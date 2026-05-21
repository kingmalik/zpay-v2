"""
backend/services/paychex_keepalive.py
======================================
Paychex session keep-alive — pings each company's stored session every 20 minutes
to reset the idle timer and prevent weekly cookie expirations.

When a session IS dead (redirect to login detected), fires an email + ntfy push
to Malik telling him which company needs a cookie recapture.

Design:
- Uses the same APScheduler BackgroundScheduler pattern as the Gmail keepalive
  in app.py (IntervalTrigger every 20 minutes).
- Reads cookies from paychex_sessions DB table (persistent across Railway restarts)
  then from the in-memory _sessions dict in paychex_bot.py (fallback).
- Makes one lightweight GET to myapps.paychex.com using the stored cookies via
  httpx (sync) — no Playwright launch, no browser, ~200ms per company.
- Expiry detection: HTTP 200 but URL contains "login" → dead session;
  redirect chain ends at a login URL → dead session.
- Notifications reuse health_monitor._send_email_alert and health_monitor._push_ntfy
  so no new alert path is introduced.

Env vars (all optional — keepalive is unconditionally active when cookies exist):
    PAYCHEX_KEEPALIVE_INTERVAL_MIN   interval in minutes (default 20)
    HEALTH_ALERT_EMAIL               recipient for session-expired emails
    HEALTH_NTFY_TOPIC                ntfy topic for push notifications
    HEALTH_NTFY_SERVER               ntfy server base URL (default https://ntfy.sh)

Public API:
    start_paychex_keepalive()  — register scheduler job; called from app.py lifespan
    stop_paychex_keepalive()   — graceful shutdown
    run_paychex_keepalive()    — main job entry; iterates both companies
    check_paychex_session(company, cookies) -> bool  — returns True if session alive
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import requests

# health_monitor helpers — imported at module level (no circular import risk;
# paychex_keepalive is not imported by health_monitor).
try:
    from backend.services.health_monitor import _send_email_alert as _hm_send_email
    from backend.services.health_monitor import _push_ntfy as _hm_push_ntfy
except Exception:  # pragma: no cover — health_monitor may not be wired in tests
    _hm_send_email = None  # type: ignore[assignment]
    _hm_push_ntfy = None  # type: ignore[assignment]

logger = logging.getLogger("zpay.paychex_keepalive")

# Paychex URL to probe — lightweight authenticated page check.
# myapps.paychex.com root redirects to the dashboard if authenticated,
# or to the login page if the session is expired. One GET, no JS needed.
_PAYCHEX_PROBE_URL = "https://myapps.paychex.com"

# Login-page content indicator.
# Paychex returns HTTP 200 with a JavaScript-rendered login page on session
# expiry — the final URL stays at myapps.paychex.com, not a /login path.
# The bot (paychex_entry.py:103) detects this via `#login-username` element
# presence. We use the same signal in the raw HTML probe: if the response body
# contains `id="login-username"` the session is dead regardless of status/URL.
_LOGIN_CONTENT_INDICATOR = 'id="login-username"'

# Companies the bot supports (must match _sessions dict in paychex_bot.py)
_COMPANIES = ("acumen", "maz")

# Module-level scheduler reference (None until start_paychex_keepalive() called)
_SCHEDULER = None

# Per-company state: tracks whether an expiry alert has already been sent so we
# don't spam Malik on every cycle once a session is dead.
_alerted: dict[str, bool] = {c: False for c in _COMPANIES}


# ── Session load ──────────────────────────────────────────────────────────────

def _load_cookies(company: str) -> list[dict] | None:
    """Return stored cookies for `company` from DB first, then in-memory fallback.

    Returns None if no cookies are stored for this company.
    """
    # DB path (survives Railway restarts)
    try:
        from backend.db.db import SessionLocal
        from backend.db.models import PaychexSession

        with SessionLocal() as db:
            row = db.query(PaychexSession).filter_by(company=company).first()
            if row and row.cookies:
                return list(row.cookies)
    except Exception as exc:
        logger.warning("[paychex-keepalive] DB cookie load failed for %s: %s", company, exc)

    # In-memory fallback (paychex_bot._sessions — populated by /sync-session endpoint)
    try:
        from backend.routes.paychex_bot import _sessions as _bot_sessions

        cookies = _bot_sessions.get(company)
        if cookies:
            return list(cookies)
    except Exception as exc:
        logger.debug("[paychex-keepalive] in-memory cookie load failed for %s: %s", company, exc)

    return None


# ── Expiry detection ──────────────────────────────────────────────────────────

def check_paychex_session(company: str, cookies: list[dict]) -> bool:
    """Probe Paychex using `cookies` and return True if the session is still alive.

    A session is considered dead when:
    - The final URL after redirects contains "login" (Paychex sent us to the
      login page).
    - The HTTP response status is 401 or 403.
    - Any network / timeout error occurs (treated as unknown — returns False to
      trigger an alert so Malik can investigate).

    We do NOT treat a 5xx as expired — Paychex itself may be down. 5xx returns
    True (optimistic) so we don't spam alerts during Paychex outages.
    """
    # Convert Playwright-style cookie dicts to requests-compatible dict.
    # Playwright format: {"name": ..., "value": ..., "domain": ..., ...}
    # Use explicit `is not None` so empty-string cookie values are preserved
    # (falsy `or` would drop "" values and silently skip valid cookies).
    cookie_jar: dict[str, str] = {}
    for c in cookies:
        name = c.get("name") if c.get("name") is not None else c.get("n")
        value = c.get("value") if c.get("value") is not None else c.get("v")
        if name and value is not None:
            cookie_jar[name] = value

    if not cookie_jar:
        logger.warning("[paychex-keepalive] No usable cookies for %s — treating as expired", company)
        return False

    start = time.monotonic()
    try:
        resp = requests.get(
            _PAYCHEX_PROBE_URL,
            cookies=cookie_jar,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            allow_redirects=True,
            timeout=15,
        )
        ms = int((time.monotonic() - start) * 1000)
        final_url = resp.url

        # 401/403 → explicitly rejected
        if resp.status_code in (401, 403):
            logger.info(
                "[paychex-keepalive] %s session EXPIRED — HTTP %d (%dms)",
                company, resp.status_code, ms,
            )
            return False

        # 5xx → Paychex down, not our session; optimistic
        if resp.status_code >= 500:
            logger.warning(
                "[paychex-keepalive] Paychex returned %d for %s — treating as alive (server error)",
                resp.status_code, company,
            )
            return True

        # Redirect to login page — session expired (URL-based detection).
        if "login" in final_url.lower():
            logger.info(
                "[paychex-keepalive] %s session EXPIRED — redirected to %s (%dms)",
                company, final_url[:120], ms,
            )
            return False

        # Content-based login detection (HIGH fix).
        # Paychex returns HTTP 200 with a JavaScript redirect on session expiry —
        # the final URL stays at myapps.paychex.com and never contains "login".
        # The bot (paychex_entry.py:103) confirmed this: it uses #login-username
        # selector presence to distinguish a dead session from a live dashboard.
        # We apply the same test to the raw response body.
        if _LOGIN_CONTENT_INDICATOR in resp.text:
            logger.info(
                "[paychex-keepalive] %s session EXPIRED — login page content in 200 response "
                "(url=%s, %dms)",
                company, final_url[:120], ms,
            )
            return False

        logger.info(
            "[paychex-keepalive] %s session alive — %s %dms",
            company, final_url[:80], ms,
        )
        return True

    except requests.Timeout:
        logger.warning("[paychex-keepalive] Timeout probing Paychex for %s — treating as expired", company)
        return False
    except requests.RequestException as exc:
        logger.warning("[paychex-keepalive] Network error probing %s: %s — treating as expired", company, exc)
        return False


# ── Alert dispatch ────────────────────────────────────────────────────────────

def _send_expiry_alert(company: str) -> None:
    """Fire email + ntfy when a company's Paychex session has expired.

    Reuses health_monitor._send_email_alert and health_monitor._push_ntfy
    so the exact same channels (HEALTH_ALERT_EMAIL + HEALTH_NTFY_TOPIC) handle
    this alert — no new notification path introduced.
    """
    subject = f"[Z-Pay] Paychex session EXPIRED — {company.upper()}"
    body = (
        f"The Paychex session for {company.upper()} has expired.\n\n"
        f"Action required: recapture Paychex cookies for {company}.\n\n"
        f"Run on your local machine:\n"
        f"  python3 scripts/capture_paychex_session.py {company}\n\n"
        f"Time: {datetime.now(timezone.utc).isoformat()}"
    )

    try:
        if _hm_send_email is None or _hm_push_ntfy is None:
            raise RuntimeError("health_monitor alert helpers unavailable at import time")
        _hm_send_email(subject, body)
        _hm_push_ntfy(
            title=subject,
            body=body,
            priority="high",
        )
    except Exception as exc:
        logger.error("[paychex-keepalive] Failed to send expiry alert for %s: %s", company, exc)


# ── Main job ──────────────────────────────────────────────────────────────────

def run_paychex_keepalive() -> dict[str, str]:
    """Probe each company's Paychex session and reset the idle timer.

    Called by the APScheduler job every PAYCHEX_KEEPALIVE_INTERVAL_MIN minutes.

    Returns
    -------
    {company: "alive" | "expired" | "no_session"}  for each company
    """
    results: dict[str, str] = {}

    for company in _COMPANIES:
        cookies = _load_cookies(company)

        if not cookies:
            logger.debug("[paychex-keepalive] No stored session for %s — skipping", company)
            results[company] = "no_session"
            # Reset alert state so we notify again once cookies are re-stored
            _alerted[company] = False
            continue

        alive = check_paychex_session(company, cookies)

        if alive:
            results[company] = "alive"
            # Clear alert state so we notify again if it expires later
            _alerted[company] = False
        else:
            results[company] = "expired"
            # Only fire one alert per expiry event (not every 20 minutes)
            if not _alerted.get(company):
                logger.warning(
                    "[paychex-keepalive] %s session expired — sending alert", company
                )
                _send_expiry_alert(company)
                _alerted[company] = True
            else:
                logger.info(
                    "[paychex-keepalive] %s still expired — alert already sent, suppressing", company
                )

    logger.info("[paychex-keepalive] cycle complete: %s", results)
    return results


# ── Scheduler lifecycle ────────────────────────────────────────────────────────

def start_paychex_keepalive() -> None:
    """Register the keepalive job with APScheduler.

    Called from app.py lifespan startup — runs unconditionally (not gated on
    MONITOR_ENABLED) so the session stays warm on lean Railway deployments.
    Non-fatal: any scheduler failure is caught and logged.
    """
    global _SCHEDULER
    if _SCHEDULER is not None:
        return

    interval_min = int(os.environ.get("PAYCHEX_KEEPALIVE_INTERVAL_MIN", "20"))

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        sched = BackgroundScheduler(timezone="America/Los_Angeles")
        sched.add_job(
            run_paychex_keepalive,
            trigger=IntervalTrigger(minutes=interval_min),
            id="paychex_keepalive",
            name="paychex:keepalive",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        sched.start()
        _SCHEDULER = sched
        logger.info(
            "[paychex-keepalive] scheduler started — interval=%dmin", interval_min
        )
    except Exception as exc:
        logger.warning("[paychex-keepalive] scheduler failed to start: %s", exc)


def stop_paychex_keepalive() -> None:
    """Gracefully shut down the keepalive scheduler. Called from app.py lifespan shutdown."""
    global _SCHEDULER
    if _SCHEDULER is not None:
        try:
            _SCHEDULER.shutdown(wait=False)
            logger.info("[paychex-keepalive] scheduler stopped")
        except Exception as exc:
            logger.debug("[paychex-keepalive] scheduler stop error: %s", exc)
        finally:
            _SCHEDULER = None
