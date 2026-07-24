"""
Tests for backend/paychex_bot/totp.py — RFC 6238 vectors + secret normalization.

Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_paychex_totp.py -q
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.paychex_bot.totp import _normalize_secret, seconds_remaining, totp_at

# RFC 6238 Appendix B uses ASCII secret "12345678901234567890" for SHA-1.
_RFC_SECRET_B32 = base64.b32encode(b"12345678901234567890").decode()

# (unix_time, expected 6-digit code) — last 6 digits of the RFC's 8-digit vectors.
_RFC_VECTORS = [
    (59, "287082"),
    (1111111109, "081804"),
    (1111111111, "050471"),
    (1234567890, "005924"),
    (2000000000, "279037"),
    (20000000000, "353130"),
]


class TestTotp:
    def test_rfc6238_vectors(self):
        for t, expected in _RFC_VECTORS:
            assert totp_at(_RFC_SECRET_B32, t) == expected, f"t={t}"

    def test_secret_normalization_tolerates_formatting(self):
        messy = _RFC_SECRET_B32.lower().rstrip("=")
        spaced = " ".join([messy[i:i + 4] for i in range(0, len(messy), 4)])
        assert _normalize_secret(spaced) == b"12345678901234567890"
        assert totp_at(spaced, 59) == "287082"

    def test_code_is_always_six_digits(self):
        for t in (0, 1, 30, 59, 12345, 999999999):
            code = totp_at(_RFC_SECRET_B32, t)
            assert len(code) == 6 and code.isdigit()

    def test_seconds_remaining_bounds(self):
        for t in (0, 1, 29, 30, 59, 61.5):
            r = seconds_remaining(t)
            assert 1 <= r <= 30
