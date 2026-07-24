"""
backend/services/remit_ingest.py
================================
EFT remittance auto-ingest — companion to the inbox auto-intake watcher
(T2, TRANSITION-PLAN-2026-07). Watches the business Gmail inbox (READ-ONLY)
for "First Student EFT Remittance Advice" emails, parses the attached ACH
advice PDF, and auto-creates PartnerPayment rows so deposits reconcile
against expected batch revenue without anyone hand-entering them.

Internal-only: NEVER sends anything external. Output = partner_payment rows
+ an owner ntfy push. Runs inside the existing inbox_intake poll cycle —
no scheduler of its own.

Authenticity gates (this writes financial rows, so the sender query alone
is not trusted):
- The message must carry ALIGNED authentication: dmarc=pass, or
  dkim=pass/spf=pass whose clause names firststudentinc.com — a spoofed
  From: riding an attacker-domain spf/dkim pass is skipped.
- The advice PDF must contain our First Student supplier number
  (EFT_SUPPLIER_ID, default 2794808).

Dedupe / safety rules (per INVOICE, not per message — one advice can pay
several invoices and their batches upload on different days):
1. EFT_AUTOINGEST=0 short-circuits the whole pass.
2. An invoice line already ingested is skipped. The dedupe key is the
   BUSINESS key "eft:<ach-payment#>:<invoice-ref>" stored in
   partner_payment.external_ref under a partial unique index (s8c) — so a
   re-sent advice email (new Gmail id, same payment#) is still a dupe,
   one payment covering N invoices records N rows, and the cross-replica
   race (every Railway replica runs the scheduler) collapses to an
   IntegrityError that is caught and counted as a dupe.
3. A batch that already has a MANUAL partner_payment row (created_by is
   not this service) is skipped — a human, e.g. mom, entered the deposit;
   never double-count. Auto rows from other advices don't block: a batch
   legitimately paid across two deposits gets two rows (model docstring).
4. An invoice whose service week has no uploaded batch yet is skipped this
   cycle; the 30-day Gmail window means it retries until the batch shows up
   (deposits land Wednesday, batches typically upload the following Monday).
5. Two acumen batches sharing a week_end = ambiguous match → skip + warn,
   never guess which batch gets the money.
6. The advice's own total must equal the sum of its invoice pay-amounts
   (±1¢, compared in integer cents) or the whole message is skipped.

Env vars:
    EFT_AUTOINGEST   master on/off switch, default "1"
    EFT_SUPPLIER_ID  First Student supplier number expected in the PDF,
                     default "2794808"
    (Gmail credentials are shared with inbox_intake — the caller passes a
    minted access token in.)
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests

logger = logging.getLogger("zpay.remit_ingest")

try:
    from backend.services.health_monitor import _push_ntfy as _hm_push_ntfy
except Exception:  # pragma: no cover — health_monitor may not be wired in tests
    _hm_push_ntfy = None  # type: ignore[assignment]

_GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
_HTTP_TIMEOUT = 15

# 30-day window: a deposit whose batch hasn't been uploaded yet keeps
# retrying until the batch arrives (see module docstring, rule 4) — 30d so a
# holiday-delayed batch upload can't silently age the deposit out of reach.
_EFT_QUERY = 'from:firststudentinc.com newer_than:30d subject:"EFT Remittance Advice"'

_MEMO_TAG = "auto-eft"
_CREATED_BY = "inbox-watcher"

_DEFAULT_SUPPLIER_ID = "2794808"

_TOTAL_TOLERANCE_CENTS = 1  # invoice-sum vs advice-total tolerance, integer cents

# ── ACH advice PDF text patterns ─────────────────────────────────────────────
_DEPOSIT_DATE_RE = re.compile(r"available a minimum of.*?from\s+(\d{1,2}/\d{1,2}/\d{4})", re.DOTALL)
_TOTAL_AMOUNT_RE = re.compile(r"funds in the amount of\s+\$\s*([\d,]+\.\d{2})", re.IGNORECASE)
# "1584417 0206202602794808 2/6/2026 22013.25 22013.25 06400 First Student"
#  payment# reference        inv-date  invoiced  PAID
_INVOICE_LINE_RE = re.compile(
    r"^(\d{6,})\s+(\d{10,})\s+(\d{1,2}/\d{1,2}/\d{4})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})",
    re.MULTILINE,
)

# Aligned authentication only (D2): dmarc=pass, or dkim/spf=pass whose SAME
# clause names firststudentinc.com. A bare spf=pass/dkim=pass on an attacker
# domain with a forged From: must NOT count.
_SENDER_DOMAIN = "firststudentinc.com"
_DMARC_PASS_RE = re.compile(r"\bdmarc=pass\b", re.IGNORECASE)
_DKIM_ALIGNED_RE = re.compile(
    r"\bdkim=pass\b[^;]*header\.[id]=@?[\w.-]*" + re.escape(_SENDER_DOMAIN),
    re.IGNORECASE,
)
_SPF_ALIGNED_RE = re.compile(
    r"\bspf=pass\b[^;]*(?:smtp\.mailfrom|smtp\.helo)=@?[\w.-]*" + re.escape(_SENDER_DOMAIN),
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RemitInvoice:
    payment_number: str     # ACH payment number — stable across re-sent emails
    invoice_ref: str        # FS invoice reference (date+supplier encoded)
    service_week_end: date  # FA invoice date = service week end (Friday)
    invoiced_amount: float  # what FS says the invoice was for
    paid_amount: float      # what actually hit the bank — the row amount

    @property
    def external_ref(self) -> str:
        """DB dedupe key (partner_payment.external_ref, unique index s8c).
        payment#+invoice-ref: re-sent email → same key (dupe caught); one
        payment covering N invoices → N distinct keys; a genuine second
        deposit against the same invoice → new payment# → new key."""
        return f"eft:{self.payment_number}:{self.invoice_ref}"


