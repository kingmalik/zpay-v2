"""
Tests for backend/services/inbox_intake.py — Gmail inbox auto-intake watcher.

Full in-memory SQLite via a patched backend.db.db.SessionLocal, mirroring the
established pattern in test_assignment_routes.py (metadata patches for SQLite
compatibility — BigInteger PKs, NOW() defaults). All Gmail HTTP is mocked —
no live network calls in this file.

Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_inbox_intake.py -x -v
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-key-for-inbox-intake-tests-long-enough",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")  # silenced by SessionLocal patch below

from backend.db.models import Base  # noqa: E402

# ── Metadata patches (same shape as test_assignment_routes.py) ───────────────
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()

for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.server_default is not None:
            _sd = _col.server_default
            try:
                _arg = _sd.arg.text if hasattr(_sd, "arg") and hasattr(_sd.arg, "text") else ""
            except Exception:
                _arg = ""
            if "NOW()" in _arg:
                _col.nullable = True
                _col.server_default = None

if "z_rate_override" in Base.metadata.tables:
    Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()

_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
)
Base.metadata.create_all(_engine)

_TestSessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

import backend.db.db as _db_module  # noqa: E402
from backend.db.models import RideIntake  # noqa: E402
from backend.services import inbox_intake  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_db_and_state(monkeypatch):
    """Point the watcher's `from backend.db.db import SessionLocal` at our
    in-memory sqlite factory, wipe ride_intake between tests, and reset the
    module-level token cache / status so tests don't bleed into each other."""
    monkeypatch.setattr(_db_module, "SessionLocal", _TestSessionFactory)

    sess = _TestSessionFactory()
    sess.query(RideIntake).delete(synchronize_session=False)
    sess.commit()
    sess.close()

    inbox_intake._token_cache["access_token"] = None
    inbox_intake._token_cache["expires_at"] = 0.0
    inbox_intake._status["enabled"] = None
    inbox_intake._status["last_run_at"] = None
    inbox_intake._status["last_result"] = {"checked": 0, "created": 0, "skipped_dupes": 0}
    inbox_intake._status["poll_minutes"] = None

    monkeypatch.setenv("INBOX_AUTOINTAKE", "1")
    monkeypatch.setenv("GMAIL_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN_BIZ_RO", "test-refresh-token")
    # PDF-attachment vision extraction is opt-in per cycle (ANTHROPIC_API_KEY
    # presence) — force it off by default so tests are deterministic
    # regardless of what's in the ambient shell env; tests that specifically
    # exercise the PDF path set it back with monkeypatch.setenv.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    yield

    sess = _TestSessionFactory()
    sess.query(RideIntake).delete(synchronize_session=False)
    sess.commit()
    sess.close()


def _all_intakes():
    sess = _TestSessionFactory()
    try:
        return sess.query(RideIntake).order_by(RideIntake.intake_id).all()
    finally:
        sess.close()


