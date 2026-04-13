"""
Test mode intercept helpers.

When TEST_MODE=true in the environment, all outbound communications
(email, SMS, Adobe Sign) are redirected to safe test destinations
so the full pipeline can be exercised with real credentials without
touching real drivers or signers.

Required env vars (only needed when TEST_MODE=true):
    TEST_MODE              — set to "true" to activate
    TEST_REDIRECT_EMAIL    — all emails and Adobe Sign envelopes go here
    TEST_REDIRECT_PHONE    — all SMS/calls go here (E.164 recommended, e.g. +12065551234)
"""

import logging
import os

_logger = logging.getLogger("zpay.test_mode")


def is_test_mode() -> bool:
    """Return True when TEST_MODE env var is set to 'true' (case-insensitive)."""
    return os.environ.get("TEST_MODE", "").strip().lower() == "true"


def redirect_email(original: str) -> str:
    """
    If test mode is active, return TEST_REDIRECT_EMAIL instead of original.
    Logs the redirect so it is visible in Railway logs.
    Raises ValueError if TEST_REDIRECT_EMAIL is not set while test mode is on.
    """
    if not is_test_mode():
        return original

    dest = os.environ.get("TEST_REDIRECT_EMAIL", "").strip()
    if not dest:
        raise ValueError(
            "TEST_MODE=true but TEST_REDIRECT_EMAIL is not set. "
            "Add TEST_REDIRECT_EMAIL to your Railway env vars."
        )

    if dest != original:
        _logger.info("[TEST MODE] email redirected: %s → %s", original, dest)
    return dest


def redirect_phone(original: str) -> str:
    """
    If test mode is active, return TEST_REDIRECT_PHONE instead of original.
    Logs the redirect so it is visible in Railway logs.
    Raises ValueError if TEST_REDIRECT_PHONE is not set while test mode is on.
    """
    if not is_test_mode():
        return original

    dest = os.environ.get("TEST_REDIRECT_PHONE", "").strip()
    if not dest:
        raise ValueError(
            "TEST_MODE=true but TEST_REDIRECT_PHONE is not set. "
            "Add TEST_REDIRECT_PHONE to your Railway env vars."
        )

    if dest != original:
        _logger.info("[TEST MODE] phone redirected: %s → %s", original, dest)
    return dest


def test_subject(subject: str) -> str:
    """
    If test mode is active, prepend '[TEST] ' to the subject string.
    Safe to call unconditionally — no-ops when test mode is off.
    """
    if not is_test_mode():
        return subject
    if subject.startswith("[TEST]"):
        return subject
    return f"[TEST] {subject}"
