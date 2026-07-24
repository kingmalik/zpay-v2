"""ride_intake — source_msg_id for inbox auto-intake dedupe

Revision ID: s8b_intake_source_msg
Revises: s7_driver_certification
Create Date: 2026-07-23

Rationale (inbox auto-intake watcher):
  The new inbox_intake background job (backend/services/inbox_intake.py)
  polls the business Gmail inbox and auto-creates ride_intake draft rows
  from FirstStudent "New Trip"/"New Route" emails before anyone opens them.
  source_msg_id stores the Gmail message id so re-running the poll never
  creates a second draft row for the same email. NULL for every row created
  through the existing manual /api/data/assignment/intake endpoint (only
  the watcher populates this column) — the partial unique index therefore
  only constrains watcher-created rows, never manual ones.

Online-safe:
  - ADD COLUMN ... NULL — metadata-only in Postgres, no table rewrite.
  - Partial UNIQUE index (WHERE source_msg_id IS NOT NULL) — built on a
    brand-new, all-NULL column, so it's instant regardless of table size.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "s8b_intake_source_msg"
down_revision = "s7_driver_certification"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ride_intake",
        sa.Column("source_msg_id", sa.Text(), nullable=True),
    )
    op.create_index(
        "ux_ride_intake_source_msg_id",
        "ride_intake",
        ["source_msg_id"],
        unique=True,
        postgresql_where=sa.text("source_msg_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("ux_ride_intake_source_msg_id", table_name="ride_intake")
    op.drop_column("ride_intake", "source_msg_id")