def _b64url(text: str) -> str:
    """Gmail-style unpadded base64url encoding."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _plain_part(text: str) -> dict:
    return {"mimeType": "text/plain", "body": {"data": _b64url(text)}}


def _html_part(html: str) -> dict:
    return {"mimeType": "text/html", "body": {"data": _b64url(html)}}


def _message(msg_id: str, subject: str, parts: list[dict] | None = None,
             single_body: str | None = None) -> dict:
    payload = {"headers": [{"name": "Subject", "value": subject}]}
    if parts is not None:
        payload["mimeType"] = "multipart/mixed"
        payload["parts"] = parts
    elif single_body is not None:
        payload["mimeType"] = "text/plain"
        payload["body"] = {"data": _b64url(single_body)}
    return {"id": msg_id, "payload": payload}


_SAMPLE_BODY = (
    'Subject: LWSD - New Trip\n\n'
    "Hi team, new route for you: Risalah ES IB 05, the pay is $45.00, 12 miles, "
    "set to start on Monday the 12th."
)


# ── flag-off short-circuit ────────────────────────────────────────────────────

def test_flag_off_short_circuits_without_any_gmail_call(monkeypatch):
    monkeypatch.setenv("INBOX_AUTOINTAKE", "0")
    with patch("backend.services.inbox_intake.requests.post") as mock_post, \
         patch("backend.services.inbox_intake.requests.get") as mock_get:
        result = inbox_intake.run_inbox_intake()

    assert result == {"checked": 0, "created": 0, "skipped_dupes": 0}
    mock_post.assert_not_called()
    mock_get.assert_not_called()
    assert inbox_intake.get_inbox_status()["enabled"] is False
    assert _all_intakes() == []


# ── dedupe by source_msg_id ───────────────────────────────────────────────────

def test_dedupe_by_source_msg_id_across_two_cycles():
    msg = _message("m1", "LWSD - New Trip", single_body=_SAMPLE_BODY)

    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=["m1"]), \
         patch.object(inbox_intake, "_gmail_get_message", return_value=msg):
        first = inbox_intake.run_inbox_intake()
        second = inbox_intake.run_inbox_intake()

    assert first == {"checked": 1, "created": 1, "skipped_dupes": 0}
    assert second == {"checked": 1, "created": 0, "skipped_dupes": 1}

    rows = _all_intakes()
    assert len(rows) == 1
    assert rows[0].source_msg_id == "m1"


# ── re:/fw:/fwd: skipping ─────────────────────────────────────────────────────

@pytest.mark.parametrize("prefix", ["Re:", "RE:", "Fw:", "FWD:", "fwd:"])
def test_reply_and_forward_subjects_are_skipped(prefix):
    msg = _message("m-reply", f"{prefix} LWSD - New Trip", single_body=_SAMPLE_BODY)

    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=["m-reply"]), \
         patch.object(inbox_intake, "_gmail_get_message", return_value=msg):
        result = inbox_intake.run_inbox_intake()

    assert result == {"checked": 1, "created": 0, "skipped_dupes": 0}
    assert _all_intakes() == []


# ── body extraction ───────────────────────────────────────────────────────────

def test_body_extraction_prefers_text_plain_in_multipart():
    parts = [
        {
            "mimeType": "multipart/alternative",
            "parts": [
                _plain_part("Risalah ES IB 05, the pay is $45.00, 12 miles."),
                _html_part("<div><b>Risalah ES IB 05</b>, the pay is $45.00, 12 miles.</div>"),
            ],
        },
        {"mimeType": "application/pdf", "filename": "attachment.pdf", "body": {"attachmentId": "abc"}},
    ]
    msg = _message("m-multipart", "LWSD - New Trip", parts=parts)

    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=["m-multipart"]), \
         patch.object(inbox_intake, "_gmail_get_message", return_value=msg):
        result = inbox_intake.run_inbox_intake()

    assert result["created"] == 1
    rows = _all_intakes()
    assert len(rows) == 1
    assert "Risalah ES IB 05" in rows[0].raw_text
    assert "<b>" not in rows[0].raw_text  # plain part chosen over html
    assert rows[0].parsed["net_pay"] == 45.0


def test_body_extraction_falls_back_to_html_when_no_plain_part():
    parts = [_html_part("<p>Risalah ES IB 05, the pay is $45.00, 12 miles.</p>")]
    msg = _message("m-html-only", "LWSD - New Trip", parts=parts)

    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=["m-html-only"]), \
         patch.object(inbox_intake, "_gmail_get_message", return_value=msg):
        result = inbox_intake.run_inbox_intake()

    assert result["created"] == 1
    rows = _all_intakes()
    assert "<p>" not in rows[0].raw_text
    assert "Risalah ES IB 05" in rows[0].raw_text
    assert rows[0].parsed["net_pay"] == 45.0


# ── one bad message does not kill the batch ───────────────────────────────────

def test_one_bad_message_does_not_stop_the_batch():
    good_msg = _message("good2", "LWSD - New Trip", single_body=_SAMPLE_BODY)

    def _flaky_get(_token, msg_id):
        if msg_id == "bad1":
            raise RuntimeError("simulated Gmail hiccup")
        return good_msg

    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=["bad1", "good2"]), \
         patch.object(inbox_intake, "_gmail_get_message", side_effect=_flaky_get):
        result = inbox_intake.run_inbox_intake()

    assert result["checked"] == 2
    assert result["created"] == 1
    rows = _all_intakes()
    assert len(rows) == 1
    assert rows[0].source_msg_id == "good2"


# ── token minting (real requests.post path, mocked) ───────────────────────────

def test_mint_access_token_missing_credentials_returns_none(monkeypatch):
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN_BIZ_RO", raising=False)
    with patch("backend.services.inbox_intake.requests.post") as mock_post:
        token = inbox_intake._mint_access_token()
    assert token is None
    mock_post.assert_not_called()


def test_mint_access_token_caches_until_near_expiry():
    fake_resp = type("R", (), {"status_code": 200, "json": lambda self: {"access_token": "tok-1", "expires_in": 3600}, "text": ""})()
    with patch("backend.services.inbox_intake.requests.post", return_value=fake_resp) as mock_post:
        first = inbox_intake._mint_access_token()
        second = inbox_intake._mint_access_token()

    assert first == "tok-1"
    assert second == "tok-1"
    mock_post.assert_called_once()


def test_mint_access_token_returns_none_on_non_200():
    fake_resp = type("R", (), {"status_code": 401, "json": lambda self: {}, "text": "invalid_grant"})()
    with patch("backend.services.inbox_intake.requests.post", return_value=fake_resp):
        token = inbox_intake._mint_access_token()
    assert token is None


# ── ntfy summary push ──────────────────────────────────────────────────────────

def test_ntfy_push_fires_with_district_summary_when_offers_created():
    msg = _message("m-ntfy", "LWSD - New Trip", single_body=_SAMPLE_BODY)

    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=["m-ntfy"]), \
         patch.object(inbox_intake, "_gmail_get_message", return_value=msg), \
         patch.object(inbox_intake, "_hm_push_ntfy") as mock_ntfy:
        inbox_intake.run_inbox_intake()

    mock_ntfy.assert_called_once()
    _, kwargs = mock_ntfy.call_args
    assert "1 new FA offer" in kwargs["body"]
    assert "LWSD" in kwargs["body"]
    assert "/dispatch/assign" in kwargs["body"]


def test_ntfy_push_skipped_when_nothing_new():
    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=[]), \
         patch.object(inbox_intake, "_hm_push_ntfy") as mock_ntfy:
        result = inbox_intake.run_inbox_intake()

    assert result == {"checked": 0, "created": 0, "skipped_dupes": 0}
    mock_ntfy.assert_not_called()


# ── status snapshot ────────────────────────────────────────────────────────────

def test_get_inbox_status_reflects_last_cycle():
    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=[]):
        inbox_intake.run_inbox_intake()

    status = inbox_intake.get_inbox_status()
    assert status["enabled"] is True
    assert status["last_run_at"] is not None
    assert status["last_result"] == {"checked": 0, "created": 0, "skipped_dupes": 0}
    assert status["poll_minutes"] == 10


# ── PDF attachment extraction (FirstAlt "Trip Plan" route sheets) ────────────

def _pdf_attachment_part(filename: str = "Bell ES OB 01.pdf", attachment_id: str = "att-1") -> dict:
    return {
        "mimeType": "application/pdf",
        "filename": filename,
        "body": {"attachmentId": attachment_id},
    }


def test_pdf_attachment_skipped_when_anthropic_key_absent(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    parts = [_plain_part(_SAMPLE_BODY), _pdf_attachment_part()]
    msg = _message("m-pdf-noapikey", "LWSD - New Trip", parts=parts)

    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=["m-pdf-noapikey"]), \
         patch.object(inbox_intake, "_gmail_get_message", return_value=msg), \
         patch.object(inbox_intake, "_gmail_get_attachment") as mock_get_att:
        result = inbox_intake.run_inbox_intake()

    assert result["created"] == 1
    mock_get_att.assert_not_called()  # no key -> never even fetch the attachment
    rows = _all_intakes()
    assert rows[0].parsed["school"] == "Risalah ES"  # body-text parse still ran fine


def test_pdf_attachment_merges_fields_without_overwriting_body_parse(monkeypatch):
    """Ground truth for _SAMPLE_BODY (verified via parse_intake directly):
    school="Risalah ES", direction="IB", number="05", miles=12.0, net_pay=45.0,
    days=["M"], district="LWSD", is_recurring=False, start_date="Monday the 12th"
    -- all non-None, so the PDF's (deliberately different) values for those
    fields must NOT come through. start_time/net_pay_ob/origin/destination/
    requirements ARE None from body-text alone, so those DO get filled."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    parts = [_plain_part(_SAMPLE_BODY), _pdf_attachment_part()]
    msg = _message("m-pdf-merge", "LWSD - New Trip", parts=parts)

    pdf_row = {
        "school": "Different School Name",
        "direction": "OB",
        "number": "99",
        "is_odt": True,
        "wheelchair": True,
        "miles": 999.0,
        "net_pay": 999.0,
        "days": ["W"],
        "start_time": "03:15 PM",
        "notes": "pdf notes",
        "district": "Different District",
        "is_recurring": True,
        "net_pay_ib": 999.0,
        "net_pay_ob": 55.0,
        "start_date": "08/31/2026",
        "origin": "Kirkland",
        "destination": "Kent",
        "requirements": ["booster seat"],
    }

    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=["m-pdf-merge"]), \
         patch.object(inbox_intake, "_gmail_get_message", return_value=msg), \
         patch.object(inbox_intake, "_gmail_get_attachment", return_value=b"%PDF-fake-bytes"), \
         patch("backend.services.ride_pdf_intake.parse_intake_from_pdf", return_value=[pdf_row]):
        result = inbox_intake.run_inbox_intake()

    assert result["created"] == 1
    parsed = _all_intakes()[0].parsed

    # Body-text already had these -- PDF must never clobber them.
    assert parsed["school"] == "Risalah ES"
    assert parsed["direction"] == "IB"
    assert parsed["number"] == "05"
    assert parsed["miles"] == 12.0
    assert parsed["net_pay"] == 45.0
    assert parsed["days"] == ["M"]
    assert parsed["district"] == "LWSD"
    assert parsed["is_recurring"] is False
    assert parsed["start_date"] == "Monday the 12th"

    # Body-text left these None -- the PDF fills them in.
    assert parsed["start_time"] == "03:15 PM"
    assert parsed["net_pay_ob"] == 55.0
    assert parsed["origin"] == "Kirkland"
    assert parsed["destination"] == "Kent"
    assert parsed["requirements"] == ["booster seat"]


