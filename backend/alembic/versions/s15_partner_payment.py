"""add_partner_payment_table

Revision ID: s15_partner_payment
Revises: s1b_email_sent_idx
Create Date: 2026-07-08

Rationale:
  S1.5 partner-payment reconciliation. FA TPA (June 2026) §6b: payment
  disputes must be written within 14 DAYS of payment or the claim is
  waived — which makes recording every partner deposit and diffing it
  against expected batch revenue contract-mandatory, not optional.

  partner_payment holds one row per deposit (a deposit spanning two
  batches is recorded as two rows). Reconciliation status and the
  dispute clock are derived at read time by
  backend/services/partner_reconciliation.py — no denormalized status
  column to drift.

  Online-safe:
    - CREATE TABLE IF NOT EXISTS guards re-runs.
    - New table, no locks on existing tables.
    - Fully reversible via downgrade().
"""

from __future__ import annotations

from typing import Union

from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────────
revision: str = "s15_partner_payment"
down_revision: Union[str, None] = "s1b_email_sent_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS partner_payment (
            partner_payment_id SERIAL PRIMARY KEY,
            source             TEXT NOT NULL,
            amount             NUMERIC(12, 2) NOT NULL,
            deposit_date       DATE NOT NULL,
            payroll_batch_id   INTEGER REFERENCES payroll_batch(payroll_batch_id)
                                   ON DELETE SET NULL,
            memo               TEXT,
            disputed_at        TIMESTAMPTZ,
            dispute_note       TEXT,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by         TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_partner_payment_batch"
        " ON partner_payment (payroll_batch_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_partner_payment_date"
        " ON partner_payment (deposit_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS partner_payment")
