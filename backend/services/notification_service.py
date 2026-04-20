"""
Twilio notification service — SMS, phone calls, and admin alerts.

Supports MONITOR_DRY_RUN=1 for testing (logs instead of sending).

Voice calls:
  - If ELEVENLABS_API_KEY is set, uses ElevenLabs TTS served via a FastAPI
    /api/data/tts/{cache_key} endpoint (Twilio fetches the audio URL).
  - Falls back to AWS Polly via TwiML <Say> when ElevenLabs is not configured.
"""

import os
import re
import hashlib
import logging
from typing import Optional

from backend.utils.test_mode import is_test_mode, redirect_phone, test_subject

logger = logging.getLogger("zpay.notify")

_dry_run_val = os.environ.get("MONITOR_DRY_RUN", "0").lower().strip()
_dry_run = _dry_run_val in ("1", "true", "yes")
_client = None

# In-memory TTS cache: cache_key → audio bytes
_tts_cache: dict[str, bytes] = {}


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
    return _client


def normalize_phone(raw: str | None) -> str | None:
    """
    Normalize a phone number to E.164 format (+1XXXXXXXXXX).
    Returns None if the input can't be parsed.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw.strip())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if raw.strip().startswith("+") and len(digits) >= 10:
        return f"+{digits}"
    logger.warning("Cannot normalize phone number: %s", raw)
    return None


# ── Azure TTS (Amharic) ───────────────────────────────────────────────────────

def _azure_configured() -> bool:
    return bool(os.environ.get("AZURE_TTS_KEY")) and bool(os.environ.get("AZURE_TTS_REGION"))


def _generate_azure_tts(text: str) -> bytes | None:
    """
    Generate Amharic TTS using Azure Neural TTS (am-ET-MekdesNeural).
    Returns MP3 audio bytes on success, None on failure.
    """
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
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


def _get_voice_id(language: str) -> str:
    """Return the ElevenLabs voice ID for the given language."""
    lang = (language or "en").lower()
    if lang == "ar":
        return os.environ.get("ELEVENLABS_VOICE_ID_AR", os.environ.get("ELEVENLABS_VOICE_ID_EN", ""))
    return os.environ.get("ELEVENLABS_VOICE_ID_EN", "")


def generate_tts_audio(text: str, language: str = "en") -> bytes | None:
    """
    Generate TTS audio bytes.

    Amharic → Azure Neural TTS (am-ET-MekdesNeural)
    English / Arabic → ElevenLabs eleven_multilingual_v2 (cloned voice)

    Returns audio bytes (MP3) on success, None on failure.
    Results are cached in-memory by a hash of (language, text).
    """
    lang = (language or "en").lower()

    # Amharic: route to Azure
    if lang == "am":
        if _azure_configured():
            return _generate_azure_tts(text)
        logger.warning("Azure TTS not configured — Amharic call will fall back to Polly")
        return None

    # English / Arabic: ElevenLabs cloned voice
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
        import json

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
        logger.info("ElevenLabs TTS generated: %d bytes (lang=%s, key=%s)", len(audio_bytes), language, cache_key)
        return audio_bytes

    except Exception as e:
        logger.error("ElevenLabs TTS failed (lang=%s): %s", language, e)
        return None


def get_tts_cache_key(text: str, language: str = "en") -> str:
    """Return the cache key for a given text + language."""
    return hashlib.sha256(f"{language}:{text}".encode()).hexdigest()[:32]


def get_cached_tts_audio(cache_key: str) -> bytes | None:
    """Retrieve cached TTS audio bytes by cache key (for serving via HTTP endpoint)."""
    return _tts_cache.get(cache_key)


# ── SMS ───────────────────────────────────────────────────────────────────────

def send_sms(to_phone: str, message: str) -> str | None:
    """
    Send an SMS via Twilio.
    Returns the message SID on success, None on failure.
    """
    # TEST MODE: redirect to test phone and prefix message
    to_phone = redirect_phone(to_phone)
    if is_test_mode():
        message = test_subject(message)

    phone = normalize_phone(to_phone)
    if not phone:
        logger.error("Invalid phone number for SMS: %s", to_phone)
        return None

    if _dry_run:
        logger.info("[DRY RUN] SMS to %s: %s", phone, message)
        return "dry-run-sms"

    client = _get_client()
    if not client:
        return None

    from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
    if not from_number:
        logger.error("TWILIO_FROM_NUMBER not set")
        return None

    try:
        msg = client.messages.create(
            body=message,
            from_=from_number,
            to=phone,
        )
        logger.info("SMS sent to %s — SID: %s", phone, msg.sid)
        return msg.sid
    except Exception as e:
        logger.error("SMS failed to %s: %s", phone, e)
        return None


# ── Phone calls ───────────────────────────────────────────────────────────────

def make_call(to_phone: str, spoken_message: str, language: str = "en") -> str | None:
    """
    Make a phone call via Twilio with a spoken message.

    Uses ElevenLabs TTS when ELEVENLABS_API_KEY is set.
    The audio is served via the /api/data/tts/{cache_key} FastAPI endpoint
    so Twilio can fetch it. Falls back to AWS Polly <Say> if ElevenLabs is
    not configured or audio generation fails.

    Returns the call SID on success, None on failure.
    """
    phone = normalize_phone(to_phone)
    if not phone:
        logger.error("Invalid phone number for call: %s", to_phone)
        return None

    if _dry_run:
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

    try:
        call = client.calls.create(
            twiml=twiml,
            from_=from_number,
            to=phone,
        )
        logger.info("Call placed to %s (lang=%s) — SID: %s", phone, language, call.sid)
        return call.sid
    except Exception as e:
        logger.error("Call failed to %s: %s", phone, e)
        return None


def _build_twiml(spoken_message: str, language: str = "en") -> str:
    """
    Build TwiML for a call.

    If ElevenLabs is configured and audio generation succeeds, returns a
    <Play> TwiML pointing to the /api/data/tts/{cache_key} endpoint.
    Falls back to Polly <Say> otherwise.
    """
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
            else:
                logger.warning(
                    "BACKEND_PUBLIC_URL not set — cannot serve ElevenLabs audio to Twilio. "
                    "Falling back to Polly."
                )

    # Polly fallback
    lang_map = {"ar": "ar-XA", "am": "en-US"}  # Polly has no Amharic; fall back to English
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
        logger.warning("OPERATOR_WHATSAPP_PHONE not set — WhatsApp alert skipped")
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

    message         — detailed text sent via SMS
    spoken_message  — clean natural-language version read aloud on the call.
                      Falls back to message if not provided.
    """
    admin_phone = os.environ.get("ADMIN_PHONE", "")
    if not admin_phone:
        logger.error("ADMIN_PHONE not set — cannot send escalation alert")
        return

    # SMS: full detail
    send_sms(admin_phone, f"Z-PAY ALERT: {message}")

    # Call: clean spoken version (or fall back to raw message)
    spoken = spoken_message if spoken_message else message
    make_call(admin_phone, f"Z-Pay alert. {spoken}", language="en")
