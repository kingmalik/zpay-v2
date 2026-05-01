"""Add dispatch_severity to trip_notification

Revision ID: zg7h8i9j0k1l
Revises: zf6g7h8i9j0k
Create Date: 2026-05-01 14:00:00.000000

Phase 3 — severity tiers + per-tier delivery routing.

Adds a `dispatch_severity` column to trip_notification so each persisted
notification record carries the severity tier that was assigned when the
alert fired.  Enum values: critical | urgent | normal | silent.
Default: normal.

Backfills all existing rows to 'normal' (safe — they were all treated
as the middle tier before this migration existed).

Reversible: downgrade drops the column.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "zg7h8i9j0k1l"
down_revision = "zf6g7h8i9j0k"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trip_notification",
        sa.Column(
            "dispatch_severity",
            sa.Text(),
            nullable=False,
            server_default="normal",
        ),
    )


def downgrade() -> None:
    op.drop_column("trip_notification", "dispatch_severity")
