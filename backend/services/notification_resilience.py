"""
Notification resilience helpers — opt-out denylist, Twilio retry,
admin-alert dedup, and per-day call/SMS counters.

Split out of notification_service.py to keep that file focused on the
Twilio + TTS integration paths.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger("zpay.notify")

_PACIFIC = ZoneInfo("America/Los_Angeles")

# ── Daily counters (reset at Pacific midnight) ───────────────────────────────
_counters_lock = threading.Lock()
_call_count_today: int = 0
_sms_count_today: int = 0
_counter_date: str = ""


def _today_pacific() -> str:
    return datetime.now(_PACIFIC).strftime("%Y-%m-%d")


def bump_counter(kind: str) -> int:
    """Increment 'call' or 'sms' counter (resets at PT midnight). Returns new value."""
    global _call_count_today, _sms_count_today, _counter_date
    today = _today_pacific()
    with _counters_lock:
        if today != _counter_date:
            _counter_date = today
            _call_count_today = 0
            _sms_count_today = 0
        if kind == "call":
            _call_count_today += 1
            return _call_count_today
        _sms_count_today += 1
        return _sms_count_today


def get_daily_counts() -> dict[str, int | str]:
    with _counters_lock:
        return {
            "date": _counter_date or _today_pacific(),
            "calls": _call_count_today,
            "sms": _sms_count_today,
        }


def reset_counters_for_test() -> None:
    """Test-only: zero out counters and date pointer."""
    global _call_count_today, _sms_count_today, _counter_date
    with _counters_lock:
        _call_count_today = 0
        _sms_count_today = 0
        _counter_date = ""


# ── Admin alert dedup ────────────────────────────────────────────────────────
_ADMIN_DEDUP_WINDOW_SEC = 60
_admin_alert_dedup: dict[str, float] = {}
_admin_dedup_lock = threading.Lock()


def admin_alert_should_send(message: str) -> bool:
    """Return True if `message` text hasn't been sent in the last 60s."""
    key = hashlib.sha256(message.encode("utf-8")).hexdigest()
    now = time.time()
    with _admin_dedup_lock:
        stale = [k for k, ts in _admin_alert_dedup.items()
                 if now - ts > _ADMIN_DEDUP_WINDOW_SEC]
        for k in stale:
            _admin_alert_dedup.pop(k, None)
        last = _admin_alert_dedup.get(key)
        if last is not None and (now - last) <= _ADMIN_DEDUP_WINDOW_SEC:
            return False
        _admin_alert_dedup[key] = now
        return True


def reset_admin_dedup_for_test() -> None:
    with _admin_dedup_lock:
        _admin_alert_dedup.clear()


# ── Opt-out denylist (persistent) ────────────────────────────────────────────
_DEFAULT_OPTOUT_PATH = "/tmp/zpay_sms_optout.json"
_optout_lock = threading.Lock()
_optout_set: set[str] = set()
_optout_loaded: bool = False


def _optout_path() -> str:
    return os.environ.get("ZPAY_OPTOUT_PATH", _DEFAULT_OPTOUT_PATH)


def _load_optout() -> None:
    global _optout_loaded
    if _optout_loaded:
        return
    with _optout_lock:
        if _optout_loaded:
            return
        path = _optout_path()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    _optout_set.update(str(p) for p in data)
                elif isinstance(data, dict) and isinstance(data.get("phones"), list):
                    _optout_set.update(str(p) for p in data["phones"])
                logger.info("[notify] loaded %d opted-out numbers from %s",
                            len(_optout_set), path)
        except Exception as e:
            logger.warning("[notify] could not load opt-out file %s: %s", path, e)
        _optout_loaded = True


def _persist_optout() -> None:
    path = _optout_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(sorted(_optout_set), fh)
    except Exception as e:
        logger.warning("[notify] could not persist opt-out file %s: %s", path, e)


def add_optout(phone: str) -> None:
    """Add a phone (E.164) to the SMS denylist. Persisted to disk."""
    _load_optout()
    with _optout_lock:
        _optout_set.add(phone)
        _persist_optout()
    logger.warning("[notify] phone %s added to SMS opt-out denylist", phone)


def is_opted_out(phone: str) -> bool:
    _load_optout()
    with _optout_lock:
        return phone in _optout_set


def reset_optout_for_test() -> None:
    global _optout_loaded
    with _optout_lock:
        _optout_set.clear()
        _optout_loaded = False


# ── Twilio retry wrapper ─────────────────────────────────────────────────────
_RATE_LIMIT_STATUSES = {429, 503}
_OPT_OUT_CODE = 21610
_RETRY_BACKOFF_SEC = (1.0, 2.0, 4.0)


def call_twilio_with_retry(fn, kind: str, target: str):
    """
    Invoke a Twilio SDK call with backoff on 429/503 and opt-out (21610) handling.

    fn      — zero-arg callable that performs the SDK call.
    kind    — 'sms' or 'call' (log context).
    target  — destination phone (log context + opt-out tracking).

    Returns the SDK response on success, None on failure / opt-out.
    """
    try:
        from twilio.base.exceptions import TwilioRestException
    except ImportError:
        return fn()

    last_err: Exception | None = None
    for attempt, backoff in enumerate([0.0, *_RETRY_BACKOFF_SEC]):
        if backoff > 0:
            time.sleep(backoff)
        try:
            return fn()
        except TwilioRestException as e:
            last_err = e
            code = getattr(e, "code", None)
            status = getattr(e, "status", None)

            if code == _OPT_OUT_CODE:
                logger.warning(
                    "[notify] %s to %s rejected — recipient opted out (21610). Adding to denylist.",
                    kind, target,
                )
                add_optout(target)
                return None

            if status in _RATE_LIMIT_STATUSES and attempt < len(_RETRY_BACKOFF_SEC):
                next_backoff = _RETRY_BACKOFF_SEC[attempt]
                logger.warning(
                    "[notify] Twilio %s rate-limited (%s) attempt %d/%d — retry in %.0fs",
                    kind, status, attempt + 1, len(_RETRY_BACKOFF_SEC), next_backoff,
                )
                continue

            logger.error("[notify] Twilio %s failed (code=%s status=%s): %s", kind, code, status, e)
            return None
        except Exception as e:
            last_err = e
            logger.error("[notify] %s to %s failed: %s", kind, target, e)
            return None

    if last_err:
        logger.error("[notify] %s to %s failed after retries: %s", kind, target, last_err)
    return None
