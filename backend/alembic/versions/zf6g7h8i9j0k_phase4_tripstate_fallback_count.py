"""Phase 4 — tripstate_fallback_count on trip_notification

Revision ID: zf6g7h8i9j0k
Revises: ze5f6g7h8i9j
Create Date: 2026-04-30 17:00:00.000000

Phase 4 of the dispatch + caller overhaul. Adds a counter column on
trip_notification so the trip monitor can track how many times a driver's
run needed the per-trip tripState fallback (i.e. the driver never tapped
"At Pickup" in the ED app but the individual trip showed Active/OnBoard).

Drivers with a high cumulative count across the week are surfaced on the
/dispatch/reliability page as "chronic non-tappers" so Malik can train or
mute them proactively.

Changes:
  1. trip_notification.tripstate_fallback_count — INTEGER NOT NULL DEFAULT 0
       Incremented each cycle by trip_monitor._run_cycle_inner when
       any_trip_progressing=True causes the bucket to be promoted from
       "accepted" to "started". Safe backfill: existing rows stay 0.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "zf6g7h8i9j0k"
down_revision = "ze5f6g7h8i9j"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trip_notification",
        sa.Column(
            "tripstate_fallback_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("trip_notification", "tripstate_fallback_count")