@dataclass(frozen=True)
class RemitAdvice:
    deposit_date: date
    total_amount: float
    invoices: tuple[RemitInvoice, ...]


def _parse_mdy(raw: str) -> date:
    m, d, y = (int(p) for p in raw.split("/"))
    return date(y, m, d)


def _parse_money(raw: str) -> float:
    return round(float(raw.replace(",", "")), 2)


def parse_remit_text(text: str) -> Optional[RemitAdvice]:
    """Parse extracted ACH-advice text. Returns None when the text doesn't
    look like a First Student remittance, or when the invoice pay-amounts
    don't sum to the advice's own total (caller logs and skips)."""
    date_m = _DEPOSIT_DATE_RE.search(text)
    total_m = _TOTAL_AMOUNT_RE.search(text)
    lines = _INVOICE_LINE_RE.findall(text)
    if not (date_m and total_m and lines):
        return None
    try:
        invoices = tuple(
            RemitInvoice(
                payment_number=num,
                invoice_ref=ref,
                service_week_end=_parse_mdy(inv_date),
                invoiced_amount=_parse_money(inv_amt),
                paid_amount=_parse_money(pay_amt),
            )
            for num, ref, inv_date, inv_amt, pay_amt in lines
        )
        total = _parse_money(total_m.group(1))
        # Integer-cents compare — float subtraction turns "exactly 1 cent"
        # into 0.010000000000218 at some magnitudes and rejects it.
        paid_sum_cents = sum(round(i.paid_amount * 100) for i in invoices)
        if abs(paid_sum_cents - round(total * 100)) > _TOTAL_TOLERANCE_CENTS:
            logger.warning(
                "[remit-ingest] advice total $%.2f != invoice pay sum $%.2f — skipping",
                total, paid_sum_cents / 100,
            )
            return None
        return RemitAdvice(
            deposit_date=_parse_mdy(date_m.group(1)),
            total_amount=total,
            invoices=invoices,
        )
    except (ValueError, IndexError) as exc:
        logger.warning("[remit-ingest] advice text parse failed: %s", exc)
        return None


def _pdf_to_text(pdf_bytes: bytes) -> str:
    """Extract text from the ACH advice PDF (single page in practice)."""
    import pdfplumber  # local import — heavy, and mocked in tests

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


# ── Gmail helpers (token is minted by the caller — inbox_intake) ─────────────

def _gmail_get(access_token: str, path: str, params: Optional[dict] = None) -> Optional[dict]:
    try:
        resp = requests.get(
            f"{_GMAIL_BASE}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params or {},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(
                "[remit-ingest] GET %s failed — HTTP %d %s",
                path, resp.status_code, resp.text[:200],
            )
            return None
        return resp.json()
    except Exception as exc:
        logger.warning("[remit-ingest] GET %s raised: %s", path, exc)
        return None


