"""add_scheduled_dropoff_to_trip_notification

Revision ID: zy4z5a6b7c8d
Revises: zx3y4z5a6b7c
Create Date: 2026-05-14

Rationale:
  The on_time_completion scorecard axis was disabled because trip_notification
  had no column to store a scheduled dropoff time.  EverDriven's runsV2 API
  returns lastDropoff.dueTimeTLT (local-time string, same shape as firstPickup)
  for every run.  FirstAlt does not expose a scheduled dropoff in its
  /v1/transportation-partner-trips response.

  This migration adds the column so trip_monitor can persist the ED value at
  poll time and the scorecard can compare completed_at against it to determine
  whether a trip finished on time.

  Column contract:
    - Nullable DateTime(timezone=True) — NULL for FA trips (partner doesn't
      provide the field) and for any ED trip whose lastDropoff is absent/blank.
    - Written once at TripNotification upsert time; never overwritten (the
      scheduled dropoff is fixed at dispatch time and doesn't change mid-run).
    - on_time_completion axis: trip is on-time when
          completed_at <= scheduled_dropoff + 5-minute grace
      Trips where scheduled_dropoff IS NULL are excluded from the axis sample
      rather than counted as late or on-time.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────────
revision: str = "zy4z5a6b7c8d"
down_revision: Union[str, None] = "zx3y4z5a6b7c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trip_notification",
        sa.Column(
            "scheduled_dropoff",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("trip_notification", "scheduled_dropoff")
