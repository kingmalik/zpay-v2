"""
Tests for backend/services/remit_ingest.py — EFT remittance auto-ingest (T2).

Same harness as test_inbox_intake.py: in-memory SQLite via patched
backend.db.db.SessionLocal, metadata patched for SQLite compat, all Gmail
HTTP mocked — no live network, no real PDFs (_pdf_to_text is mocked; the
text parser is exercised directly on real advice text shape).

Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_remit_ingest.py -x -v
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-key-for-remit-ingest-tests-long-enough",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")  # silenced by SessionLocal patch below

from backend.db.models import Base  # noqa: E402

# ── Metadata patches (same shape as test_inbox_intake.py) ────────────────────
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
from backend.db.models import PartnerPayment, PayrollBatch  # noqa: E402
from backend.services import remit_ingest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    monkeypatch.setattr(_db_module, "SessionLocal", _TestSessionFactory)
    monkeypatch.setenv("EFT_AUTOINGEST", "1")

    yield

    sess = _TestSessionFactory()
    sess.query(PartnerPayment).delete(synchronize_session=False)
    sess.query(PayrollBatch).delete(synchronize_session=False)
    sess.commit()
    sess.close()


_NEXT_BATCH_PK = iter(range(1000, 9999))


def _add_batch(batch_id: int, week_end: date, source: str = "acumen") -> None:
    sess = _TestSessionFactory()
    sess.add(
        PayrollBatch(
            payroll_batch_id=batch_id,
            source=source,
            company_name="Acumen International",
            week_end=week_end,
        )
    )
    sess.commit()
    sess.close()


def _all_payments() -> list[PartnerPayment]:
    sess = _TestSessionFactory()
    try:
        return sess.query(PartnerPayment).order_by(PartnerPayment.partner_payment_id).all()
    finally:
        sess.close()


# Real ACH advice text shape (from the 27-PDF corpus).
_ADVICE_TEXT = """First Student Inc
ACH Advice
CONTACT.ACUMENINTL@GMAIL.COM
Supplier # 2794808 ACUMEN INTERNATIONAL
An electronic deposit of funds has been sent to your designated account. Funds in the amount of $22013.25 have been sent and should be
available a minimum of 2 working days from 02/12/2026. If you do not receive this deposit, please contact the Accounts Payable department.
Payment is made against the following Invoices :
Payment Invoice Number Invoice Date Invoice Amount Payment Company
Number Amount
1584417 0206202602794808 2/6/2026 22013.25 22013.25 06400 First Student
If you have any questions, please contact the First Student & Subsidiaries Accounts Payable Department at vendorinquiries@firststudentinc.com
"""

# Short-pay: invoiced 22013.25, actually paid 20000.00 — advice total is
# what was actually sent.
_SHORT_PAY_TEXT = _ADVICE_TEXT.replace(
    "Funds in the amount of $22013.25", "Funds in the amount of $20000.00"
).replace(
    "1584417 0206202602794808 2/6/2026 22013.25 22013.25",
    "1584417 0206202602794808 2/6/2026 22013.25 20000.00",
)

# Two invoices, two service weeks, one deposit.
_TWO_INVOICE_TEXT = _ADVICE_TEXT.replace(
    "Funds in the amount of $22013.25", "Funds in the amount of $30013.25"
).replace(
    "1584417 0206202602794808 2/6/2026 22013.25 22013.25 06400 First Student",
    "1584417 0206202602794808 2/6/2026 22013.25 22013.25 06400 First Student\n"
    "1584999 0213202602794808 2/13/2026 8000.00 8000.00 06400 First Student",
)


def _authed_message(msg_id: str) -> dict:
    return {
        "id": msg_id,
        "payload": {
            "headers": [
                {
                    "name": "Authentication-Results",
                    "value": "mx.google.com; spf=pass dkim=pass header.i=@firststudentinc.com",
                }
            ]
        },
    }


def _run(msg_id: str = "eft1", text: str = _ADVICE_TEXT, message: dict | None = None):
    msg = message if message is not None else _authed_message(msg_id)
    with patch.object(remit_ingest, "_list_eft_message_ids", return_value=[msg_id]), \
         patch.object(remit_ingest, "_gmail_get", return_value=msg), \
         patch.object(remit_ingest, "_fetch_pdf_bytes", return_value=b"%PDF-fake"), \
         patch.object(remit_ingest, "_pdf_to_text", return_value=text), \
         patch.object(remit_ingest, "_push_deposit_summary") as mock_push:
        result = remit_ingest.run_remit_ingest("tok")
    return result, mock_push


# ── text parser ───────────────────────────────────────────────────────────────

def test_parse_remit_text_extracts_deposit_and_invoice():
    advice = remit_ingest.parse_remit_text(_ADVICE_TEXT)

    assert advice is not None
    assert advice.deposit_date == date(2026, 2, 12)
    assert advice.total_amount == 22013.25
    assert len(advice.invoices) == 1
    inv = advice.invoices[0]
    assert inv.payment_number == "1584417"
    assert inv.invoice_ref == "0206202602794808"
    assert inv.external_ref == "eft:1584417:0206202602794808"
    assert inv.service_week_end == date(2026, 2, 6)
    assert inv.invoiced_amount == 22013.25
    assert inv.paid_amount == 22013.25


def test_parse_remit_text_short_pay_uses_paid_column():
    advice = remit_ingest.parse_remit_text(_SHORT_PAY_TEXT)

    assert advice is not None
    assert advice.total_amount == 20000.00
    assert advice.invoices[0].invoiced_amount == 22013.25
    assert advice.invoices[0].paid_amount == 20000.00


def test_parse_remit_text_accepts_exactly_one_cent_diff():
    # Float subtraction turns "exactly 1 cent" into 0.0100000000002 at some
    # magnitudes — the cents-based compare must still accept it.
    text = _ADVICE_TEXT.replace("Funds in the amount of $22013.25",
                                "Funds in the amount of $4871.00").replace(
        "1584417 0206202602794808 2/6/2026 22013.25 22013.25",
        "1584417 0206202602794808 2/6/2026 4871.00 4870.99",
    )
    advice = remit_ingest.parse_remit_text(text)

    assert advice is not None
    assert advice.invoices[0].paid_amount == 4870.99


def test_parse_remit_text_rejects_total_mismatch():
    # Advice total doesn't equal sum of pay amounts → refuse the whole advice.
    bad = _ADVICE_TEXT.replace("Funds in the amount of $22013.25",
                               "Funds in the amount of $99999.99")
    assert remit_ingest.parse_remit_text(bad) is None


def test_parse_remit_text_handles_comma_amounts():
    text = _ADVICE_TEXT.replace("$22013.25", "$22,013.25").replace(
        "1584417 0206202602794808 2/6/2026 22013.25 22013.25",
        "1584417 0206202602794808 2/6/2026 22,013.25 22,013.25",
    )
    advice = remit_ingest.parse_remit_text(text)

    assert advice is not None
    assert advice.total_amount == 22013.25
    assert advice.invoices[0].paid_amount == 22013.25


def test_parse_remit_text_rejects_non_advice_text():
    assert remit_ingest.parse_remit_text("FirstAlt October Newsletter body") is None


# ── flag off ──────────────────────────────────────────────────────────────────

def test_flag_off_short_circuits_without_gmail(monkeypatch):
    monkeypatch.setenv("EFT_AUTOINGEST", "0")
    with patch("backend.services.remit_ingest.requests.get") as mock_get:
        result = remit_ingest.run_remit_ingest("tok")

    assert result["checked"] == 0 and result["recorded"] == 0
    mock_get.assert_not_called()
    assert _all_payments() == []


# ── authenticity gates ────────────────────────────────────────────────────────

def test_spoofed_sender_without_auth_pass_is_rejected():
    _add_batch(107, date(2026, 2, 6))
    spoofed = {
        "id": "spoof1",
        "payload": {"headers": [
            {"name": "Authentication-Results",
             "value": "mx.google.com; spf=fail dkim=fail"},
        ]},
    }

    result, _ = _run("spoof1", message=spoofed)

    assert result["skipped_unauthenticated"] == 1
    assert result["recorded"] == 0
    assert _all_payments() == []


def test_missing_auth_header_fails_closed():
    _add_batch(107, date(2026, 2, 6))
    result, _ = _run("noauth", message={"id": "noauth", "payload": {"headers": []}})

    assert result["skipped_unauthenticated"] == 1
    assert _all_payments() == []


def test_pdf_without_supplier_id_is_rejected():
    _add_batch(107, date(2026, 2, 6))
    text = _ADVICE_TEXT.replace("2794808", "9999999")

    result, _ = _run(text=text)

    assert result["skipped_unauthenticated"] == 1
    assert _all_payments() == []


# ── happy path ────────────────────────────────────────────────────────────────

def test_records_payment_linked_to_matching_batch():
    _add_batch(107, date(2026, 2, 6))

    result, mock_push = _run()

    assert result["recorded"] == 1
    payments = _all_payments()
    assert len(payments) == 1
    p = payments[0]
    assert p.source == "acumen"
    assert float(p.amount) == 22013.25
    assert p.deposit_date == date(2026, 2, 12)
    assert p.payroll_batch_id == 107
    assert "auto-eft" in p.memo and "msg eft1 | pmt 1584417" in p.memo
    assert p.external_ref == "eft:1584417:0206202602794808"
    assert p.created_by == "inbox-watcher"
    mock_push.assert_called_once()


def test_short_pay_records_actual_paid_amount():
    _add_batch(107, date(2026, 2, 6))

    result, _ = _run(text=_SHORT_PAY_TEXT)

    assert result["recorded"] == 1
    assert float(_all_payments()[0].amount) == 20000.00  # NOT the invoiced 22013.25


# ── dedupe semantics ──────────────────────────────────────────────────────────

def test_second_cycle_dedupes_by_invoice_tag():
    _add_batch(107, date(2026, 2, 6))

    first, _ = _run()
    second, _ = _run()

    assert first["recorded"] == 1
    assert second["recorded"] == 0
    assert second["skipped_dupes"] == 1
    assert len(_all_payments()) == 1


def test_partial_ingest_retries_unmatched_invoice_next_cycle():
    """Multi-invoice advice: invoice A's batch exists, B's doesn't. Cycle 1
    records A. Cycle 2 (B's batch now uploaded) must record B — the message
    is NOT deduped as a whole."""
    _add_batch(107, date(2026, 2, 6))

    first, _ = _run(text=_TWO_INVOICE_TEXT)
    assert first["recorded"] == 1
    assert first["skipped_no_batch"] == 1

    _add_batch(108, date(2026, 2, 13))  # B's batch uploads Monday

    second, _ = _run(text=_TWO_INVOICE_TEXT)
    assert second["recorded"] == 1
    assert second["skipped_dupes"] == 1  # A correctly deduped

    payments = _all_payments()
    assert len(payments) == 2
    assert {p.payroll_batch_id for p in payments} == {107, 108}
    assert float(payments[1].amount) == 8000.00


def test_batch_with_manual_row_is_never_double_counted():
    _add_batch(107, date(2026, 2, 6))
    sess = _TestSessionFactory()
    sess.add(
        PartnerPayment(
            source="acumen",
            amount=22013.25,
            deposit_date=date(2026, 2, 12),
            payroll_batch_id=107,
            memo="entered by mom",
        )
    )
    sess.commit()
    sess.close()

    result, _ = _run()

    assert result["recorded"] == 0
    assert result["skipped_dupes"] == 1
    assert len(_all_payments()) == 1  # only mom's row


def test_prior_auto_row_on_batch_does_not_block_new_advice():
    """A batch paid across two GENUINELY DISTINCT deposits (new ACH payment
    number) gets two auto rows — only MANUAL rows block (rule 3)."""
    _add_batch(107, date(2026, 2, 6))
    second_deposit = _ADVICE_TEXT.replace("1584417", "1599999")

    first, _ = _run("eftA")
    second, _ = _run("eftB", text=second_deposit)

    assert first["recorded"] == 1
    assert second["recorded"] == 1
    assert len(_all_payments()) == 2


def test_resent_advice_email_is_deduped_by_business_key():
    """FS re-sends the same advice → new Gmail id, same payment#/invoice
    ref → must NOT double-record (dedupe key is the business key, not the
    message id)."""
    _add_batch(107, date(2026, 2, 6))

    first, _ = _run("original-msg")
    second, _ = _run("resent-msg")  # identical advice text

    assert first["recorded"] == 1
    assert second["recorded"] == 0
    assert second["skipped_dupes"] == 1
    assert len(_all_payments()) == 1


def test_one_payment_number_covering_two_invoices_records_both():
    """One ACH payment paying two invoices repeats the payment number per
    line — both lines must record (keys differ by invoice ref)."""
    _add_batch(107, date(2026, 2, 6))
    _add_batch(108, date(2026, 2, 13))
    text = _TWO_INVOICE_TEXT.replace("1584999", "1584417")  # same payment#

    result, _ = _run(text=text)

    assert result["recorded"] == 2
    refs = {p.external_ref for p in _all_payments()}
    assert refs == {
        "eft:1584417:0206202602794808",
        "eft:1584417:0213202602794808",
    }


def test_replica_race_integrityerror_treated_as_dupe():
    """Another replica inserts the same external_ref between our SELECT and
    commit — the s8c unique index fires and we count a dupe, not a crash."""
    _add_batch(107, date(2026, 2, 6))

    real_commit_hits = {"n": 0}
    import backend.db.db as dbm
    real_factory = dbm.SessionLocal

    class RacingSession:
        """Proxy that injects a competing row right before our first commit."""
        def __init__(self):
            self._s = real_factory()
            self._raced = False
        def __enter__(self):
            return self
        def __exit__(self, *a):
            self._s.close()
        def __getattr__(self, name):
            if name == "commit":
                return self._commit
            return getattr(self._s, name)
        def _commit(self):
            if not self._raced:
                self._raced = True
                other = real_factory()
                other.add(PartnerPayment(
                    source="acumen", amount=22013.25,
                    deposit_date=date(2026, 2, 12), payroll_batch_id=107,
                    external_ref="eft:1584417:0206202602794808",
                    memo="auto-eft | competing replica",
                    created_by="inbox-watcher",
                ))
                other.commit()
                other.close()
            real_commit_hits["n"] += 1
            return self._s.commit()

    with patch.object(dbm, "SessionLocal", RacingSession),          patch.object(remit_ingest, "_list_eft_message_ids", return_value=["race1"]),          patch.object(remit_ingest, "_gmail_get", return_value=_authed_message("race1")),          patch.object(remit_ingest, "_fetch_pdf_bytes", return_value=b"%PDF-fake"),          patch.object(remit_ingest, "_pdf_to_text", return_value=_ADVICE_TEXT),          patch.object(remit_ingest, "_push_deposit_summary"):
        result = remit_ingest.run_remit_ingest("tok")

    assert result["recorded"] == 0
    assert result["skipped_dupes"] == 1
    assert len(_all_payments()) == 1  # only the competing replica's row


def test_attacker_aligned_auth_is_rejected():
    """spf=pass/dkim=pass on the ATTACKER's domain with a forged From: must
    not authenticate — only aligned passes count."""
    _add_batch(107, date(2026, 2, 6))
    forged = {
        "id": "forge1",
        "payload": {"headers": [
            {"name": "Authentication-Results",
             "value": ("mx.google.com; spf=pass smtp.mailfrom=attacker.com; "
                       "dkim=pass header.i=@attacker.com; dmarc=fail")},
        ]},
    }

    result, _ = _run("forge1", message=forged)

    assert result["skipped_unauthenticated"] == 1
    assert _all_payments() == []


def test_dmarc_pass_alone_authenticates():
    _add_batch(107, date(2026, 2, 6))
    msg = {
        "id": "dm1",
        "payload": {"headers": [
            {"name": "Authentication-Results",
             "value": "mx.google.com; dmarc=pass header.from=firststudentinc.com"},
        ]},
    }

    result, _ = _run("dm1", message=msg)

    assert result["recorded"] == 1


# ── batch matching guards ─────────────────────────────────────────────────────

def test_missing_batch_skips_and_writes_nothing():
    result, mock_push = _run()

    assert result["recorded"] == 0
    assert result["skipped_no_batch"] == 1
    assert _all_payments() == []
    mock_push.assert_called_once_with([])


def test_ambiguous_duplicate_week_end_batches_are_skipped():
    _add_batch(107, date(2026, 2, 6))
    _add_batch(207, date(2026, 2, 6))  # duplicate acumen week_end

    result, _ = _run()

    assert result["recorded"] == 0
    assert result["skipped_no_batch"] == 1
    assert _all_payments() == []


def test_non_acumen_batch_with_same_week_end_is_not_matched():
    _add_batch(200, date(2026, 2, 6), source="maz")

    result, _ = _run()

    assert result["skipped_no_batch"] == 1
    assert _all_payments() == []


# ── resilience ────────────────────────────────────────────────────────────────

def test_unparseable_pdf_is_skipped_cleanly():
    _add_batch(107, date(2026, 2, 6))
    result, _ = _run(text="not an advice")

    assert result["recorded"] == 0
    assert _all_payments() == []


def test_gmail_failure_never_raises():
    with patch.object(remit_ingest, "_list_eft_message_ids", side_effect=RuntimeError("boom")):
        result = remit_ingest.run_remit_ingest("tok")

    assert result["recorded"] == 0