def _list_eft_message_ids(access_token: str) -> list[str]:
    payload = _gmail_get(access_token, "/messages", {"q": _EFT_QUERY})
    if not payload:
        return []
    return [m["id"] for m in payload.get("messages", []) if m.get("id")]


def _message_passes_auth(message: dict) -> bool:
    """Require ALIGNED authentication: dmarc=pass, or dkim=pass/spf=pass whose
    clause names the sender domain. Fail closed: no auth header, or passes
    only on foreign domains, is treated as unauthenticated."""
    headers = (message.get("payload") or {}).get("headers") or []
    for h in headers:
        name = (h.get("name") or "").lower()
        if name in ("authentication-results", "arc-authentication-results"):
            value = h.get("value") or ""
            if (
                _DMARC_PASS_RE.search(value)
                or _DKIM_ALIGNED_RE.search(value)
                or _SPF_ALIGNED_RE.search(value)
            ):
                return True
    return False


def _find_pdf_attachment_id(payload: dict) -> Optional[str]:
    """Depth-first walk for the first PDF attachment part."""
    filename = (payload.get("filename") or "").lower()
    body = payload.get("body") or {}
    if filename.endswith(".pdf") and body.get("attachmentId"):
        return body["attachmentId"]
    for child in payload.get("parts") or []:
        found = _find_pdf_attachment_id(child)
        if found:
            return found
    return None


def _fetch_pdf_bytes(access_token: str, msg_id: str, message: dict) -> Optional[bytes]:
    attachment_id = _find_pdf_attachment_id(message.get("payload") or {})
    if not attachment_id:
        logger.warning("[remit-ingest] message %s has no PDF attachment", msg_id)
        return None
    attachment = _gmail_get(
        access_token, f"/messages/{msg_id}/attachments/{attachment_id}"
    )
    if not attachment or not attachment.get("data"):
        return None
    data = attachment["data"]
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("utf-8"))
    except Exception as exc:
        logger.warning("[remit-ingest] attachment decode failed for %s: %s", msg_id, exc)
        return None


# ── Notification ─────────────────────────────────────────────────────────────

def _push_deposit_summary(recorded: list[dict]) -> None:
    if not recorded:
        return
    parts = []
    for r in recorded:
        delta = r["amount"] - r["expected"]
        verdict = "match" if abs(delta) <= 0.01 else f"Δ ${delta:+,.2f}"
        parts.append(f"${r['amount']:,.2f} → batch {r['batch_id']} ({verdict})")
    body = "Z-Pay: EFT deposit recorded — " + "; ".join(parts)
    try:
        if _hm_push_ntfy is not None:
            _hm_push_ntfy(title="Z-Pay EFT ingest", body=body, priority="default")
    except Exception as exc:
        logger.warning("[remit-ingest] ntfy push failed: %s", exc)


# ── Main pass — called from inbox_intake.run_inbox_intake() ──────────────────

def _is_enabled() -> bool:
    return os.environ.get("EFT_AUTOINGEST", "1").strip() != "0"


def _supplier_id() -> str:
    return os.environ.get("EFT_SUPPLIER_ID", _DEFAULT_SUPPLIER_ID).strip()


