"""S12 paychex_api_check — staged-check ledger for the Paychex External API rail.

Revision ID: s12_paychex_api_check
Revises: s11_paychex_job_mfa
Create Date: 2026-09-16

Rationale (docs/PAYCHEX-API-RAIL-PLAN-2026-09-16.md):
  Replaces the Playwright pay-entry bot with the official Paychex Flex
  External API. POST /companies/{companyId}/checks stages one check per
  driver into an open pay period — a human still opens Flex to submit
  payroll (no submit/release endpoint exists in the API). This table is the
  ledger of what got staged (or failed) per (batch, person), and is also the
  idempotency guard that stops a batch's checks from being staged twice.

Online-safe: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS on a
new table only. Fully reversible.
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "s12_paychex_api_check"
down_revision: Union[str, None] = "s11_paychex_job_mfa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS paychex_api_check (
            id                  SERIAL PRIMARY KEY,
            payroll_batch_id    INTEGER NOT NULL REFERENCES payroll_batch(payroll_batch_id) ON DELETE CASCADE,
            person_id           INTEGER NOT NULL REFERENCES person(person_id) ON DELETE CASCADE,
            company             TEXT NOT NULL,
            worker_id           TEXT NOT NULL,
            pay_period_id       TEXT NOT NULL,
            paycheck_id         TEXT,
            amount              NUMERIC(12,2) NOT NULL,
            status              TEXT NOT NULL,
            error               TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_paychex_api_check_batch_person
            ON paychex_api_check (payroll_batch_id, person_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS paychex_api_check")
