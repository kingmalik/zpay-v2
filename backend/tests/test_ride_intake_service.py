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


class TestRealBrandonFormat:
    """Fixtures modeled on the real corpus (1,100 FirstStudent emails, 2026-07-23)."""

    def test_split_directional_pays_and_start_date(self):
        p = parse_intake(
            "Subject: LWSD / Edmonds - New Route\n\nHi Zubeda,\n\n"
            "I have a new route. Do you have a driver that can service this? "
            "The IB pay is $54.75 while the OB pay is $49.75 and set to start on Monday the 12th.\n\n"
            "Thanks,\n\nBRANDEN SEEBERGER\nAssistant Manager | First Alt\nCell: 925.995.4050"
        )
        assert p["net_pay_ib"] == 54.75
        assert p["net_pay_ob"] == 49.75
        assert p["net_pay"] == 54.75
        assert p["is_recurring"] is True
        assert p["start_date"] == "Monday the 12th"
        assert "IB $54.75" in p["notes"] and "OB $49.75" in p["notes"]

    def test_single_pay_city_pair_trip(self):
        p = parse_intake(
            "Subject: LWSD - New Trip\n\nHi Zubeda,\n\n"
            "I have a new trip from Kirkland to Kent. Starting on Friday the 9th. "
            "The pay is $73. Do you have a driver that can service this?\n\nThanks,"
        )
        assert p["net_pay"] == 73.0
        assert p["is_recurring"] is False
        assert p["origin"] == "Kirkland" and p["destination"] == "Kent"
        assert p["district"] == "LWSD"

    def test_requirements_and_signature_stripping(self):
        p = parse_intake(
            "Subject: Fife SD - New Trip\n\nHi Zubeda,\n\n"
            "Do you have a driver that can service this trip? The trip requires two booster "
            "seats as well, and the pay is $48.\n\nThanks,\n\n"
            "BRANDEN SEEBERGER\nCell: 925.995.4050\n"
            "This email (and any attachment) is intended solely for the addressee."
        )
        assert p["net_pay"] == 48.0
        assert p["requirements"] == ["two booster seat"]
        assert p["district"] == "Fife SD"

    def test_no_pay_in_body_stays_none(self):
        p = parse_intake(
            "Subject: LWSD - New Route and Updates\n\nHi Zubeda,\n\n"
            "Attached are the Route Sheets. Let me know if you have driver availability.\n\nThanks,"
        )
        assert p["net_pay"] is None
        assert p["district"] == "LWSD"
        assert p["is_recurring"] is True
