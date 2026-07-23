"""
Tests for backend/services/ride_intake_service.py — best-effort email parsing.

Run with:
    PYTHONPATH=. pytest backend/tests/test_ride_intake_service.py -x -v
"""
from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.ride_intake_service import build_reply_draft, parse_intake


def test_clean_route_with_pay_and_miles():
    email = (
        "Hi team, new route for you: Risalah ES IB 05, pay $45.00, 12 miles, "
        "starts 7:45 AM, runs Monday and Wednesday."
    )
    parsed = parse_intake(email)
    assert parsed["school"] == "Risalah ES"
    assert parsed["direction"] == "IB"
    assert parsed["number"] == "05"
    assert parsed["is_odt"] is False
    assert parsed["wheelchair"] is False
    assert parsed["net_pay"] == 45.00
    assert parsed["miles"] == 12.0
    assert parsed["start_time"] == "7:45 AM"
    assert parsed["days"] == ["M", "W"]


def test_wheelchair_ride_flagged():
    email = "New wheelchair route: Cedar Heights MS OB 16 (HCV), rate $62, 9 mi."
    parsed = parse_intake(email)
    assert parsed["wheelchair"] is True
    assert parsed["net_pay"] == 62.0


def test_wheelchair_bracket_marker_flagged():
    email = "Westgate ES OB 01 [Wt] needs a driver, $44, 16mi, Fri only."
    parsed = parse_intake(email)
    assert parsed["wheelchair"] is True
    assert parsed["days"] == ["F"]


def test_missing_pay_leaves_net_pay_null():
    email = "Alderwood MS OB 09, 12 miles, starting next Monday. Pay TBD, will confirm."
    parsed = parse_intake(email)
    assert parsed["net_pay"] is None
    assert parsed["school"] == "Alderwood MS"
    assert parsed["direction"] == "OB"


def test_odt_route_detected():
    email = "ODT run: Alderwood MS OB ODT 03, $50, 14 miles."
    parsed = parse_intake(email)
    assert parsed["is_odt"] is True
    assert parsed["number"] == "03"


def test_garbage_text_never_raises():
    garbage = "asdkjfh 1234 %%%$$$ ??? \n\t\x00 lorem ipsum no structure at all"
    parsed = parse_intake(garbage)
    assert parsed["school"] is None
    assert parsed["net_pay"] is None
    assert parsed["miles"] is None
    assert parsed["wheelchair"] is False


def test_empty_string_never_raises():
    parsed = parse_intake("")
    assert parsed["school"] is None
    assert parsed["notes"] is None


def test_none_input_never_raises():
    parsed = parse_intake(None)  # type: ignore[arg-type]
    assert parsed["school"] is None


def test_pay_keyword_disambiguates_from_other_dollar_amounts():
    email = "Fuel surcharge is $5 extra but driver pay rate is $38.50 for this 10 mile run."
    parsed = parse_intake(email)
    assert parsed["net_pay"] == 38.50


# ── reply draft ──────────────────────────────────────────────────────────────

def test_reply_draft_accept_when_complete():
    parsed = {"school": "Risalah ES", "direction": "IB", "number": "05", "net_pay": 45.0, "wheelchair": False}
    draft = build_reply_draft(parsed)
    assert "can cover" in draft.lower()
    assert "Risalah ES" in draft


def test_reply_draft_asks_clarifying_questions_when_incomplete():
    parsed = {"school": None, "direction": None, "number": None, "net_pay": None, "wheelchair": False}
    draft = build_reply_draft(parsed)
    assert "?" in draft
    assert "can cover" not in draft.lower()


def test_reply_draft_pass_variant():
    parsed = {"school": "Cedar Heights MS", "direction": "OB", "number": "16", "net_pay": 62.0, "wheelchair": False}
    draft = build_reply_draft(parsed, decision_hint="pass")
    assert "not able to cover" in draft.lower()
