"""
R2 Payroll Archive Service
===========================
Backs up approved Maz payroll xlsx files and emailed paystub PDFs to Cloudflare R2.

Design contract
---------------
- Every public function wraps all R2 calls in ``try/except Exception``.
- Failures are logged with ``logger.exception(...)`` — LOUD, never swallowed.
- Returns ``None`` on any failure; never raises to the caller.
- Runs AFTER the canonical DB commit — payroll is never blocked.
- No imports from payroll math modules (workflow math, summary, paystub PDF gen).
  Only imports ``r2_storage`` (low-level client) and ORM models for read-only fetches.

Key layout
----------
- Batch xlsx  : ``payroll/batches/maz/W{NN}/batch-{batch_id}.xlsx``
- Paystub PDF : ``payroll/paystubs/{company}/W{NN}/{driver-slug}-{paystub_id}.pdf``

Where ``{NN}`` is zero-padded canonical week number and ``{company}`` is the
lowercased company slug derived from the batch source field.

Usage (call sites)
------------------
After ``db.commit()`` in the approval / send flows::

    from backend.services import r2_payroll_archive, r2_storage

    if r2_storage.r2_configured():
        try:
            r2_key = r2_payroll_archive.upload_batch_xlsx(batch.payroll_batch_id, xlsx_bytes, db)
            if r2_key:
                batch.r2_key = r2_key
                db.commit()
        except Exception as exc:
            logger.warning("r2_payroll_archive: SKIPPED for batch %s — %s", batch.payroll_batch_id, exc)
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from backend.services import r2_storage

_logger = logging.getLogger("zpay.r2_payroll_archive")

# ── Constants ────────────────────────────────────────────────────────────────

_BATCH_KEY_TMPL = "payroll/batches/{company}/W{week:02d}/batch-{batch_id}.xlsx"
_STUB_KEY_TMPL = "payroll/paystubs/{company}/W{week:02d}/{driver_slug}-{paystub_id}.pdf"

_SLUG_MAX = 50
_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ── Public helpers ────────────────────────────────────────────────────────────

def r2_configured() -> bool:
    """Re-export from r2_storage for convenient import at call sites."""
    return r2_storage.r2_configured()


def _slug(name: str) -> str:
    """
    Convert *name* to a safe R2 key segment.

    Rules: lowercase ASCII, alphanumerics + hyphens, max 50 chars.
    Leading / trailing hyphens are stripped.

    Examples::
        "John Doe"          -> "john-doe"
        "Ali   Al-Rashed"   -> "ali-al-rashed"
        "Ábdúl"             -> "bdul"          (non-ASCII stripped)
        ""                  -> "unknown"
    """
    lowered = name.lower().encode("ascii", errors="ignore").decode()
    slugged = _SLUG_RE.sub("-", lowered).strip("-")
    if not slugged:
        return "unknown"
    return slugged[:_SLUG_MAX]


def _week_num(batch) -> int:
    """
    Derive the canonical payroll week number from a PayrollBatch ORM row.

    Uses the same priority chain as the Drive archive hook in workflow.py:
    1. canonical_week_num() — date arithmetic from period_start / batch_ref.
    2. batch_id % 52 (non-zero) as last-resort fallback.
    """
    from backend.utils.week_label import canonical_week_num

    period_start = getattr(batch, "period_start", None)
    batch_ref = getattr(batch, "batch_ref", None)
    canon = canonical_week_num(period_start, batch_ref)
    if canon is not None:
        return canon
    return batch.payroll_batch_id % 52 or 52


def _company_slug(batch) -> str:
    """Lowercase company prefix for the R2 path (maz, acumen, etc.)."""
    source = (getattr(batch, "source", None) or "").lower()
    if source:
        return _slug(source)
    company = (getattr(batch, "company_name", None) or "zpay").lower()
    return _slug(company)


# ── Public upload functions ───────────────────────────────────────────────────

def upload_batch_xlsx(
    batch_id: int,
    xlsx_bytes: bytes,
    db: Session,
) -> Optional[str]:
    """
    Upload the approved batch xlsx to R2 and persist the R2 key on the DB row.

    Returns the R2 key string on success, ``None`` on any failure.

    Idempotent: if the batch already has ``r2_key`` set, skip and return the
    existing key (caller may still call db.commit if desired).

    Args:
        batch_id:   PayrollBatch primary key.
        xlsx_bytes: Raw xlsx bytes already built by the approval flow.
        db:         Active SQLAlchemy session (used for read-only batch fetch
                    and for persisting r2_key after a successful upload).
    """
    try:
        from backend.db.models import PayrollBatch

        batch = db.get(PayrollBatch, batch_id)
        if batch is None:
            _logger.warning("upload_batch_xlsx: batch %s not found — skipping", batch_id)
            return None

        # Idempotent: already uploaded
        existing_key = getattr(batch, "r2_key", None)
        if existing_key:
            _logger.info(
                "upload_batch_xlsx: batch %s already has r2_key=%s — skipping",
                batch_id, existing_key,
            )
            return existing_key

        week = _week_num(batch)
        company = _company_slug(batch)
        key = _BATCH_KEY_TMPL.format(company=company, week=week, batch_id=batch_id)

        _logger.info(
            "upload_batch_xlsx: uploading batch=%s week=W%02d size=%d bytes -> %s",
            batch_id, week, len(xlsx_bytes), key,
        )

        r2_storage.upload_file(
            xlsx_bytes,
            key,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        batch.r2_key = key
        db.commit()

        _logger.info(
            "upload_batch_xlsx: batch=%s uploaded successfully -> %s", batch_id, key,
        )
        return key

    except Exception:
        _logger.exception(
            "upload_batch_xlsx: FAILED for batch=%s — R2 upload did not complete",
            batch_id,
        )
        return None


def upload_paystub_pdf(
    paystub_archive_id: int,
    pdf_bytes: bytes,
    db: Session,
) -> Optional[str]:
    """
    Upload a driver paystub PDF to R2 and persist the R2 key on the archive row.

    Returns the R2 key string on success, ``None`` on any failure.

    Idempotent: if the archive row already has ``r2_key`` set, skip and return
    the existing key.

    Args:
        paystub_archive_id: PaystubArchive primary key.
        pdf_bytes:          Raw PDF bytes (caller already has them in memory).
        db:                 Active SQLAlchemy session.
    """
    try:
        from backend.db.models import PaystubArchive, PayrollBatch, Person

        row = db.get(PaystubArchive, paystub_archive_id)
        if row is None:
            _logger.warning(
                "upload_paystub_pdf: paystub_archive_id=%s not found — skipping",
                paystub_archive_id,
            )
            return None

        # Idempotent: already uploaded
        existing_key = getattr(row, "r2_key", None)
        if existing_key:
            _logger.info(
                "upload_paystub_pdf: stub=%s already has r2_key=%s — skipping",
                paystub_archive_id, existing_key,
            )
            return existing_key

        batch = db.get(PayrollBatch, row.payroll_batch_id)
        person = db.get(Person, row.person_id)

        week = _week_num(batch) if batch else 0
        company = _company_slug(batch) if batch else "unknown"
        driver_name = (person.full_name if person else None) or "unknown"
        driver_slug = _slug(driver_name)

        key = _STUB_KEY_TMPL.format(
            company=company,
            week=week,
            driver_slug=driver_slug,
            paystub_id=paystub_archive_id,
        )

        _logger.info(
            "upload_paystub_pdf: uploading stub=%s driver=%s week=W%02d size=%d bytes -> %s",
            paystub_archive_id, driver_name, week, len(pdf_bytes), key,
        )

        r2_storage.upload_file(pdf_bytes, key, content_type="application/pdf")

        row.r2_key = key
        db.commit()

        _logger.info(
            "upload_paystub_pdf: stub=%s uploaded successfully -> %s",
            paystub_archive_id, key,
        )
        return key

    except Exception:
        _logger.exception(
            "upload_paystub_pdf: FAILED for stub=%s — R2 upload did not complete",
            paystub_archive_id,
        )
        return None
