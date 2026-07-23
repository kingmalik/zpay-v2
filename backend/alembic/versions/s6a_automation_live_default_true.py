"""onboarding_record.automation_live — default flips to true for NEW rows only

Revision ID: s6a_automation_live_default_true
Revises: s34_pricing_v2
Create Date: 2026-07-22

Rationale (MASTER-PLAN S6 — onboarding repair, item 3):
  automation_live has defaulted to false since it was introduced
  (ac1b2c3d4e5f6_add_onboarding_automation.py). That means the
  compliance-sync-driven automation (onboarding_automation.check_and_advance,
  called from firstalt_compliance.sync_driver_compliance) never actually
  fires for any driver unless someone hits the /automation/toggle endpoint
  by hand — so onboarding automation has been effectively opt-in-only and
  silently dormant for the fleet.

  Decision: flip the column DEFAULT to true so every NEWLY CREATED hire
  record gets automation on from day one. Existing rows are untouched —
  ALTER COLUMN ... SET DEFAULT only changes what gets applied on future
  INSERTs that don't specify a value; it does not rewrite any existing row.
  (The DB has live driver data — an UPDATE here was explicitly out of scope.)

Online-safe:
  - ALTER COLUMN ... SET DEFAULT is a metadata-only change in Postgres.
    No table rewrite, no lock beyond a brief catalog update.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "s6a_automation_live_default_true"
down_revision = "s34_pricing_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "onboarding_record",
        "automation_live",
        server_default=sa.text("true"),
    )


def downgrade():
    op.alter_column(
        "onboarding_record",
        "automation_live",
        server_default=sa.text("false"),
    )
