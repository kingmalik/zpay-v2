"""add trip_status_event table and derived timestamp cols on trip_notification

Revision ID: ze1f2g3h4i5j6
Revises: zd4e5f6g7h8i9
Create Date: 2026-04-30 14:00:00.000000

Phase 1 of driver scorecard build.

New table: trip_status_event
  Append-only log of partner-status transitions detected by the polling loop.
  One row per transition, per trip poll cycle that observes a state change.

New columns on trip_notification:
  arrived_at_pickup  TIMESTAMPTZ NULL  — derived from first 'arrived'/'at_stop' transition
  completed_at       TIMESTAMPTZ NULL  — derived from first 'completed' transition

Fully reversible: downgrade drops the table and the two columns.
"""
from typing import Union, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ze1f2g3h4i5j6"
down_revision: Union[str, Sequence[str], None] = "zd4e5f6g7h8i9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── New columns on trip_notification ──────────────────────────────────
    op.add_column(
        "trip_notification",
        sa.Column("arrived_at_pickup", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "trip_notification",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── New table: trip_status_event ──────────────────────────────────────
    op.create_table(
        "trip_status_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "trip_notification_id",
            sa.Integer(),
            sa.ForeignKey("trip_notification.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),          # 'firstalt' | 'everdriven'
        sa.Column("trip_ref", sa.Text(), nullable=False),
        sa.Column(
            "person_id",
            sa.Integer(),
            sa.ForeignKey("person.person_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prev_status", sa.Text(), nullable=True),      # classified status before
        sa.Column("new_status", sa.Text(), nullable=False),      # classified status after
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=True),  # staleness bound
        sa.Column("raw_partner_status", sa.Text(), nullable=True),        # raw API value
    )

    # Indexes
    op.create_index(
        "ix_trip_status_event_person_detected",
        "trip_status_event",
        ["person_id", sa.text("detected_at DESC")],
    )
    op.create_index(
        "ix_trip_status_event_trip",
        "trip_status_event",
        ["trip_notification_id", sa.text("detected_at")],
    )


def downgrade() -> None:
    op.drop_index("ix_trip_status_event_trip", table_name="trip_status_event")
    op.drop_index("ix_trip_status_event_person_detected", table_name="trip_status_event")
    op.drop_table("trip_status_event")
    op.drop_column("trip_notification", "completed_at")
    op.drop_column("trip_notification", "arrived_at_pickup")
