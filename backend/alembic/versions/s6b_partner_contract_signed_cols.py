"""onboarding_record — internal e-sign columns for the partner (Acumen) contract

Revision ID: s6b_partner_contract_signed_cols
Revises: s6a_automation_live_default_true
Create Date: 2026-07-22

Rationale (MASTER-PLAN S6 — onboarding repair, item 6):
  The partner-contract path (step 7, contract_status) wanted a paid
  ADOBE_SIGN_INTEGRATION_KEY and fell back to "manual" (admin sends the
  contract by hand via email) whenever that key wasn't set — which is
  always, today (no ADOBE_SIGN_INTEGRATION_KEY on Railway). Decision: route
  this contract through the same internal typed-name e-sign flow already
  used for the Maz contract (maz_contract_signed_name/_at), instead of
  paying for Adobe. These are separate, new, additive columns rather than
  reusing maz_contract_signed_name/_at directly — the two contracts (partner
  vs Maz) are legally distinct and must not share a signature record.

Online-safe:
  - ADD COLUMN ... NULL — metadata-only in Postgres, no table rewrite.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "s6b_partner_contract_signed_cols"
down_revision = "s6a_automation_live_default_true"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "onboarding_record",
        sa.Column("contract_signed_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "onboarding_record",
        sa.Column("contract_signed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("onboarding_record", "contract_signed_at")
    op.drop_column("onboarding_record", "contract_signed_name")