def test_pdf_attachment_fetch_failure_does_not_break_message_processing():
    parts = [_plain_part(_SAMPLE_BODY), _pdf_attachment_part()]
    msg = _message("m-pdf-fail", "LWSD - New Trip", parts=parts)

    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=["m-pdf-fail"]), \
         patch.object(inbox_intake, "_gmail_get_message", return_value=msg), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
         patch.object(inbox_intake, "_gmail_get_attachment", side_effect=RuntimeError("boom")):
        result = inbox_intake.run_inbox_intake()

    assert result["created"] == 1  # the message still gets created off body text alone
    rows = _all_intakes()
    assert rows[0].parsed["school"] == "Risalah ES"


def test_multiple_pdf_attachments_only_first_extractable_route_merged():
    parts = [
        _plain_part(_SAMPLE_BODY),
        _pdf_attachment_part("Route A.pdf", "att-a"),
        _pdf_attachment_part("Route B.pdf", "att-b"),
    ]
    msg = _message("m-pdf-multi", "Fife SD - New Routes", parts=parts)

    # _SAMPLE_BODY already yields days=["M"] on its own (verified in the merge
    # test above) -- use start_time (None from body-text alone) as the field
    # that proves attachment A's extraction actually landed.
    row_a = {
        "school": None, "direction": None, "number": None, "is_odt": False,
        "wheelchair": False, "miles": None, "net_pay": None,
        "days": None, "start_time": "03:15 PM", "notes": "route A",
        "district": None, "is_recurring": None, "net_pay_ib": None,
        "net_pay_ob": None, "start_date": None, "origin": None,
        "destination": None, "requirements": None,
    }

    def _fake_parse(pdf_bytes):
        return [row_a]  # both attachments would extract fine; only the first is used

    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=["m-pdf-multi"]), \
         patch.object(inbox_intake, "_gmail_get_message", return_value=msg), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
         patch.object(inbox_intake, "_gmail_get_attachment", return_value=b"%PDF-fake") as mock_get_att, \
         patch("backend.services.ride_pdf_intake.parse_intake_from_pdf", side_effect=_fake_parse):
        result = inbox_intake.run_inbox_intake()

    assert result["created"] == 1
    parsed = _all_intakes()[0].parsed
    assert parsed["start_time"] == "03:15 PM"
    mock_get_att.assert_called_once_with("tok", "m-pdf-multi", "att-a")  # stopped after first hit


