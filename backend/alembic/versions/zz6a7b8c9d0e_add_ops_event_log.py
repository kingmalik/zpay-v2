"""add_ops_event_log

Revision ID: zz6a7b8c9d0e
Revises: zy5z6a7b8c9d
Create Date: 2026-05-28

Rationale:
  Discord webhook is being removed from ops_alert.py per owner decision
  (no outside chat apps). The Discord channel had served as the permanent
  paper trail for every dispatch event regardless of severity tier.

  Replace it with a first-class internal table:
    - Same paper-trail role (every alert writes a row)
    - Queryable from /ops/live as a scrollable timeline
    - Decouples ops audit from any external service

  Columns:
    severity      Tier this event was routed at (critical/urgent/normal/silent)
    title         Short headline as it appeared in the alert
    message       Full alert body
    trip_id       Foreign-ish reference to the trip when applicable.
                  Not a hard FK because trip_id origin spans FA + ED and the
                  trip_status_event table key isn't always populated at alert
                  time (race with monitor cycle).
    notif_id      Optional pointer to trip_notification.id for join queries.
    source        Free-text origin (e.g. "trip_monitor", "agent",
                  "manual_test"). Helps debugging.
    created_at    NOW() default.

  Indexes:
    ix_ops_event_log_created_at — drives the timeline query
                                  (ORDER BY created_at DESC LIMIT 100)
    ix_ops_event_log_severity   — filter by tier
    ix_ops_event_log_trip       — partial index, NOT NULL trip_id only

  Online-safe: new table, no FK rewrites.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────────
revision: str = "zz6a7b8c9d0e"
down_revision: Union[str, None] = "zy5z6a7b8c9d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ops_event_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("trip_id", sa.Text(), nullable=True),
        sa.Column("notif_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_ops_event_log_created_at",
        "ops_event_log",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ops_event_log_severity",
        "ops_event_log",
        ["severity"],
        unique=False,
    )
    op.create_index(
        "ix_ops_event_log_trip",
        "ops_event_log",
        ["trip_id"],
        unique=False,
        postgresql_where=sa.text("trip_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_ops_event_log_trip", table_name="ops_event_log")
    op.drop_index("ix_ops_event_log_severity", table_name="ops_event_log")
    op.drop_index("ix_ops_event_log_created_at", table_name="ops_event_log")
    op.drop_table("ops_event_log")
