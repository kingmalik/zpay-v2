"""add soft-delete columns to ride table

Revision ID: zx3y4z5a6b7c
Revises: zw2x3y4z5a6b
Create Date: 2026-05-21

Rationale:
  Admin needs to be able to remove a single back-pay / reconciliation line
  from a driver's paystub without a direct DB edit. Soft-delete keeps the
  ride row (preserving revenue numbers) while flagging it as excluded from
  driver payout calculations and the emailed paystub PDF.

  Three audit columns are added to the ride table:
    removed_at     — UTC timestamp when admin removed the ride
    removed_by     — username of the admin who removed it
    removed_reason — free-text reason (e.g. "already paid W17")

  A removed ride (removed_at IS NOT NULL) must be:
    - Excluded from ALL driver payout sums (z_rate)
    - Excluded from the emailed paystub PDF
    - Visually marked as removed on the admin paystub UI (audit trail)
    - NOT deleted — the ride row stays so revenue numbers remain intact
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────────
revision: str = "zx3y4z5a6b7c"
down_revision: Union[str, None] = "zw2x3y4z5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ride", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ride", sa.Column("removed_by", sa.Text(), nullable=True))
    op.add_column("ride", sa.Column("removed_reason", sa.Text(), nullable=True))

    # Partial index — only indexes rows where removed_at IS NULL (the active set).
    # This is the performance-critical path: nearly all rides are active, so the
    # index stays small and payout queries (WHERE removed_at IS NULL) hit it directly.
    op.create_index(
        "ix_ride_removed_at_null", "ride", ["removed_at"],
        postgresql_where=sa.text("removed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_ride_removed_at_null", table_name="ride")
    op.drop_column("ride", "removed_reason")
    op.drop_column("ride", "removed_by")
    op.drop_column("ride", "removed_at")