def test_pdf_attachment_needs_info_flag_flows_through_the_merge():
    """A multi-stop card's needs_info=True must survive the merge into the
    body-text parsed dict unchanged (the body-text parser has no concept of
    needs_info, so this is a pure fill-in, never something to negotiate).
    Uses a body/subject combo that yields notes=None from body-text alone
    (unlike _SAMPLE_BODY, which always sets notes via its LWSD subject
    match) so the PDF's multi-stop notes are visibly the ones that land."""
    bare_body = "Subject: quick check-in\n\nHi team, checking on this one, let me know."
    parts = [_plain_part(bare_body), _pdf_attachment_part()]
    msg = _message("m-pdf-needsinfo", "quick check-in", parts=parts)

    multi_stop_row = {
        "school": None, "direction": None, "number": None, "is_odt": False,
        "wheelchair": False, "miles": None, "net_pay": None,
        "days": None, "start_time": None,
        "notes": "⚠ MULTI-STOP ROUTE — 3 stops total, only the first pickup + "
                 "final dropoff are in the fields above · unmapped stop 1: "
                 "pickup 02:45 PM @ Surprise Lake MS (Aliyah'Marie Heleta)",
        "district": None, "is_recurring": None, "net_pay_ib": None,
        "net_pay_ob": None, "start_date": None, "origin": None,
        "destination": None, "requirements": None, "needs_info": True,
    }

    with patch.object(inbox_intake, "_mint_access_token", return_value="tok"), \
         patch.object(inbox_intake, "_gmail_list_message_ids", return_value=["m-pdf-needsinfo"]), \
         patch.object(inbox_intake, "_gmail_get_message", return_value=msg), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
         patch.object(inbox_intake, "_gmail_get_attachment", return_value=b"%PDF-fake"), \
         patch("backend.services.ride_pdf_intake.parse_intake_from_pdf", return_value=[multi_stop_row]):
        result = inbox_intake.run_inbox_intake()

    assert result["created"] == 1
    parsed = _all_intakes()[0].parsed
    assert parsed["needs_info"] is True
    assert "MULTI-STOP ROUTE" in parsed["notes"]
    assert "Surprise Lake MS" in parsed["notes"]