def run_remit_ingest(access_token: str) -> dict:
    """One EFT ingest pass. Never raises — mirrors run_inbox_intake's
    contract so a remit failure can never break offer intake."""
    result = {
        "checked": 0,
        "recorded": 0,
        "skipped_dupes": 0,
        "skipped_no_batch": 0,
        "skipped_unauthenticated": 0,
    }
    if not _is_enabled():
        logger.info("[remit-ingest] EFT_AUTOINGEST=0 — skipping pass")
        return result

    recorded_rows: list[dict] = []
    try:
        message_ids = _list_eft_message_ids(access_token)
        result["checked"] = len(message_ids)
        if not message_ids:
            return result

        from sqlalchemy import func
        from sqlalchemy.exc import IntegrityError

        from backend.db.db import SessionLocal
        from backend.db.models import PartnerPayment, PayrollBatch, Ride

        with SessionLocal() as db:
            for msg_id in message_ids:
                try:
                    message = _gmail_get(
                        access_token, f"/messages/{msg_id}", {"format": "full"}
                    )
                    if message is None:
                        continue

                    if not _message_passes_auth(message):
                        result["skipped_unauthenticated"] += 1
                        logger.warning(
                            "[remit-ingest] message %s failed SPF/DKIM — NOT ingesting",
                            msg_id,
                        )
                        continue

                    pdf_bytes = _fetch_pdf_bytes(access_token, msg_id, message)
                    if not pdf_bytes:
                        continue
                    text = _pdf_to_text(pdf_bytes)

                    if _supplier_id() not in text:
                        result["skipped_unauthenticated"] += 1
                        logger.warning(
                            "[remit-ingest] message %s: PDF missing supplier id — NOT ingesting",
                            msg_id,
                        )
                        continue

                    advice = parse_remit_text(text)
                    if advice is None:
                        logger.warning("[remit-ingest] message %s: unparseable advice", msg_id)
                        continue

                    for inv in advice.invoices:
                        invoice_tag = f"msg {msg_id} | pmt {inv.payment_number}"

                        # Rule 2: per-invoice-line dedupe on the business key —
                        # exact match, survives re-sent emails, and the s8c
                        # unique index is the real cross-replica guarantee.
                        already = (
                            db.query(PartnerPayment.partner_payment_id)
                            .filter(PartnerPayment.external_ref == inv.external_ref)
                            .first()
                        )
                        if already:
                            result["skipped_dupes"] += 1
                            continue

                        # Rule 5: ambiguous week_end match — never guess.
                        batches = (
                            db.query(PayrollBatch)
                            .filter(
                                PayrollBatch.source == "acumen",
                                PayrollBatch.week_end == inv.service_week_end,
                            )
                            .all()
                        )
                        if not batches:
                            result["skipped_no_batch"] += 1
                            logger.info(
                                "[remit-ingest] %s: no acumen batch for week end %s "
                                "— will retry next cycle",
                                invoice_tag, inv.service_week_end,
                            )
                            continue
                        if len(batches) > 1:
                            result["skipped_no_batch"] += 1
                            logger.warning(
                                "[remit-ingest] %s: %d acumen batches share week end %s "
                                "— ambiguous, record the deposit manually",
                                invoice_tag, len(batches), inv.service_week_end,
                            )
                            continue
                        batch = batches[0]

                        # Rule 3: a manual row on this batch wins — never
                        # double-count a human-entered deposit.
                        manual_row = (
                            db.query(PartnerPayment.partner_payment_id)
                            .filter(
                                PartnerPayment.payroll_batch_id == batch.payroll_batch_id,
                                func.coalesce(PartnerPayment.created_by, "") != _CREATED_BY,
                            )
                            .first()
                        )
                        if manual_row:
                            result["skipped_dupes"] += 1
                            continue

                        expected = float(
                            db.query(func.coalesce(func.sum(Ride.net_pay), 0))
                            .filter(Ride.payroll_batch_id == batch.payroll_batch_id)
                            .scalar()
                            or 0
                        )
                        payment = PartnerPayment(
                            source="acumen",
                            amount=inv.paid_amount,
                            deposit_date=advice.deposit_date,
                            payroll_batch_id=batch.payroll_batch_id,
                            external_ref=inv.external_ref,
                            memo=(
                                f"{_MEMO_TAG} | {invoice_tag} "
                                f"| wk-end {inv.service_week_end.isoformat()}"
                            ),
                            created_by=_CREATED_BY,
                        )
                        db.add(payment)
                        try:
                            db.commit()
                        except IntegrityError:
                            # Another replica won the race on the s8c unique
                            # index between our SELECT and this commit.
                            db.rollback()
                            result["skipped_dupes"] += 1
                            logger.info(
                                "[remit-ingest] %s: lost insert race to another "
                                "replica — treated as dupe", inv.external_ref,
                            )
                            continue
                        result["recorded"] += 1
                        recorded_rows.append(
                            {
                                "amount": inv.paid_amount,
                                "batch_id": batch.payroll_batch_id,
                                "expected": expected,
                            }
                        )
                except Exception as exc:
                    # One bad message must never kill the pass. Committed
                    # invoices stay; uncommitted work rolls back and the
                    # per-invoice dedupe lets the rest retry next cycle.
                    db.rollback()
                    logger.warning("[remit-ingest] failed on message %s: %s", msg_id, exc)
                    continue

        _push_deposit_summary(recorded_rows)
    except Exception as exc:
        # Belt-and-suspenders — no exception may escape this pass.
        logger.error("[remit-ingest] pass crashed: %s", exc)

    logger.info("[remit-ingest] pass complete: %s", result)
    return result
