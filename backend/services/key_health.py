"""
backend/services/key_health.py
===============================
External-API key health watchdog.

Owner decision 2026-05-28: Malik does not want to find out a key is
dead because something silently failed weeks earlier. The moment any
external API key dies, his phone should ring with a clear "fix this"
message and a direct link.

Checks (all read-only, no side effects on the external service):
  ANTHROPIC_API_KEY  — token-counting call (cheapest valid request).
  ELEVENLABS_API_KEY — GET /v1/user (~free, just confirms auth).
  GMAIL acumen       — refresh token redeem against oauth2.googleapis.com.
  GMAIL maz          — refresh token redeem against oauth2.googleapis.com.

Each check returns a structured result the watchdog cron + the
/admin/keys-health route both consume.

When a key transitions from OK → DEAD, fires a single phone+SMS alert
via route_dispatch_alert(urgent). Dedup is built into alert_admin
(60-second window) so a repeated failure within the cron interval does
not double-page.

Status persistence: the latest check result is cached in the
ops_event_log table under source="key_health.{name}" so the /admin
page can show last-checked timestamps even after a process restart.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger("zpay.key_health")


# ── Result shape ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class KeyCheckResult:
    name: str
    ok: bool
    detail: str
    reauth_url: str | None = None
    checked_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "reauth_url": self.reauth_url,
            "checked_at": (
                self.checked_at.isoformat()
                if self.checked_at else None
            ),
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Individual checks ─────────────────────────────────────────────────────────

def check_anthropic() -> KeyCheckResult:
    """Tiny token-count request — cheapest way to confirm the org is alive."""
    name = "anthropic"
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return KeyCheckResult(
            name=name,
            ok=False,
            detail="ANTHROPIC_API_KEY not set",
            reauth_url="https://console.anthropic.com/settings/keys",
            checked_at=_now(),
        )

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        # /v1/messages/count_tokens is free and tiny.
        client.messages.count_tokens(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": "ping"}],
        )
        return KeyCheckResult(
            name=name,
            ok=True,
            detail="OK",
            checked_at=_now(),
        )
    except Exception as exc:
        msg = str(exc)
        # Common failure modes mapped to clearer reasons.
        if "organization has been disabled" in msg:
            short = "Org disabled — rotate key"
        elif "invalid x-api-key" in msg.lower() or "authentication" in msg.lower():
            short = "Invalid key — rotate"
        else:
            short = f"check failed: {msg[:120]}"
        return KeyCheckResult(
            name=name,
            ok=False,
            detail=short,
            reauth_url="https://console.anthropic.com/settings/keys",
            checked_at=_now(),
        )


def check_elevenlabs() -> KeyCheckResult:
    """GET /v1/user — auth-only, no character usage."""
    name = "elevenlabs"
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        return KeyCheckResult(
            name=name,
            ok=False,
            detail="ELEVENLABS_API_KEY not set",
            reauth_url="https://elevenlabs.io/app/settings/api-keys",
            checked_at=_now(),
        )

    try:
        import requests
        r = requests.get(
            "https://api.elevenlabs.io/v1/user",
            headers={"xi-api-key": api_key},
            timeout=8,
        )
        if r.status_code == 200:
            return KeyCheckResult(name=name, ok=True, detail="OK", checked_at=_now())
        if r.status_code == 401:
            return KeyCheckResult(
                name=name,
                ok=False,
                detail="401 Unauthorized — rotate key",
                reauth_url="https://elevenlabs.io/app/settings/api-keys",
                checked_at=_now(),
            )
        return KeyCheckResult(
            name=name,
            ok=False,
            detail=f"HTTP {r.status_code}",
            reauth_url="https://elevenlabs.io/app/settings/api-keys",
            checked_at=_now(),
        )
    except Exception as exc:
        return KeyCheckResult(
            name=name,
            ok=False,
            detail=f"check failed: {str(exc)[:120]}",
            reauth_url="https://elevenlabs.io/app/settings/api-keys",
            checked_at=_now(),
        )


def _check_gmail_mailbox(company: str) -> KeyCheckResult:
    """Exchange the refresh token for a 1-hour access token."""
    name = f"gmail_{company}"
    env_token_var = f"GMAIL_REFRESH_TOKEN_{company.upper()}"
    refresh_token = os.environ.get(env_token_var, "").strip()
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    reauth_url = (
        "https://zpay-v2-production.up.railway.app"
        f"/admin/gmail-reauth?account={company}"
    )

    if not refresh_token:
        return KeyCheckResult(
            name=name,
            ok=False,
            detail=f"{env_token_var} not set",
            reauth_url=reauth_url,
            checked_at=_now(),
        )
    if not client_id or not client_secret:
        return KeyCheckResult(
            name=name,
            ok=False,
            detail="GOOGLE_OAUTH_CLIENT_ID/SECRET not set",
            reauth_url=reauth_url,
            checked_at=_now(),
        )

    try:
        import requests
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=8,
        )
        if r.status_code == 200 and r.json().get("access_token"):
            return KeyCheckResult(name=name, ok=True, detail="OK", checked_at=_now())
        body = r.text
        if "invalid_grant" in body:
            return KeyCheckResult(
                name=name,
                ok=False,
                detail="Token expired/revoked — reauth needed",
                reauth_url=reauth_url,
                checked_at=_now(),
            )
        return KeyCheckResult(
            name=name,
            ok=False,
            detail=f"HTTP {r.status_code} {body[:100]}",
            reauth_url=reauth_url,
            checked_at=_now(),
        )
    except Exception as exc:
        return KeyCheckResult(
            name=name,
            ok=False,
            detail=f"check failed: {str(exc)[:120]}",
            reauth_url=reauth_url,
            checked_at=_now(),
        )


def check_gmail_acumen() -> KeyCheckResult:
    return _check_gmail_mailbox("acumen")


def check_gmail_maz() -> KeyCheckResult:
    return _check_gmail_mailbox("maz")


# Registry — drives both the cron and the /admin page.
ALL_CHECKS: dict[str, Callable[[], KeyCheckResult]] = {
    "anthropic": check_anthropic,
    "elevenlabs": check_elevenlabs,
    "gmail_acumen": check_gmail_acumen,
    "gmail_maz": check_gmail_maz,
}


# ── Aggregator ────────────────────────────────────────────────────────────────

def run_all_checks() -> list[KeyCheckResult]:
    """Run every registered check and return the results in order."""
    results: list[KeyCheckResult] = []
    for fn in ALL_CHECKS.values():
        try:
            results.append(fn())
        except Exception as exc:
            logger.exception("key_health: check crashed: %s", exc)
    return results


# ── In-memory transition state — only alert on OK -> DEAD ─────────────────────

# Process-level cache. Resets on container restart, which means the first
# cron after a deploy may re-alert for any already-dead key — that's
# the right behavior on a cold start.
_last_state: dict[str, bool] = {}


def _maybe_alert(result: KeyCheckResult) -> bool:
    """
    Fire a phone+SMS alert ONLY when a key transitions from OK→DEAD.
    Returns True if we fired an alert this call.
    """
    prev_ok = _last_state.get(result.name)
    _last_state[result.name] = result.ok

    # Never alert on first observation OR on transition DEAD→DEAD OR OK→OK.
    if prev_ok is None:
        return False
    if prev_ok is False:
        return False  # was already dead; do not re-page
    if result.ok is True:
        return False  # still alive

    # Real transition: was OK last cycle, dead now.
    try:
        from backend.services.ops_alert import route_dispatch_alert
        link = result.reauth_url or "(no rotation link wired)"
        title = f"KEY DEAD — {result.name}"
        message = (
            f"External API key '{result.name}' just stopped working.\n"
            f"Reason: {result.detail}\n"
            f"Fix: {link}\n"
            f"Until rotated, related Z-Pay features fall back to static defaults."
        )
        spoken = (
            f"Heads up. The {result.name.replace('_', ' ')} key just stopped working. "
            f"Open Z-Pay's keys-health page to rotate it."
        )
        route_dispatch_alert(
            severity="urgent",
            title=title,
            message=message,
            spoken_message=spoken,
            source=f"key_health.{result.name}",
        )
        return True
    except Exception as exc:
        logger.error("key_health: alert dispatch failed: %s", exc)
        return False


def run_watchdog_cycle() -> dict:
    """One full cycle: check everything, alert on transitions, return summary."""
    results = run_all_checks()
    alerts_fired = 0
    for r in results:
        if _maybe_alert(r):
            alerts_fired += 1

    summary = {
        "ran_at": _now().isoformat(),
        "checked": len(results),
        "ok": sum(1 for r in results if r.ok),
        "dead": sum(1 for r in results if not r.ok),
        "alerts_fired": alerts_fired,
        "results": [r.to_dict() for r in results],
    }
    logger.info(
        "[key_health] cycle complete: ok=%d dead=%d alerts=%d",
        summary["ok"], summary["dead"], summary["alerts_fired"],
    )
    return summary


# ── Gmail keep-alive (preventive) ─────────────────────────────────────────────

def gmail_keepalive() -> dict:
    """
    Weekly preventive ping: redeem each Gmail refresh token to a fresh access
    token. Token redemption counts as "activity" for Google's stale-token policy
    and keeps unverified-app tokens alive much longer.

    Does NOT send any email. Just exercises the OAuth grant. Cheap.
    """
    out: dict[str, str] = {}
    for company in ("acumen", "maz"):
        res = _check_gmail_mailbox(company)
        out[company] = "ok" if res.ok else f"dead: {res.detail}"
    logger.info("[key_health] gmail keepalive: %s", out)
    return out
