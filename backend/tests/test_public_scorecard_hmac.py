"""
backend/tests/test_public_scorecard_hmac.py
============================================
Phase 9 — HMAC token tests + public scorecard endpoint tests.

Test matrix
-----------
 1. mint_token produces a two-part dot-separated token
 2. verify_token round-trips a freshly minted token correctly
 3. verify_token raises TokenInvalidError on tampered signature
 4. verify_token raises TokenInvalidError on truncated token (no dot)
 5. verify_token raises TokenExpiredError when iat is >14 days ago
 6. verify_token raises TokenInvalidError on corrupted payload bytes
 7. Tokens minted with different person_ids are different strings
 8. Tokens minted at different times are different strings (no replay)
 9. GET /api/public/scorecard/<token> returns 200 + safe fields
10. GET /api/public/scorecard/<token> returns 422 on expired token
11. GET /api/public/scorecard/<token> returns 422 on invalid token
12. GET /api/public/scorecard/<token> returns 404 when driver missing
13. Response excludes paycheck_code, person_id, internal fields
14. mint_scorecard_url returns a path with /scorecard/ prefix
15. Week label in response matches token week_iso, not always current week

Run with:
    PYTHONPATH=. pytest backend/tests/test_public_scorecard_hmac.py -x -v
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.scorecard_token import (
    TokenExpiredError,
    TokenInvalidError,
    TokenPayload,
    mint_scorecard_url,
    mint_token,
    verify_token,
)
from backend.services.driver_scorecard import (
    AXIS_LABELS,
    AXIS_WEIGHTS,
    AxisScore,
    DriverScorecard,
)
from backend.routes.public import _hmac_scorecard_response


# ── Shared fixtures ────────────────────────────────────────────────────────────

_WEEK = "2026-W18"
_PID = 42


def _make_axis(name: str, raw: float = 0.88, n: int = 5) -> AxisScore:
    w = AXIS_WEIGHTS.get(name, 0.0)
    return AxisScore(
        name=name,
        raw_value=raw,
        normalized_value=raw,
        weight=w,
        weighted_score=raw * w * 100,
        sample_size=n,
        available=name != "on_time_completion",
        low_confidence=False,
    )


def _all_axes(raw: float = 0.88) -> dict:
    return {k: _make_axis(k, raw=raw) for k in AXIS_WEIGHTS}


def _make_scorecard(
    person_id: int = _PID,
    composite: Optional[float] = 85.0,
    tier: str = "silver",
    tier_label: str = "Tier 2",
    total_trips: int = 6,
    week_iso: str = _WEEK,
) -> DriverScorecard:
    year, wnum = int(week_iso.split("-W")[0]), int(week_iso.split("-W")[1])
    week_start = date.fromisocalendar(year, wnum, 1)
    return DriverScorecard(
        person_id=person_id,
        driver_name="Ahmed Abdi",
        week_start=week_start,
        week_iso=week_iso,
        total_trips=total_trips if composite is not None else 0,
        axes=_all_axes() if composite is not None else {},
        composite_score=composite,
        tier=tier,
        tier_label=tier_label,
        low_sample=total_trips < 3,
        week_over_week_delta=None,
        headline_metric="Acceptance 88% — top 25%",
        focus_area="",
        escalation_count=0,
        self_serve_pct=100.0,
        revenue_impact=None,
        revenue_impact_per_trip=None,
        revenue_rank=None,
    )


def _mock_person(
    person_id: int = _PID,
    full_name: str = "Ahmed Abdi",
    active: bool = True,
) -> MagicMock:
    p = MagicMock()
    p.person_id = person_id
    p.full_name = full_name
    p.paycheck_code = "1099"
    p.paycheck_code_maz = "2055"
    p.active = active
    return p


def _mock_db(person: Optional[MagicMock] = None) -> MagicMock:
    db = MagicMock()
    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.first.return_value = person
    return db


# ── Token unit tests ───────────────────────────────────────────────────────────

def test_mint_token_produces_two_part_string():
    """Token must be <payload_b64>.<sig_b64> — exactly one dot."""
    token = mint_token(_PID, _WEEK)
    parts = token.split(".")
    assert len(parts) == 2, f"Expected 2 parts, got {len(parts)}: {token}"
    assert all(len(p) > 0 for p in parts)


def test_verify_token_round_trips_correctly():
    """verify_token must decode the same pid + week_iso that was signed."""
    token = mint_token(_PID, _WEEK)
    payload = verify_token(token)
    assert isinstance(payload, TokenPayload)
    assert payload.person_id == _PID
    assert payload.week_iso == _WEEK
    assert payload.issued_at > 0


def test_verify_token_raises_on_tampered_signature():
    """Flipping one character in the signature must raise TokenInvalidError."""
    token = mint_token(_PID, _WEEK)
    payload_b64, sig_b64 = token.split(".")
    # Flip last char
    tampered_sig = sig_b64[:-1] + ("A" if sig_b64[-1] != "A" else "B")
    bad_token = f"{payload_b64}.{tampered_sig}"
    with pytest.raises(TokenInvalidError):
        verify_token(bad_token)


def test_verify_token_raises_on_no_dot():
    """A token without a '.' separator must raise TokenInvalidError."""
    with pytest.raises(TokenInvalidError):
        verify_token("thisisnotavalidtoken")


def test_verify_token_raises_on_expired_token():
    """A token with iat 15 days ago must raise TokenExpiredError."""
    fifteen_days_ago = int(time.time()) - (15 * 24 * 60 * 60)
    token = mint_token(_PID, _WEEK, issued_at=fifteen_days_ago)
    with pytest.raises(TokenExpiredError):
        verify_token(token)


def test_verify_token_raises_on_corrupted_payload():
    """A token with non-JSON payload bytes must raise TokenInvalidError."""
    import base64
    garbage = base64.urlsafe_b64encode(b"notjson!!!").rstrip(b"=").decode()
    # Need a valid-looking sig to reach JSON decode (will fail there)
    fake_sig = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    with pytest.raises(TokenInvalidError):
        verify_token(f"{garbage}.{fake_sig}")


def test_different_person_ids_produce_different_tokens():
    """Different person_ids must produce different token strings."""
    now = int(time.time())
    t1 = mint_token(1, _WEEK, issued_at=now)
    t2 = mint_token(2, _WEEK, issued_at=now)
    assert t1 != t2


def test_different_issued_at_produces_different_tokens():
    """Different iat values must produce different token strings (no replay)."""
    t1 = mint_token(_PID, _WEEK, issued_at=1000000)
    t2 = mint_token(_PID, _WEEK, issued_at=1000001)
    assert t1 != t2


# ── Endpoint logic tests ───────────────────────────────────────────────────────

def test_hmac_endpoint_200_valid_token():
    """Valid token for existing driver must return 200 with required fields."""
    token = mint_token(_PID, _WEEK)
    person = _mock_person(person_id=_PID)
    db = _mock_db(person=person)
    sc = _make_scorecard(person_id=_PID, week_iso=_WEEK)

    with patch("backend.routes.public.compute_driver_scorecard", return_value=sc):
        response = _hmac_scorecard_response(token=token, db=db)

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["first_name"] == "Ahmed"
    assert body["tier"] == "silver"
    assert body["composite_score"] == 85.0
    assert "axes" in body
    assert "trend" in body
    assert "week_iso" in body


def test_hmac_endpoint_422_expired_token():
    """Expired token must return 422 with an 'expired' error message."""
    old_iat = int(time.time()) - (15 * 24 * 60 * 60)
    token = mint_token(_PID, _WEEK, issued_at=old_iat)
    db = _mock_db()

    response = _hmac_scorecard_response(token=token, db=db)

    assert response.status_code == 422
    body = json.loads(response.body)
    assert "error" in body
    assert "expired" in body["error"].lower()


def test_hmac_endpoint_422_invalid_token():
    """Malformed token must return 422 with an 'invalid' error message."""
    db = _mock_db()
    response = _hmac_scorecard_response(token="notarealtoken", db=db)
    assert response.status_code == 422
    body = json.loads(response.body)
    assert "error" in body
    assert "invalid" in body["error"].lower()


def test_hmac_endpoint_404_missing_driver():
    """Valid token but unknown person_id must return 404."""
    token = mint_token(9999, _WEEK)
    db = _mock_db(person=None)
    response = _hmac_scorecard_response(token=token, db=db)
    assert response.status_code == 404
    body = json.loads(response.body)
    assert "error" in body


def test_hmac_endpoint_excludes_internal_fields():
    """paycheck_code, person_id must not appear anywhere in the response body."""
    token = mint_token(_PID, _WEEK)
    person = _mock_person(person_id=_PID)
    db = _mock_db(person=person)
    sc = _make_scorecard(person_id=_PID, week_iso=_WEEK)

    with patch("backend.routes.public.compute_driver_scorecard", return_value=sc):
        response = _hmac_scorecard_response(token=token, db=db)

    raw_text = response.body.decode()
    assert "paycheck_code" not in raw_text
    assert "person_id" not in raw_text
    # Last name must not appear
    assert "Abdi" not in raw_text

    body = json.loads(raw_text)
    for axis_val in body["axes"].values():
        assert "weight" not in axis_val
        assert "weighted_score" not in axis_val
        assert "normalized_value" not in axis_val


def test_mint_scorecard_url_includes_scorecard_prefix():
    """mint_scorecard_url must return a path starting with /scorecard/."""
    url = mint_scorecard_url(_PID, _WEEK)
    assert url.startswith("/scorecard/")
    # Token portion must itself be a valid verifiable token
    token = url.split("/scorecard/")[1]
    payload = verify_token(token)
    assert payload.person_id == _PID


def test_hmac_endpoint_week_label_matches_token_week():
    """week_iso in response must reflect the token's week, not always 'current'."""
    token = mint_token(_PID, "2026-W10")
    person = _mock_person(person_id=_PID)
    db = _mock_db(person=person)
    sc = _make_scorecard(person_id=_PID, week_iso="2026-W10", composite=77.0)

    with patch("backend.routes.public.compute_driver_scorecard", return_value=sc):
        response = _hmac_scorecard_response(token=token, db=db)

    body = json.loads(response.body)
    assert body["week_iso"] == "2026-W10"
