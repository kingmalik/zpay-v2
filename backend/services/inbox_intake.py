"""
backend/services/inbox_intake.py
=================================
Inbox auto-intake watcher — polls the business Gmail inbox (READ-ONLY) for
new FirstStudent ride-offer emails and auto-creates ride_intake draft rows
so the offer card + driver suggestions are waiting before anyone opens the
email.

Internal-only: this job NEVER sends email/SMS/anything to an external
party. Its only output is DB rows (ride_intake) and an ntfy push to the
owner summarizing what showed up this cycle.

Design (mirrors backend/services/paychex_keepalive.py):
- APScheduler BackgroundScheduler, IntervalTrigger every INBOX_POLL_MINUTES
  (default 10).
- Master flag INBOX_AUTOINTAKE (default "1") checked on every run — "0"
  short-circuits the job (log + return) without touching Gmail or the DB.
- Gmail auth: refresh-token → short-lived access-token dance against
  oauth2.googleapis.com/token (same shape as backend/services/drive_archive.py
  and backend/services/key_health.py), cached in a module var and renewed
  when fewer than 5 minutes remain before expiry. Every Gmail call is a GET
  to gmail.googleapis.com — this token is gmail.readonly-scoped and cannot
  send.
- Dedupe: ride_intake.source_msg_id (partial unique index, migration
  s8b_intake_source_msg) — a message already imported is never re-created.
- One bad message never kills the batch: each message is parsed/committed
  independently inside its own try/except.
- A Gmail outage (timeout, non-200, malformed JSON) is logged as a warning
  and the job returns cleanly — the next scheduled cycle retries. No
  exception escapes run_inbox_intake().

Env vars:
    INBOX_AUTOINTAKE            master on/off switch, default "1"
    INBOX_POLL_MINUTES          poll interval in minutes, default 10
    GMAIL_CLIENT_ID             OAuth2 client id (shared w/ email_service.py)
    GMAIL_CLIENT_SECRET         OAuth2 client secret
    GMAIL_REFRESH_TOKEN_BIZ_RO  gmail.readonly-scoped refresh token for the
                                business inbox (contact.activate)
    HEALTH_NTFY_TOPIC / HEALTH_NTFY_SERVER — reused from health_monitor for
                                the owner-facing push (never driver-facing)

Public API:
    start_inbox_intake() / stop_inbox_intake()  — scheduler lifecycle,
        called from app.py lifespan exactly where paychex keepalive is.
    run_inbox_intake()                          — one poll cycle; also the
        pytest entry point.
    get_inbox_status()                          — module-level state for
        GET /api/data/assignment/inbox-status.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from backend.services.ride_intake_service import build_reply_draft, parse_intake

# health_monitor's ntfy helper — imported defensively (same pattern as
# paychex_keepalive.py) so a missing/broken health_monitor never breaks the
# watcher itself.
try:
    from backend.services.health_monitor import _push_ntfy as _hm_push_ntfy
except Exception:  # pragma: no cover — health_monitor may not be wired in tests
    _hm_push_ntfy = None  # type: ignore[assignment]

logger = logging.getLogger("zpay.inbox_intake")

# ── Gmail endpoints ───────────────────────────────────────────────────────────
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
_HTTP_TIMEOUT = 15

# FirstStudent "new offer" search — last 2 days, subject shape Brandon uses.
_GMAIL_QUERY = (
    'from:firststudentinc.com newer_than:2d '
    '(subject:"New Trip" OR subject:"New Route" OR subject:"New Trips" OR subject:"New Routes")'
)

# Reply/forward prefixes — these are threads, not new offers; skip them.
_REPLY_PREFIX_RE = re.compile(r"^\s*(re|fw|fwd)\s*:", re.IGNORECASE)

# Cap on raw_text stored per row (matches the brief's 20k char ceiling).
_MAX_RAW_TEXT = 20000

# ── Module-level state ────────────────────────────────────────────────────────
_SCHEDULER = None

# Cached Gmail access token: (token, expiry_epoch_seconds). None until minted.
_token_cache: dict[str, object] = {"access_token": None, "expires_at": 0.0}

# Refresh proactively once fewer than this many seconds remain on the token.
_TOKEN_REFRESH_MARGIN_SEC = 5 * 60

# State surfaced via GET /api/data/assignment/inbox-status.
_status: dict[str, object] = {
    "enabled": None,
    "last_run_at": None,
    "last_result": {"checked": 0, "created": 0, "skipped_dupes": 0},
    "last_eft_result": None,
    "poll_minutes": None,
}


def get_inbox_status() -> dict:
    """Return a JSON-safe snapshot of the watcher's last cycle."""
    return {
        "enabled": _status["enabled"],
        "last_run_at": _status["last_run_at"],
        "last_result": dict(_status["last_result"]),  # type: ignore[arg-type]
        "last_eft_result": (
            dict(_status["last_eft_result"])  # type: ignore[arg-type]
            if _status["last_eft_result"] is not None
            else None
        ),
        "poll_minutes": _status["poll_minutes"],
    }


