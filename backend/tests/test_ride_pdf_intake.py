"""
Tests for backend/services/ride_pdf_intake.py — FirstAlt/Acumen "Trip Plan"
PDF vision extraction.

Pure-function module (no DB), so these are plain unit tests — no SQLite
fixture needed, matching test_ride_intake_service.py's style.

The `_call_vision_extraction`/Anthropic layer is mocked with JSON hand-
transcribed field-for-field from the real rendered PDFs pulled 2026-08-19
from contact.acumenintl@gmail.com (Bell_ES_OB_01.pdf / Bell_ES_OB_01_W.pdf —
see scratchpad ride-pdfs/ for the originals), NOT synthetic data — this is
the ground truth a correct vision call should return for those two cards.
A live call against the real Anthropic API could not be exercised while
building this: the configured ANTHROPIC_API_KEY's org returned
"This organization has been disabled" (account-level, unrelated to this
module). test_live_vision_extraction_against_real_pdf below re-runs the
same PDFs through the real API and is skipped unless explicitly opted in.

Run with:
    PYTHONPATH=. pytest backend/tests/test_ride_pdf_intake.py -x -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.ride_pdf_intake import (
    _extract_wheelchair,
    _map_card_to_intake,
    _norm_days,
    _norm_direction,
    _render_pages_to_png,
    parse_intake_from_pdf,
)
from backend.services.route_identity import parse_route_identity

# ── Ground-truth card JSON, transcribed field-for-field from the real ────────
# rendered PDFs (Bell_ES_OB_01.pdf = MTHF, Bell_ES_OB_01_W.pdf = Wednesday-
# only variant of the exact same student/route). `stops` replaced the old
# singular pickup_time/pickup_location/dropoff_time/dropoff_location keys
# 2026-08-19 so multi-stop routes (Columbia JHS below) can't silently lose
# a stop.
_BELL_MTHF_CARD = {
    "trip_plan_title": "Bell ES OB 01 - Trip Plan 1",
    "direction": "OB",
    "route_number": "01",
    "is_odt": False,
    "applicable_days": ["M", "T", "H", "F"],
    "start_date": "08/31/2026",
    "end_date": "06/16/2027",
    "stops": [
        {"type": "pickup", "time": "03:15 PM",
         "location": "Bell, 11212 Northeast 112th Street, Kirkland, Washington, 98033",
         "student": "Aura Gould"},
        {"type": "dropoff", "time": "04:05 PM",
         "location": "12404 Southeast 217th Court, Kent, Washington, 98031",
         "student": "Aura Gould"},
    ],
    "mileage": 24,
    "driver_assigned": "Unassigned",
    "wheelchair_equipment_needed": False,
    "students": [{"name": "Aura Gould", "equipment": None, "notes": None}],
}

_BELL_WEDNESDAY_CARD = {
    **_BELL_MTHF_CARD,
    "trip_plan_title": "Bell ES OB 01 (W) - Trip Plan 1",
    "applicable_days": ["W"],
    "stops": [
        {"type": "pickup", "time": "01:45 PM",
         "location": "Bell, 11212 Northeast 112th Street, Kirkland, Washington, 98033",
         "student": "Aura Gould"},
        {"type": "dropoff", "time": "02:25 PM",
         "location": "12404 Southeast 217th Court, Kent, Washington, 98031",
         "student": "Aura Gould"},
    ],
}

# Real 3-stop card (Columbia_JHS_Surprise_Lake_MS_OB_01.pdf): two pickups at
# two different schools, one shared dropoff. The old pickup+dropoff-pair
# shape would have silently dropped stop 2 (Surprise Lake MS pickup).
_COLUMBIA_3STOP_CARD = {
    "trip_plan_title": "Columbia JHS - Surprise Lake MS OB 01",
    "direction": "OB",
    "route_number": "01",
    "is_odt": False,
    "applicable_days": ["M", "T", "W", "H", "F"],
    "start_date": "05/18/2026",
    "end_date": None,
    "stops": [
        {"type": "pickup", "time": "02:20 PM",
         "location": "Columbia JHS, 2901 54th Avenue East, Fife, Washington, 98424",
         "student": "Amari Heleta"},
        {"type": "pickup", "time": "02:45 PM",
         "location": "Surprise Lake MS, 2001 Milton Way, Milton, Washington, 98354",
         "student": "Aliyah'Marie Heleta"},
        {"type": "dropoff", "time": "03:05 PM",
         "location": "626 South 312th Street, Unit A, Federal Way, Washington, 98003",
         "student": "Aliyah'Marie Heleta, Amari Heleta"},
    ],
    "mileage": 13,
    "driver_assigned": "Unassigned",
    "wheelchair_equipment_needed": False,
    "students": [
        {"name": "Aliyah'Marie Heleta", "equipment": None, "notes": None},
        {"name": "Amari Heleta", "equipment": None, "notes": None},
    ],
}


def test_map_card_bell_mthf_variant():
    parsed = _map_card_to_intake(_BELL_MTHF_CARD)
    assert parsed["school"] == "Bell ES"
    assert parsed["direction"] == "OB"
    assert parsed["number"] == "01"
    assert parsed["is_odt"] is False
    assert parsed["wheelchair"] is False
    assert parsed["miles"] == 24.0
    assert parsed["net_pay"] is None  # Trip Plan cards never show a dollar figure
    assert parsed["days"] == ["M", "T", "Th", "F"]  # "H" badge -> "Th" convention
    assert parsed["start_time"] == "03:15 PM"
    assert parsed["start_date"] == "08/31/2026"
    assert parsed["is_recurring"] is True  # distinct start/end -> standing route
    assert "Aura Gould" in parsed["notes"]
    assert "03:15 PM" in parsed["notes"]
    assert parsed["needs_info"] is False  # clean 2-stop card, nothing truncated
    assert "MULTI-STOP" not in parsed["notes"]


def test_map_card_bell_wednesday_variant_differs_only_in_schedule():
    """The acceptance check the coordinator asked to eyeball: MTHF vs the
    (W) Wednesday-only variant of the SAME route/student must come out with
    the same identity but different days/times."""
    mthf = _map_card_to_intake(_BELL_MTHF_CARD)
    wed = _map_card_to_intake(_BELL_WEDNESDAY_CARD)

    assert mthf["school"] == wed["school"] == "Bell ES"
    assert mthf["direction"] == wed["direction"] == "OB"
    assert mthf["number"] == wed["number"] == "01"

    assert mthf["days"] == ["M", "T", "Th", "F"]
    assert wed["days"] == ["W"]
    assert mthf["start_time"] == "03:15 PM"
    assert wed["start_time"] == "01:45 PM"


def test_map_card_columbia_jhs_3stop_route_keeps_all_stops_and_flags_needs_info():
    """Ground-truth acceptance check for the 3-stop card: the middle stop
    (Surprise Lake MS pickup) must survive somewhere, never silently drop —
    2 stops go into the normal intake fields exactly as a 2-stop card would,
    the 3rd goes into notes as an explicit unmapped-stop line, and the row
    is flagged needs_info so the board surfaces it for a human look instead
    of trusting a quietly-truncated route."""
    parsed = _map_card_to_intake(_COLUMBIA_3STOP_CARD)
    assert parsed is not None

    # Stop 1 (first pickup) and stop 3 (final dropoff) map to the normal
    # fields, exactly like a clean 2-stop card.
    assert parsed["school"] == "Columbia JHS - Surprise Lake MS"
    assert parsed["direction"] == "OB"
    assert parsed["number"] == "01"
    assert parsed["start_time"] == "02:20 PM"
    assert parsed["origin"] == "Columbia JHS, 2901 54th Avenue East, Fife, Washington, 98424"
    assert parsed["destination"] == "626 South 312th Street, Unit A, Federal Way, Washington, 98003"

    # Stop 2 (the middle pickup) is NOT silently dropped -- it's in notes.
    assert parsed["needs_info"] is True
    assert "MULTI-STOP ROUTE" in parsed["notes"]
    assert "3 stops total" in parsed["notes"]
    assert "Surprise Lake MS" in parsed["notes"]
    assert "02:45 PM" in parsed["notes"]
    assert "Aliyah'Marie Heleta" in parsed["notes"]


def test_map_card_missing_identity_returns_none():
    card = {"trip_plan_title": None, "direction": None, "route_number": None}
    assert _map_card_to_intake(card) is None


def test_map_card_returns_none_when_title_unparseable():
    """The trip-plan title is the ONLY source of `school` (route_identity.
    parse_route_identity is the sole school parser here) -- when the model
    can't read the title, there's no school signal at all, and
    season_pool.upsert_from_intake requires school+number+direction to pool
    a route. Correctly returning None here (not a half-built row) mirrors
    that same required-fields contract one layer earlier."""
    card = {
        "trip_plan_title": "garbled ocr text",
        "direction": "IB",
        "route_number": "07",
        "is_odt": False,
    }
    assert _map_card_to_intake(card) is None


def test_map_card_wheelchair_from_route_identity_marker():
    card = {
        "trip_plan_title": "Cedar Heights MS OB 16 (HCV) - Trip Plan 1",
        "direction": "OB",
        "route_number": "16",
    }
    parsed = _map_card_to_intake(card)
    assert parsed["wheelchair"] is True


def test_map_card_wheelchair_from_student_equipment():
    card = {
        **_BELL_MTHF_CARD,
        "students": [{"name": "Aura Gould", "equipment": "wheelchair", "notes": None}],
    }
    parsed = _map_card_to_intake(card)
    assert parsed["wheelchair"] is True
    assert parsed["requirements"] == ["wheelchair"]


def test_norm_days_handles_h_and_th_thursday_spellings():
    assert _norm_days(["M", "T", "H", "F"]) == ["M", "T", "Th", "F"]
    assert _norm_days(["M", "T", "TH", "F"]) == ["M", "T", "Th", "F"]
    assert _norm_days("W") == ["W"]
    assert _norm_days(None) is None
    assert _norm_days([]) is None


def test_norm_direction_variants():
    assert _norm_direction("IB") == "IB"
    assert _norm_direction("outbound") == "OB"
    assert _norm_direction("sideways") is None
    assert _norm_direction(None) is None


def test_extract_wheelchair_false_when_no_signal():
    card = {"wheelchair_equipment_needed": False, "students": [{"equipment": None}]}
    assert _extract_wheelchair(card, identity=None) is False


# ── PDF rendering ─────────────────────────────────────────────────────────────

def test_render_pages_to_png_returns_empty_on_garbage_bytes():
    assert _render_pages_to_png(b"not a real pdf") == []


def test_render_pages_to_png_returns_empty_on_empty_bytes():
    assert _render_pages_to_png(b"") == []


def test_render_pages_to_png_real_sample_pdf_produces_one_png():
    """Renders a real downloaded sample -- proves the PyMuPDF path works end
    to end without hitting the network. Skipped if the fixture isn't on disk
    (scratchpad path, not committed to the repo)."""
    sample = (
        "/private/tmp/claude-501/-Users-malikmilion/"
        "f96fe70c-70a0-4b30-a309-9b6354f4b086/scratchpad/ride-pdfs/Bell_ES_OB_01.pdf"
    )
    if not os.path.exists(sample):
        pytest.skip("scratchpad sample PDF not present on this machine")
    pages = _render_pages_to_png(open(sample, "rb").read())
    assert len(pages) == 1
    assert pages[0][:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes


# ── End-to-end with a mocked vision call ──────────────────────────────────────

def test_parse_intake_from_pdf_returns_empty_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("backend.services.ride_pdf_intake._render_pages_to_png", return_value=[b"fake-png-bytes"]):
        assert parse_intake_from_pdf(b"%PDF-1.4 fake") == []


def test_parse_intake_from_pdf_end_to_end_mocked_vision_call():
    with patch(
        "backend.services.ride_pdf_intake._render_pages_to_png",
        return_value=[b"fake-png-bytes"],
    ), patch(
        "backend.services.ride_pdf_intake._call_vision_extraction",
        return_value=_BELL_MTHF_CARD,
    ):
        rows = parse_intake_from_pdf(b"%PDF-1.4 fake")

    assert len(rows) == 1
    row = rows[0]
    assert row["school"] == "Bell ES"
    assert row["direction"] == "OB"
    assert row["number"] == "01"
    assert row["days"] == ["M", "T", "Th", "F"]


def test_parse_intake_from_pdf_returns_empty_when_vision_call_fails():
    with patch(
        "backend.services.ride_pdf_intake._render_pages_to_png",
        return_value=[b"fake-png-bytes"],
    ), patch(
        "backend.services.ride_pdf_intake._call_vision_extraction",
        return_value=None,
    ):
        assert parse_intake_from_pdf(b"%PDF-1.4 fake") == []


def test_parse_intake_from_pdf_never_raises_on_garbage_input():
    # No mocking at all -- garbage bytes must fail closed at the render step.
    assert parse_intake_from_pdf(b"definitely not a pdf") == []
    assert parse_intake_from_pdf(b"") == []


# ── Live API smoke test — opt-in only, skipped in CI ──────────────────────────

_LIVE_SAMPLE_DIR = (
    "/private/tmp/claude-501/-Users-malikmilion/"
    "f96fe70c-70a0-4b30-a309-9b6354f4b086/scratchpad/ride-pdfs"
)


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_ANTHROPIC_TESTS") != "1",
    reason="live Anthropic vision call — opt-in only (set RUN_LIVE_ANTHROPIC_TESTS=1), never runs in CI",
)
def test_live_vision_extraction_against_real_pdf():
    """Real network call against the real API and a real sample PDF. Not run
    by default — as of 2026-08-19 the configured ANTHROPIC_API_KEY's org
    returns 'This organization has been disabled', unrelated to this code;
    this test exists so the moment that's fixed, `RUN_LIVE_ANTHROPIC_TESTS=1
    pytest backend/tests/test_ride_pdf_intake.py -k live` verifies the real
    call end to end against a real card."""
    sample = os.path.join(_LIVE_SAMPLE_DIR, "Bell_ES_OB_01.pdf")
    if not os.path.exists(sample):
        pytest.skip("scratchpad sample PDF not present on this machine")
    rows = parse_intake_from_pdf(open(sample, "rb").read())
    assert len(rows) == 1
    assert rows[0]["school"] == "Bell ES"
    assert rows[0]["direction"] == "OB"
    assert rows[0]["number"] == "01"
