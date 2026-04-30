"""add original_pickup_dt to trip_notification

Revision ID: zd4e5f6g7h8i9
Revises: zc3d4e5f6g7h8
Create Date: 2026-04-29 14:00:00.000000

Adds a nullable timestamptz column `original_pickup_dt` to trip_notification.
This column is set once when `accept_sms_at` is first written for a trip.
If the pickup time is later rescheduled EARLIER than this value, the monitor
suppresses SMS re-fire to avoid double-texting drivers.

Fully reversible: downgrade drops the column.
"""
from typing import Union, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "zd4e5f6g7h8i9"
down_revision: Union[str, Sequence[str], None] = "zc3d4e5f6g7h8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trip_notification",
        sa.Column(
            "original_pickup_dt",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("trip_notification", "original_pickup_dt")
