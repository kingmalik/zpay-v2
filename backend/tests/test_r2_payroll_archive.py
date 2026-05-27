"""
Tests for r2_payroll_archive service.

Covers:
  1.  _slug: edge cases (empty, unicode, long, hyphens, spaces)
  2.  _week_num: canonical derivation + batch_ref override + fallback
  3.  _company_slug: source field extraction
  4.  upload_batch_xlsx — happy path: correct R2 key returned, db.commit called
  5.  upload_batch_xlsx — R2 raises: returns None, never re-raises
  6.  upload_batch_xlsx — batch not found: returns None, no upload
  7.  upload_batch_xlsx — already has r2_key: skips upload, returns existing key
  8.  upload_paystub_pdf — happy path: correct R2 key returned, db.commit called
  9.  upload_paystub_pdf — R2 raises: returns None, never re-raises
  10. upload_paystub_pdf — archive row not found: returns None
  11. upload_paystub_pdf — already has r2_key: skips upload, returns existing key
  12. r2_configured re-export: delegates to r2_storage
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_batch(
    batch_id: int = 99,
    source: str = "maz",
    period_start=None,
    batch_ref: str | None = None,
    r2_key: str | None = None,
):
    b = SimpleNamespace()
    b.payroll_batch_id = batch_id
    b.source = source
    b.company_name = "Maz Services"
    b.period_start = period_start or date(2026, 4, 13)
    b.batch_ref = batch_ref
    b.r2_key = r2_key
    return b


def _make_archive_row(
    paystub_id: int = 1,
    person_id: int = 10,
    batch_id: int = 99,
    r2_key: str | None = None,
):
    r = SimpleNamespace()
    r.paystub_id = paystub_id
    r.person_id = person_id
    r.payroll_batch_id = batch_id
    r.r2_key = r2_key
    return r


def _make_person(person_id: int = 10, full_name: str = "John Doe"):
    p = SimpleNamespace()
    p.person_id = person_id
    p.full_name = full_name
    return p


def _make_db(
    batch=None,
    archive_row=None,
    person=None,
):
    """Return a minimal mock Session whose .get() dispatches by model class."""
    from backend.db.models import PayrollBatch, PaystubArchive, Person

    lookup = {}
    if batch is not None:
        lookup[PayrollBatch] = batch
    if archive_row is not None:
        lookup[PaystubArchive] = archive_row
    if person is not None:
        lookup[Person] = person

    db = MagicMock()

    def _get(model_cls, pk):
        return lookup.get(model_cls)

    db.get.side_effect = _get
    return db


# ── 1. _slug ──────────────────────────────────────────────────────────────────

class TestSlug:
    def test_basic(self):
        from backend.services.r2_payroll_archive import _slug
        assert _slug("John Doe") == "john-doe"

    def test_leading_trailing_stripped(self):
        from backend.services.r2_payroll_archive import _slug
        assert _slug("  Ali  ") == "ali"

    def test_multiple_spaces_become_single_hyphen(self):
        from backend.services.r2_payroll_archive import _slug
        assert _slug("Ali   Al-Rashed") == "ali-al-rashed"

    def test_non_ascii_stripped(self):
        from backend.services.r2_payroll_archive import _slug
        result = _slug("Ábdúl")
        assert all(c.isascii() for c in result)

    def test_empty_returns_unknown(self):
        from backend.services.r2_payroll_archive import _slug
        assert _slug("") == "unknown"

    def test_only_special_chars_returns_unknown(self):
        from backend.services.r2_payroll_archive import _slug
        assert _slug("!!!") == "unknown"

    def test_max_50_chars(self):
        from backend.services.r2_payroll_archive import _slug
        long_name = "a" * 100
        result = _slug(long_name)
        assert len(result) <= 50

    def test_no_uppercase(self):
        from backend.services.r2_payroll_archive import _slug
        result = _slug("DRIVER NAME")
        assert result == result.lower()


# ── 2. _week_num ─────────────────────────────────────────────────────────────

class TestWeekNum:
    def test_derives_from_period_start(self):
        from backend.services.r2_payroll_archive import _week_num
        batch = _make_batch(period_start=date(2026, 4, 13))  # W15 canonical
        assert _week_num(batch) == 15

    def test_batch_ref_override(self):
        from backend.services.r2_payroll_archive import _week_num
        batch = _make_batch(batch_ref="OY2026W18-something")
        assert _week_num(batch) == 18

    def test_fallback_when_no_period_start(self):
        """Fallback: batch_id % 52 or 52."""
        from backend.services.r2_payroll_archive import _week_num
        batch = _make_batch(batch_id=52)
        batch.period_start = None
        batch.batch_ref = None
        # 52 % 52 == 0, so fallback uses 52
        assert _week_num(batch) == 52

    def test_fallback_nonzero_mod(self):
        from backend.services.r2_payroll_archive import _week_num
        batch = _make_batch(batch_id=85)
        batch.period_start = None
        batch.batch_ref = None
        # 85 % 52 = 33
        assert _week_num(batch) == 33


# ── 3. _company_slug ─────────────────────────────────────────────────────────

class TestCompanySlug:
    def test_maz_source(self):
        from backend.services.r2_payroll_archive import _company_slug
        batch = _make_batch(source="maz")
        assert _company_slug(batch) == "maz"

    def test_acumen_source(self):
        from backend.services.r2_payroll_archive import _company_slug
        batch = _make_batch(source="acumen")
        assert _company_slug(batch) == "acumen"

    def test_uppercase_normalised(self):
        from backend.services.r2_payroll_archive import _company_slug
        batch = _make_batch(source="MAZ")
        assert _company_slug(batch) == "maz"


# ── 4. upload_batch_xlsx — happy path ────────────────────────────────────────

class TestUploadBatchXlsxHappyPath:
    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_returns_r2_key(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_batch_xlsx

        mock_r2.upload_file.return_value = "payroll/batches/maz/W15/batch-99.xlsx"

        batch = _make_batch(batch_id=99)
        db = _make_db(batch=batch)

        xlsx_bytes = b"fake xlsx"
        result = upload_batch_xlsx(99, xlsx_bytes, db)

        assert result == "payroll/batches/maz/W15/batch-99.xlsx"

    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_key_format(self, mock_r2):
        """Key must match payroll/batches/{company}/W{NN}/batch-{id}.xlsx"""
        from backend.services.r2_payroll_archive import upload_batch_xlsx

        mock_r2.upload_file.return_value = None  # doesn't matter — we inspect the call arg

        batch = _make_batch(batch_id=99, period_start=date(2026, 4, 13))  # W15
        db = _make_db(batch=batch)

        upload_batch_xlsx(99, b"data", db)

        call_args = mock_r2.upload_file.call_args
        key_used = call_args[0][1]  # second positional arg
        assert key_used == "payroll/batches/maz/W15/batch-99.xlsx"

    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_db_commit_called(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_batch_xlsx

        mock_r2.upload_file.return_value = None

        batch = _make_batch(batch_id=99)
        db = _make_db(batch=batch)

        upload_batch_xlsx(99, b"data", db)

        db.commit.assert_called()

    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_r2_key_set_on_batch(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_batch_xlsx

        mock_r2.upload_file.return_value = None

        batch = _make_batch(batch_id=99)
        db = _make_db(batch=batch)

        upload_batch_xlsx(99, b"data", db)

        assert batch.r2_key is not None
        assert "payroll/batches" in batch.r2_key


# ── 5. upload_batch_xlsx — R2 raises ─────────────────────────────────────────

class TestUploadBatchXlsxR2Failure:
    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_returns_none_on_r2_error(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_batch_xlsx

        mock_r2.upload_file.side_effect = ConnectionError("R2 unreachable")

        batch = _make_batch(batch_id=99)
        db = _make_db(batch=batch)

        result = upload_batch_xlsx(99, b"data", db)
        assert result is None

    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_does_not_raise_to_caller(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_batch_xlsx

        mock_r2.upload_file.side_effect = RuntimeError("some unexpected error")

        batch = _make_batch(batch_id=99)
        db = _make_db(batch=batch)

        # Must not raise — this is the payroll safety guarantee
        try:
            result = upload_batch_xlsx(99, b"data", db)
        except Exception as exc:
            pytest.fail(f"upload_batch_xlsx raised when it should have returned None: {exc}")
        assert result is None

    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_failure_logged_with_exception(self, mock_r2, caplog):
        """Failure must be logged at ERROR level with stack trace (not swallowed silently)."""
        import logging
        from backend.services.r2_payroll_archive import upload_batch_xlsx

        mock_r2.upload_file.side_effect = ValueError("bad bytes")

        batch = _make_batch(batch_id=99)
        db = _make_db(batch=batch)

        with caplog.at_level(logging.ERROR, logger="zpay.r2_payroll_archive"):
            upload_batch_xlsx(99, b"data", db)

        assert any("FAILED" in r.message for r in caplog.records), (
            "Expected a FAILED log message — failure must be loud, not swallowed"
        )


# ── 6. upload_batch_xlsx — batch not found ───────────────────────────────────

class TestUploadBatchXlsxNotFound:
    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_returns_none_when_batch_missing(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_batch_xlsx

        db = _make_db(batch=None)  # db.get returns None

        result = upload_batch_xlsx(999, b"data", db)
        assert result is None
        mock_r2.upload_file.assert_not_called()


# ── 7. upload_batch_xlsx — idempotent skip ───────────────────────────────────

class TestUploadBatchXlsxIdempotent:
    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_skips_if_already_uploaded(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_batch_xlsx

        existing_key = "payroll/batches/maz/W15/batch-99.xlsx"
        batch = _make_batch(batch_id=99, r2_key=existing_key)
        db = _make_db(batch=batch)

        result = upload_batch_xlsx(99, b"data", db)

        assert result == existing_key
        mock_r2.upload_file.assert_not_called()


# ── 8. upload_paystub_pdf — happy path ───────────────────────────────────────

class TestUploadPaystubPdfHappyPath:
    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_returns_r2_key(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_paystub_pdf

        mock_r2.upload_file.return_value = None

        archive_row = _make_archive_row(paystub_id=1, person_id=10, batch_id=99)
        batch = _make_batch(batch_id=99)
        person = _make_person(person_id=10, full_name="John Doe")
        db = _make_db(batch=batch, archive_row=archive_row, person=person)

        result = upload_paystub_pdf(1, b"pdf bytes", db)

        assert result is not None
        assert "payroll/paystubs" in result
        assert "john-doe" in result
        assert "-1.pdf" in result  # paystub_id in filename

    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_key_format(self, mock_r2):
        """Key: payroll/paystubs/{company}/W{NN}/{driver-slug}-{paystub_id}.pdf"""
        from backend.services.r2_payroll_archive import upload_paystub_pdf

        mock_r2.upload_file.return_value = None

        archive_row = _make_archive_row(paystub_id=7, person_id=10, batch_id=99)
        batch = _make_batch(batch_id=99, period_start=date(2026, 4, 13))  # W15
        person = _make_person(person_id=10, full_name="Jane Smith")
        db = _make_db(batch=batch, archive_row=archive_row, person=person)

        upload_paystub_pdf(7, b"pdf", db)

        call_args = mock_r2.upload_file.call_args
        key_used = call_args[0][1]
        assert key_used == "payroll/paystubs/maz/W15/jane-smith-7.pdf"

    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_db_commit_called(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_paystub_pdf

        mock_r2.upload_file.return_value = None

        archive_row = _make_archive_row()
        batch = _make_batch()
        person = _make_person()
        db = _make_db(batch=batch, archive_row=archive_row, person=person)

        upload_paystub_pdf(1, b"pdf", db)
        db.commit.assert_called()

    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_r2_key_set_on_archive_row(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_paystub_pdf

        mock_r2.upload_file.return_value = None

        archive_row = _make_archive_row()
        batch = _make_batch()
        person = _make_person()
        db = _make_db(batch=batch, archive_row=archive_row, person=person)

        upload_paystub_pdf(1, b"pdf", db)
        assert archive_row.r2_key is not None


# ── 9. upload_paystub_pdf — R2 raises ────────────────────────────────────────

class TestUploadPaystubPdfR2Failure:
    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_returns_none_on_r2_error(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_paystub_pdf

        mock_r2.upload_file.side_effect = ConnectionError("R2 down")

        archive_row = _make_archive_row()
        batch = _make_batch()
        person = _make_person()
        db = _make_db(batch=batch, archive_row=archive_row, person=person)

        result = upload_paystub_pdf(1, b"pdf", db)
        assert result is None

    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_does_not_raise_to_caller(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_paystub_pdf

        mock_r2.upload_file.side_effect = RuntimeError("boom")

        archive_row = _make_archive_row()
        batch = _make_batch()
        person = _make_person()
        db = _make_db(batch=batch, archive_row=archive_row, person=person)

        try:
            result = upload_paystub_pdf(1, b"pdf", db)
        except Exception as exc:
            pytest.fail(f"upload_paystub_pdf raised when it should return None: {exc}")
        assert result is None

    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_failure_logged_with_exception(self, mock_r2, caplog):
        """R2 failure must be LOUD — logged at ERROR with stack trace."""
        import logging
        from backend.services.r2_payroll_archive import upload_paystub_pdf

        mock_r2.upload_file.side_effect = OSError("disk gone")

        archive_row = _make_archive_row()
        batch = _make_batch()
        person = _make_person()
        db = _make_db(batch=batch, archive_row=archive_row, person=person)

        with caplog.at_level(logging.ERROR, logger="zpay.r2_payroll_archive"):
            upload_paystub_pdf(1, b"pdf", db)

        assert any("FAILED" in r.message for r in caplog.records), (
            "Expected a FAILED log message — failure must be loud, not swallowed"
        )


# ── 10. upload_paystub_pdf — archive row not found ───────────────────────────

class TestUploadPaystubPdfNotFound:
    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_returns_none_when_row_missing(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_paystub_pdf

        db = _make_db(archive_row=None)

        result = upload_paystub_pdf(9999, b"pdf", db)
        assert result is None
        mock_r2.upload_file.assert_not_called()


# ── 11. upload_paystub_pdf — idempotent skip ─────────────────────────────────

class TestUploadPaystubPdfIdempotent:
    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_skips_if_already_uploaded(self, mock_r2):
        from backend.services.r2_payroll_archive import upload_paystub_pdf

        existing_key = "payroll/paystubs/maz/W15/john-doe-1.pdf"
        archive_row = _make_archive_row(paystub_id=1, r2_key=existing_key)
        db = _make_db(archive_row=archive_row)

        result = upload_paystub_pdf(1, b"pdf", db)

        assert result == existing_key
        mock_r2.upload_file.assert_not_called()


# ── 12. r2_configured re-export ──────────────────────────────────────────────

class TestR2ConfiguredReexport:
    @patch("backend.services.r2_payroll_archive.r2_storage")
    def test_delegates_to_r2_storage(self, mock_r2):
        from backend.services.r2_payroll_archive import r2_configured

        mock_r2.r2_configured.return_value = True
        assert r2_configured() is True

        mock_r2.r2_configured.return_value = False
        assert r2_configured() is False
