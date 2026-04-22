"""
Twilio notification service — SMS, phone calls, and admin alerts.

Supports MONITOR_DRY_RUN=1 for testing (logs instead of sending).

Voice calls:
  - If ELEVENLABS_API_KEY is set, uses ElevenLabs TTS served via a FastAPI
    /api/data/tts/{cache_key} endpoint (Twilio fetches the audio URL).
  - Falls back to AWS Polly via TwiML <Say> when ElevenLabs is not configured.

Hardening (2026-04-22):
  - Synchronous AMD on outbound calls (MachineDetection="Enable") so we log
    answered_by={human, machine_*, fax, unknown} per call.
  - Twilio rate-limit + suspension awareness (see notification_resilience.py).
  - Phone normalization handles US 10/11-digit, formatted, and non-US E.164
    (Eritrean +291, Ethiopian +251, etc.). Uses `phonenumbers` if installed.
  - alert_admin de-dupes identical messages within 60s.
  - Daily call/SMS counters reset at Pacific midnight; one-line summary log
    per send for trivial cost roll-ups.
"""

import base64
import hashlib
import json
import logging
import os
import re
import threading
from typing import Optional

from backend.utils.test_mode import is_test_mode, redirect_phone, test_subject
from backend.services.notification_resilience import (
    add_optout,
    admin_alert_should_send,
    bump_counter,
    call_twilio_with_retry,
    get_daily_counts,
    is_opted_out,
)

logger = logging.getLogger("zpay.notify")

_dry_run_val = os.environ.get("MONITOR_DRY_RUN", "0").lower().strip()
_dry_run = _dry_run_val in ("1", "true", "yes")
_client = None

# In-memory TTS cache: cache_key → audio bytes
_tts_cache: dict[str, bytes] = {}

# ElevenLabs: disabled for process lifetime after first 401
_elevenlabs_disabled: bool = False

# Account-status probe (run-once)
_account_probed: bool = False
_account_probe_lock = threading.Lock()

# Re-export so tests / other modules can read counters
__all__ = [
    "send_sms", "make_call", "alert_admin", "normalize_phone",
    "send_whatsapp_alert", "generate_tts_audio", "get_tts_cache_key",
    "get_cached_tts_audio", "is_opted_out", "add_optout", "get_daily_counts",
]


# ── Twilio client + suspension probe ─────────────────────────────────────────

def _get_client():
    global _client
    if _client is not None:
        return _client
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        logger.warning("Twilio credentials not configured — notifications disabled")
        return None
    from twilio.rest import Client
    _client = Client(sid, token)
    _probe_account_status_once()
    return _client