def _is_enabled() -> bool:
    return os.environ.get("INBOX_AUTOINTAKE", "1").strip() != "0"


def _season_pool_autofill_enabled() -> bool:
    return os.environ.get("SEASON_POOL_AUTOFILL", "1").strip() != "0"


def pool_taken_intake(db, intake) -> None:
    """Best-effort pool of a `taken` RideIntake into season_ride (S10 board,
    docs/SEASON-BOARD-PLAN.md §Wiring).

    Called from backend/routes/assignment.py's decide_intake() right after
    an intake's status flips to 'taken' — the only place that happens today.
    Guarded by SEASON_POOL_AUTOFILL (default enabled, "0" disables). Never
    raises into the caller: season_pool.upsert_from_intake's ValueError (an
    intake too incomplete to carry a route identity) and any other failure
    are logged and swallowed here so a bad pool attempt can never break the
    intake take/pass decision itself.
    """
    if not _season_pool_autofill_enabled():
        return
    try:
        from backend.services import season_pool

        # SAVEPOINT: a failed flush inside the pool upsert must not poison
        # the caller's session — its own commit still has to persist the
        # take/pass decision after we swallow the error here.
        with db.begin_nested():
            season_pool.upsert_from_intake(db, intake)
    except Exception as exc:
        logger.warning(
            "[inbox-intake] season pool autofill failed for intake %s: %s",
            getattr(intake, "intake_id", None), exc,
        )


# ── Gmail auth ─────────────────────────────────────────────────────────────────