def _probe_account_status_once() -> None:
    """One-shot probe. CRITICAL log + admin SMS if account is not active."""
    global _account_probed
    if _account_probed:
        return
    with _account_probe_lock:
        if _account_probed:
            return
        _account_probed = True

    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        return

    try:
        import urllib.request
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json"
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        req = urllib.request.Request(url, headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        status = (payload.get("status") or "").lower()
        if status != "active":
            logger.critical("[notify] Twilio account status=%s (NOT active) — outbound disabled", status)
            try:
                _send_admin_sms_raw(f"CRITICAL: Twilio account status={status}. "
                                    "All Z-Pay outbound SMS/calls degraded.")
            except Exception as inner:
                logger.error("[notify] could not page admin about suspension: %s", inner)
        else:
            logger.info("[notify] Twilio account probe: status=active")
    except Exception as e:
        logger.warning("[notify] Twilio account status probe failed: %s", e)


def _send_admin_sms_raw(text: str) -> None:
    """Lightweight SMS path used during account probe (avoids re-entry into make_call)."""
    admin_phone = os.environ.get("ADMIN_PHONE", "")
    if not admin_phone or _dry_run:
        return
    from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
    if not from_number:
        return
    try:
        global _client
        if _client is None:
            from twilio.rest import Client
            _client = Client(os.environ["TWILIO_ACCOUNT_SID"],
                             os.environ["TWILIO_AUTH_TOKEN"])
        _client.messages.create(body=f"Z-PAY ALERT: {text}",
                                from_=from_number, to=admin_phone)
    except Exception:
        pass


# ── Phone normalization ───────────────────────────────────────────────────────

_phonenumbers_mod = None
_phonenumbers_attempted = False


def _try_import_phonenumbers():
    global _phonenumbers_mod, _phonenumbers_attempted
    if _phonenumbers_attempted:
        return _phonenumbers_mod
    _phonenumbers_attempted = True
    try:
        import phonenumbers as _pn  # type: ignore
        _phonenumbers_mod = _pn
    except ImportError:
        _phonenumbers_mod = None
    return _phonenumbers_mod


def normalize_phone(raw: str | None) -> str | None:
    """
    Normalize a phone number to E.164 format.

    Handles US 10/11-digit, formatted ((206) 555-1234, etc.), already-E.164,
    and international numbers (+251 Ethiopia, +291 Eritrea). Uses the
    `phonenumbers` library when installed; otherwise applies a permissive
    fallback that preserves any '+'-prefixed number with 10–15 digits.

    Returns None if the input cannot be parsed.
    """
    if raw is None:
        return None
    raw_str = str(raw).strip()
    if not raw_str:
        return None

    pn = _try_import_phonenumbers()
    if pn is not None:
        try:
            region = None if raw_str.startswith("+") else "US"
            parsed = pn.parse(raw_str, region)
            if pn.is_valid_number(parsed):
                return pn.format_number(parsed, pn.PhoneNumberFormat.E164)
        except Exception:
            pass

    digits = re.sub(r"\D", "", raw_str)
    starts_with_plus = raw_str.startswith("+")
    if not digits:
        logger.warning("Cannot normalize phone number (no digits): %r", raw)
        return None

    if starts_with_plus:
        if digits.startswith("1") and len(digits) == 11:
            return f"+{digits}"
        if 10 <= len(digits) <= 15:
            return f"+{digits}"
        logger.warning("Cannot normalize phone number (invalid + format): %r", raw)
        return None

    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"

    logger.warning("Cannot normalize phone number: %r", raw)
    return None


# ── Azure TTS (Amharic) ───────────────────────────────────────────────────────

def _azure_configured() -> bool:
    return bool(os.environ.get("AZURE_TTS_KEY")) and bool(os.environ.get("AZURE_TTS_REGION"))


def _generate_azure_tts(text: str) -> bytes | None:
    """Generate Amharic TTS via Azure Neural TTS. Returns MP3 bytes or None."""
    api_key = os.environ.get("AZURE_TTS_KEY", "")
    region = os.environ.get("AZURE_TTS_REGION", "")
    cache_key = hashlib.sha256(f"am:{text}".encode()).hexdigest()[:32]
    if cache_key in _tts_cache:
        return _tts_cache[cache_key]

    try:
        import urllib.request
        ssml = (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="am-ET">'
            '<voice name="am-ET-MekdesNeural">'
            f'{text}'
            '</voice>'
            '</speak>'
        )
        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        req = urllib.request.Request(
            url,
            data=ssml.encode("utf-8"),
            headers={
                "Ocp-Apim-Subscription-Key": api_key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            audio_bytes = resp.read()
        _tts_cache[cache_key] = audio_bytes
        logger.info("Azure TTS generated for Amharic: %d bytes", len(audio_bytes))
        return audio_bytes
    except Exception as e:
        logger.error("Azure TTS failed (Amharic): %s", e)
        return None


# ── ElevenLabs TTS ────────────────────────────────────────────────────────────

def _elevenlabs_configured() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY")) and not _elevenlabs_disabled


def _get_voice_id(language: str) -> str:
    lang = (language or "en").lower()
    if lang == "ar":
        return os.environ.get("ELEVENLABS_VOICE_ID_AR", os.environ.get("ELEVENLABS_VOICE_ID_EN", ""))
    return os.environ.get("ELEVENLABS_VOICE_ID_EN", "")


def generate_tts_audio(text: str, language: str = "en") -> bytes | None:
    """
    Generate TTS audio bytes.

    Amharic → Azure Neural TTS (am-ET-MekdesNeural)
    English / Arabic → ElevenLabs eleven_multilingual_v2 (cloned voice)

    Cached in-memory by hash of (language, text). Returns None on failure.
    """
    lang = (language or "en").lower()

    if lang == "am":
        if _azure_configured():
            return _generate_azure_tts(text)
        logger.warning("Azure TTS not configured — Amharic call will fall back to Polly")
        return None

    if not _elevenlabs_configured():
        return None

    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    voice_id = _get_voice_id(language)
    if not voice_id:
        logger.warning("ElevenLabs voice ID not configured for language: %s", language)
        return None

    cache_key = hashlib.sha256(f"{language}:{text}".encode()).hexdigest()[:32]
    if cache_key in _tts_cache:
        logger.debug("TTS cache hit for key %s", cache_key)
        return _tts_cache[cache_key]

    try:
        import urllib.request
        import urllib.error
        payload = json.dumps({
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }).encode()
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            audio_bytes = resp.read()
        _tts_cache[cache_key] = audio_bytes
        logger.info("ElevenLabs TTS generated: %d bytes (lang=%s, key=%s)",
                    len(audio_bytes), language, cache_key)
        return audio_bytes
    except urllib.error.HTTPError as e:
        if e.code == 401:
            global _elevenlabs_disabled
            _elevenlabs_disabled = True
            logger.warning(
                "ElevenLabs API key invalid (401) — disabling for this process. "
                "Calls fall back to Polly. Update ELEVENLABS_API_KEY on Railway to restore."
            )
        else:
            logger.error("ElevenLabs TTS failed (lang=%s): %s", language, e)
        return None
    except Exception as e:
        logger.error("ElevenLabs TTS failed (lang=%s): %s", language, e)
        return None


def get_tts_cache_key(text: str, language: str = "en") -> str:
    return hashlib.sha256(f"{language}:{text}".encode()).hexdigest()[:32]


def get_cached_tts_audio(cache_key: str) -> bytes | None:
    return _tts_cache.get(cache_key)


# ── SMS ───────────────────────────────────────────────────────────────────────

def send_sms(to_phone: str, message: str) -> str | None:
    """Send an SMS via Twilio. Returns SID on success, None on failure / opt-out."""
    to_phone = redirect_phone(to_phone)
    if is_test_mode():
        message = test_subject(message)

    phone = normalize_phone(to_phone)
    if not phone:
        logger.error("Invalid phone number for SMS: %s", to_phone)
        return None

    if is_opted_out(phone):
        logger.info("[notify] SMS suppressed — %s is on opt-out denylist", phone)
        return None

    if _dry_run:
        n = bump_counter("sms")
        logger.info("[notify] SMS #%d to %s: %s", n, phone, message[:80])
        logger.info("[DRY RUN] SMS to %s: %s", phone, message)
        return "dry-run-sms"

    client = _get_client()
    if not client:
        return None

    from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
    if not from_number:
        logger.error("TWILIO_FROM_NUMBER not set")
        return None

    def _do_send():
        return client.messages.create(body=message, from_=from_number, to=phone)

    msg = call_twilio_with_retry(_do_send, kind="sms", target=phone)
    if msg is None:
        return None

    sid = getattr(msg, "sid", None)
    n = bump_counter("sms")
    logger.info("[notify] SMS #%d to %s sid=%s len=%d", n, phone, sid, len(message))
    return sid


# ── Phone calls ───────────────────────────────────────────────────────────────

def make_call(to_phone: str, spoken_message: str, language: str = "en") -> str | None:
    """
    Make a phone call via Twilio.

    Uses synchronous Answering Machine Detection so we log
    answered_by={human, machine_end_beep, machine_end_silence,
    machine_end_other, fax, unknown} per call. trip_monitor can use this
    to decide retry policy (machine → retry; human → trust).

    Uses ElevenLabs TTS when configured; falls back to Polly <Say>.
    Returns the call SID on success, None on failure.
    """
    phone = normalize_phone(to_phone)
    if not phone:
        logger.error("Invalid phone number for call: %s", to_phone)
        return None

    if _dry_run:
        n = bump_counter("call")
        logger.info("[notify] CALL #%d to %s lang=%s answered_by=dry-run status=dry-run",
                    n, phone, language)
        logger.info("[DRY RUN] CALL to %s (lang=%s): %s", phone, language, spoken_message)
        return "dry-run-call"

    client = _get_client()
    if not client:
        return None

    from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
    if not from_number:
        logger.error("TWILIO_FROM_NUMBER not set")
        return None

    twiml = _build_twiml(spoken_message, language)

    # Optional async status callback. Wired only if BACKEND_PUBLIC_URL is set
    # AND a /api/twilio/voice-status route is added to the FastAPI app.
    backend_url = os.environ.get("BACKEND_PUBLIC_URL", "").rstrip("/")
    status_callback = f"{backend_url}/api/twilio/voice-status" if backend_url else None

    call_kwargs: dict = {
        "twiml": twiml,
        "from_": from_number,
        "to": phone,
        # Synchronous AMD: Twilio waits ~6s before connecting and populates
        # answered_by on the response. Acceptable for our scale (~10 calls/morning).
        "machine_detection": "Enable",
        "machine_detection_timeout": 6,
    }
    if status_callback:
        call_kwargs["status_callback"] = status_callback
        call_kwargs["status_callback_event"] = ["initiated", "ringing", "answered", "completed"]
        call_kwargs["status_callback_method"] = "POST"

    def _do_call():
        return client.calls.create(**call_kwargs)

    call = call_twilio_with_retry(_do_call, kind="call", target=phone)
    if call is None:
        return None

    sid = getattr(call, "sid", None)
    answered_by = getattr(call, "answered_by", None) or "unknown"
    duration = getattr(call, "duration", None)
    status = getattr(call, "status", None)
    n = bump_counter("call")
    logger.info(
        "[notify] CALL #%d to %s sid=%s lang=%s status=%s duration=%s answered_by=%s",
        n, phone, sid, language, status, duration, answered_by,
    )
    return sid


def _build_twiml(spoken_message: str, language: str = "en") -> str:
    """ElevenLabs <Play> when available + audio cached; else Polly <Say>."""
    if _elevenlabs_configured():
        audio_bytes = generate_tts_audio(spoken_message, language)
        if audio_bytes:
            cache_key = get_tts_cache_key(spoken_message, language)
            backend_url = os.environ.get("BACKEND_PUBLIC_URL", "").rstrip("/")
            if backend_url:
                audio_url = f"{backend_url}/api/data/tts/{cache_key}"
                return (
                    '<Response>'
                    f'<Play>{audio_url}</Play>'
                    '<Pause length="1"/>'
                    f'<Play>{audio_url}</Play>'
                    '</Response>'
                )
            logger.warning(
                "BACKEND_PUBLIC_URL not set — cannot serve ElevenLabs audio. Falling back to Polly."
            )

    lang_map = {"ar": "ar-XA", "am": "en-US"}  # Polly has no Amharic; fall back
    polly_lang = lang_map.get((language or "en").lower(), "en-US")
    return (
        '<Response>'
        f'<Say voice="Polly.Matthew" language="{polly_lang}">{spoken_message}</Say>'
        '<Pause length="1"/>'
        f'<Say voice="Polly.Matthew" language="{polly_lang}">{spoken_message}</Say>'
        '</Response>'
    )


# ── WhatsApp operator alert ───────────────────────────────────────────────────

def send_whatsapp_alert(message: str) -> str | None:
    operator_phone = os.environ.get("OPERATOR_WHATSAPP_PHONE", "")
    if not operator_phone:
        logger.debug("OPERATOR_WHATSAPP_PHONE not set — WhatsApp alert skipped")
        return None
    if _dry_run:
        logger.info("[DRY RUN] WhatsApp alert: %s", message[:120])
        return "dry-run-wa-alert"
    from backend.services.whatsapp_service import send_whatsapp
    return send_whatsapp(operator_phone, message)


# ── Admin alert ───────────────────────────────────────────────────────────────

def alert_admin(message: str, spoken_message: str | None = None) -> None:
    """
    Alert admin (Malik) via SMS + phone call.

    De-duped: identical `message` text within 60s is suppressed (one page,
    not two, when paired cycles fire in quick succession).
    """
    admin_phone = os.environ.get("ADMIN_PHONE", "")
    if not admin_phone:
        logger.error("ADMIN_PHONE not set — cannot send escalation alert")
        return

    if not admin_alert_should_send(message):
        logger.info("[notify] alert_admin suppressed (duplicate within 60s): %s", message[:80])
        return

    send_sms(admin_phone, f"Z-PAY ALERT: {message}")

    spoken = spoken_message if spoken_message else message
    make_call(admin_phone, f"Z-Pay alert. {spoken}", language="en")