def _mint_access_token() -> Optional[str]:
    """Return a valid Gmail access token, refreshing/caching as needed.

    Returns None (never raises) if credentials are missing or the token
    exchange fails — callers treat that as "Gmail unavailable this cycle".
    """
    now = time.time()
    cached_token = _token_cache.get("access_token")
    cached_expiry = _token_cache.get("expires_at") or 0.0
    if cached_token and (cached_expiry - now) > _TOKEN_REFRESH_MARGIN_SEC:
        return cached_token  # type: ignore[return-value]

    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN_BIZ_RO", "").strip()

    if not all([client_id, client_secret, refresh_token]):
        logger.warning(
            "[inbox-intake] missing Gmail credentials "
            "(GMAIL_CLIENT_ID/GMAIL_CLIENT_SECRET/GMAIL_REFRESH_TOKEN_BIZ_RO) — skipping cycle"
        )
        return None

    try:
        resp = requests.post(
            _TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(
                "[inbox-intake] token refresh failed — HTTP %d %s",
                resp.status_code, resp.text[:200],
            )
            return None
        payload = resp.json()
        access_token = payload.get("access_token")
        if not access_token:
            logger.warning("[inbox-intake] token refresh response missing access_token")
            return None
        expires_in = int(payload.get("expires_in", 3600))
        _token_cache["access_token"] = access_token
        _token_cache["expires_at"] = now + expires_in
        return access_token
    except Exception as exc:
        logger.warning("[inbox-intake] token refresh raised: %s", exc)
        return None


# ── Gmail HTTP calls ─────────────────────────────────────────────────────────

def _gmail_list_message_ids(access_token: str) -> list[str]:
    """messages.list — returns message ids matching _GMAIL_QUERY, or [] on any failure."""
    try:
        resp = requests.get(
            f"{_GMAIL_BASE}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"q": _GMAIL_QUERY},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(
                "[inbox-intake] messages.list failed — HTTP %d %s",
                resp.status_code, resp.text[:200],
            )
            return []
        return [m["id"] for m in resp.json().get("messages", []) if m.get("id")]
    except Exception as exc:
        logger.warning("[inbox-intake] messages.list raised: %s", exc)
        return []


def _gmail_get_attachment(access_token: str, msg_id: str, attachment_id: str) -> Optional[bytes]:
    """attachments.get — returns the raw attachment bytes, or None on any failure."""
    try:
        resp = requests.get(
            f"{_GMAIL_BASE}/messages/{msg_id}/attachments/{attachment_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(
                "[inbox-intake] attachments.get(%s/%s) failed — HTTP %d %s",
                msg_id, attachment_id, resp.status_code, resp.text[:200],
            )
            return None
        data = resp.json().get("data")
        if not data:
            return None
        return _decode_b64url_bytes(data)
    except Exception as exc:
        logger.warning(
            "[inbox-intake] attachments.get(%s/%s) raised: %s", msg_id, attachment_id, exc
        )
        return None


def _gmail_get_message(access_token: str, msg_id: str) -> Optional[dict]:
    """messages.get (format=full) — returns the raw JSON payload, or None on failure."""
    try:
        resp = requests.get(
            f"{_GMAIL_BASE}/messages/{msg_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"format": "full"},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(
                "[inbox-intake] messages.get(%s) failed — HTTP %d %s",
                msg_id, resp.status_code, resp.text[:200],
            )
            return None
        return resp.json()
    except Exception as exc:
        logger.warning("[inbox-intake] messages.get(%s) raised: %s", msg_id, exc)
        return None


# ── Message parsing ────────────────────────────────────────────────────────────

def _decode_b64url(data: str) -> str:
    """Gmail base64url bodies aren't always padded — pad before decoding."""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")


def _decode_b64url_bytes(data: str) -> bytes:
    """Same padding fix as _decode_b64url, but returns raw bytes — used for
    binary attachments (PDFs) where decoding as utf-8 text would corrupt
    the payload."""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


# PDF attachments — FirstAlt/Acumen "Trip Plan" route sheets. Distinct from
# _walk_parts_for_body: this collects (filename, attachmentId) pairs instead
# of decoding inline body data, since PDF attachments always carry a
# Gmail attachmentId requiring a separate attachments.get call.
_PDF_FILENAME_RE = re.compile(r"\.pdf$", re.IGNORECASE)


def _walk_parts_for_pdf_attachments(payload: dict) -> list[tuple[str, str]]:
    """Depth-first walk collecting every PDF attachment's (filename,
    attachmentId). Parts without an attachmentId (Gmail inlines very small
    attachments directly in body.data instead) are skipped — every real
    FirstAlt Trip Plan PDF seen is well over that inline threshold."""
    found: list[tuple[str, str]] = []

    def _visit(part: dict) -> None:
        filename = part.get("filename") or ""
        mime = part.get("mimeType", "")
        attachment_id = (part.get("body") or {}).get("attachmentId")
        if attachment_id and (mime == "application/pdf" or _PDF_FILENAME_RE.search(filename)):
            found.append((filename or "attachment.pdf", attachment_id))
        for child in part.get("parts") or []:
            _visit(child)

    _visit(payload)
    return found


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _walk_parts_for_body(payload: dict) -> tuple[Optional[str], Optional[str]]:
    """Depth-first walk of message parts. Returns (text_plain, text_html), either
    of which may be None if that mime type wasn't present anywhere."""
    plain: Optional[str] = None
    html: Optional[str] = None

    def _visit(part: dict) -> None:
        nonlocal plain, html
        if plain is not None and html is not None:
            return
        mime = part.get("mimeType", "")
        body_data = (part.get("body") or {}).get("data")
        if body_data:
            try:
                decoded = _decode_b64url(body_data)
            except Exception:
                decoded = None
            if decoded is not None:
                if mime == "text/plain" and plain is None:
                    plain = decoded
                elif mime == "text/html" and html is None:
                    html = decoded
        for child in part.get("parts") or []:
            _visit(child)

    _visit(payload)
    return plain, html


def _merge_pdf_fields_into_parsed(parsed: dict, pdf_row: dict) -> dict:
    """Fill only currently-None fields in the body-text `parsed` dict from a
    vision-extracted PDF row — never overwrites anything the body-text
    parser already confidently pulled out of Brandon's prose. Same "only
    fill NULLs, never clobber" convention as season_pool._apply_corridor_cities."""
    merged = dict(parsed)
    for key, value in pdf_row.items():
        if value is None:
            continue
        if merged.get(key) is None:
            merged[key] = value
    return merged


def _extract_subject(payload: dict) -> str:
    headers = (payload.get("headers") or [])
    for h in headers:
        if (h.get("name") or "").lower() == "subject":
            return h.get("value") or ""
    return ""


def _extract_body(message: dict) -> str:
    payload = message.get("payload") or {}
    plain, html = _walk_parts_for_body(payload)
    if plain:
        return plain
    if html:
        return _strip_html(html)
    return ""


# ── Notification ──────────────────────────────────────────────────────────────

def _push_new_offers_summary(created_parsed: list[dict]) -> None:
    if not created_parsed:
        return
    districts = []
    for parsed in created_parsed:
        d = parsed.get("district") or parsed.get("school")
        if d and d not in districts:
            districts.append(d)
    district_label = ", ".join(districts) if districts else "unknown district"
    n = len(created_parsed)
    title = "Z-Pay inbox intake"
    body = (
        f"Z-Pay: {n} new FA offer{'s' if n != 1 else ''} — {district_label} — "
        f"card ready in /dispatch/assign"
    )
    try:
        if _hm_push_ntfy is not None:
            _hm_push_ntfy(title=title, body=body, priority="default")
    except Exception as exc:
        logger.warning("[inbox-intake] ntfy push failed: %s", exc)


# ── Main job ──────────────────────────────────────────────────────────────────

def run_inbox_intake() -> dict:
    """One poll cycle. Never raises — every failure path logs and returns a
    result dict so the scheduler (and tests) always get a clean summary.
    """
    _status["poll_minutes"] = int(os.environ.get("INBOX_POLL_MINUTES", "10"))

    enabled = _is_enabled()
    _status["enabled"] = enabled
    if not enabled:
        logger.info("[inbox-intake] INBOX_AUTOINTAKE=0 — skipping cycle")
        _status["last_run_at"] = datetime.now(timezone.utc).isoformat()
        result = {"checked": 0, "created": 0, "skipped_dupes": 0}
        _status["last_result"] = result
        return result

    result = {"checked": 0, "created": 0, "skipped_dupes": 0}
    created_parsed: list[dict] = []

    try:
        access_token = _mint_access_token()
        if not access_token:
            _status["last_run_at"] = datetime.now(timezone.utc).isoformat()
            _status["last_result"] = result
            return result

        message_ids = _gmail_list_message_ids(access_token)
        result["checked"] = len(message_ids)

        if message_ids:
            # Local import avoids a hard DB dependency at module import time
            # (mirrors paychex_keepalive._load_cookies).
            from backend.db.db import SessionLocal
            from backend.db.models import RideIntake

            with SessionLocal() as db:
                existing_ids: set[str] = {
                    row[0]
                    for row in db.query(RideIntake.source_msg_id)
                    .filter(RideIntake.source_msg_id.in_(message_ids))
                    .all()
                }

                for msg_id in message_ids:
                    if msg_id in existing_ids:
                        result["skipped_dupes"] += 1
                        continue

                    try:
                        message = _gmail_get_message(access_token, msg_id)
                        if message is None:
                            continue

                        subject = _extract_subject(message.get("payload") or {})
                        if _REPLY_PREFIX_RE.match(subject or ""):
                            continue

                        body = _extract_body(message)
                        raw_text = f"Subject: {subject}\n\n{body}"[:_MAX_RAW_TEXT]

                        parsed = parse_intake(raw_text)

                        # PDF attachments (FirstAlt "Trip Plan" route sheets) carry
                        # schedule/address/day detail the body prose never has —
                        # merge whatever a vision extraction finds into any field
                        # the body-text parser left None. Optional at this layer:
                        # no ANTHROPIC_API_KEY configured means skip entirely, no
                        # Gmail attachment fetch, no crash — same contract
                        # ride_pdf_intake.parse_intake_from_pdf enforces internally.
                        try:
                            pdf_attachments = _walk_parts_for_pdf_attachments(
                                message.get("payload") or {}
                            )
                        except Exception:
                            pdf_attachments = []

                        if pdf_attachments and not os.environ.get("ANTHROPIC_API_KEY", "").strip():
                            logger.info(
                                "[inbox-intake] msg %s has %d PDF attachment(s) but "
                                "ANTHROPIC_API_KEY is not configured — skipping PDF extraction",
                                msg_id, len(pdf_attachments),
                            )
                        elif pdf_attachments:
                            from backend.services.ride_pdf_intake import parse_intake_from_pdf

                            for att_filename, attachment_id in pdf_attachments:
                                try:
                                    att_bytes = _gmail_get_attachment(access_token, msg_id, attachment_id)
                                    if not att_bytes:
                                        continue
                                    pdf_rows = parse_intake_from_pdf(att_bytes)
                                except Exception as exc:
                                    logger.warning(
                                        "[inbox-intake] PDF attachment %s on msg %s failed: %s",
                                        att_filename, msg_id, exc,
                                    )
                                    continue
                                if pdf_rows:
                                    parsed = _merge_pdf_fields_into_parsed(parsed, pdf_rows[0])
                                    if len(pdf_attachments) > 1:
                                        logger.info(
                                            "[inbox-intake] msg %s has %d PDF attachments — only "
                                            "the first extractable route (%s) was merged; the "
                                            "rest need manual review in the intake UI",
                                            msg_id, len(pdf_attachments), att_filename,
                                        )
                                    break  # first successfully-extracted PDF wins

                        reply_draft = build_reply_draft(parsed)

                        intake = RideIntake(
                            raw_text=raw_text,
                            parsed=parsed,
                            reply_draft=reply_draft,
                            status="draft",
                            source_msg_id=msg_id,
                        )
                        db.add(intake)
                        db.commit()

                        result["created"] += 1
                        created_parsed.append(parsed)
                    except Exception as exc:
                        # One bad message must never kill the batch.
                        db.rollback()
                        logger.warning(
                            "[inbox-intake] failed to process message %s: %s", msg_id, exc
                        )
                        continue

        _push_new_offers_summary(created_parsed)

        # EFT remittance ingest rides the same cycle + token (T2). Its own
        # never-raises contract, but guard anyway — a remit failure must
        # never break offer intake.
        try:
            from backend.services.remit_ingest import run_remit_ingest

            _status["last_eft_result"] = run_remit_ingest(access_token)
        except Exception as exc:
            logger.warning("[inbox-intake] remit ingest pass failed: %s", exc)

    except Exception as exc:
        # Belt-and-suspenders — no exception may escape this job.
        logger.error("[inbox-intake] cycle crashed: %s", exc)

    _status["last_run_at"] = datetime.now(timezone.utc).isoformat()
    _status["last_result"] = result
    logger.info("[inbox-intake] cycle complete: %s", result)
    return result


# ── Scheduler lifecycle ────────────────────────────────────────────────────────

def start_inbox_intake() -> None:
    """Register the poll job with APScheduler. Called from app.py lifespan
    startup. Non-fatal: any scheduler failure is caught and logged.
    """
    global _SCHEDULER
    if _SCHEDULER is not None:
        return

    interval_min = int(os.environ.get("INBOX_POLL_MINUTES", "10"))
    _status["poll_minutes"] = interval_min
    _status["enabled"] = _is_enabled()

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        sched = BackgroundScheduler(timezone="America/Los_Angeles")
        sched.add_job(
            run_inbox_intake,
            trigger=IntervalTrigger(minutes=interval_min),
            id="inbox_intake",
            name="inbox:autointake",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        sched.start()
        _SCHEDULER = sched
        logger.info("[inbox-intake] scheduler started — interval=%dmin", interval_min)
    except Exception as exc:
        logger.warning("[inbox-intake] scheduler failed to start: %s", exc)


def stop_inbox_intake() -> None:
    """Gracefully shut down the poll scheduler. Called from app.py lifespan shutdown."""
    global _SCHEDULER
    if _SCHEDULER is not None:
        try:
            _SCHEDULER.shutdown(wait=False)
            logger.info("[inbox-intake] scheduler stopped")
        except Exception as exc:
            logger.debug("[inbox-intake] scheduler stop error: %s", exc)
        finally:
            _SCHEDULER = None
