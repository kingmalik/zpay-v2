"""Phase 2 — operator overrides + audit log

Revision ID: ze5f6g7h8i9j
Revises: zd4e5f6g7h8i9
Create Date: 2026-04-30 14:30:00.000000

Phase 2 of the dispatch + caller overhaul. Adds operator override controls
so Malik can mute a driver's admin alerts, snooze a specific notification,
or manually resolve it from the monitor UI. Also adds a full audit log so
every escalation, snooze, mute, resolve, and dedup is permanently recorded.

Changes:
  1. Person.alert_profile — nullable JSONB column
       Shape: {"muted_until": "2026-05-01T00:00:00Z" | null,
               "muted_reason": str | null}
       Null means no mute. Driver-facing SMS is never affected.

  2. TripNotification — four new nullable TIMESTAMPTZ/INT columns:
       snoozed_until        — monitor skips re-escalation while now < this
       manually_resolved_at — operator "Got it" — stops all further escalation
       manually_resolved_by — person_id FK (nullable for backwards compat)
       last_escalated_at    — bumped each time the stuck-trip re-escalation fires

  3. TripNotification — two new boolean/int columns for cross-source dedup:
       dedup_suppressed         — true when suppressed in favour of another notif
       dedup_primary_notif_id   — FK-like pointer to the canonical notif row

  4. New table: notification_event
       Immutable audit log. One row per action (SMS sent, call made, snoozed,
       resolved, muted, deduped, re-escalated, WhatsApp delivered/failed, etc.)

Fully reversible via downgrade().
"""
from typing import Union, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ze5f6g7h8i9j"
down_revision: Union[str, Sequence[str], None] = "zd4e5f6g7h8i9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Person.alert_profile ──────────────────────────────────────────────
    op.add_column(
        "person",
        sa.Column("alert_profile", sa.JSON(), nullable=True),
    )

    # ── 2 + 3. TripNotification override + dedup columns ────────────────────
    op.add_column(
        "trip_notification",
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "trip_notification",
        sa.Column("manually_resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "trip_notification",
        sa.Column("manually_resolved_by", sa.Integer(), nullable=True),
    )
    op.add_column(
        "trip_notification",
        sa.Column("last_escalated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "trip_notification",
        sa.Column(
            "dedup_suppressed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "trip_notification",
        sa.Column("dedup_primary_notif_id", sa.Integer(), nullable=True),
    )

    # ── 4. notification_event table ──────────────────────────────────────────
    op.create_table(
        "notification_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "trip_notification_id",
            sa.Integer(),
            sa.ForeignKey("trip_notification.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Event type — text column for flexibility; validated at app layer.
        # Valid values: sms_sent, sms_delivered, sms_failed,
        #   whatsapp_sent, whatsapp_delivered, whatsapp_failed,
        #   voice_call_admin, snoozed, unmuted, manually_resolved,
        #   auto_escalated, stuck_trip_alert, accept_sms, accept_call,
        #   accept_escalated, start_sms, start_call, start_escalated,
        #   overdue_alert, mute, dedup_suppressed, reescalated
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("created_by_person_id", sa.Integer(), nullable=True),
    )

    op.create_index(
        "ix_notification_event_notif",
        "notification_event",
        ["trip_notification_id"],
    )
    op.create_index(
        "ix_notification_event_type",
        "notification_event",
        ["event_type"],
    )
    op.create_index(
        "ix_notification_event_created",
        "notification_event",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_event_created", table_name="notification_event")
    op.drop_index("ix_notification_event_type", table_name="notification_event")
    op.drop_index("ix_notification_event_notif", table_name="notification_event")
    op.drop_table("notification_event")

    op.drop_column("trip_notification", "dedup_primary_notif_id")
    op.drop_column("trip_notification", "dedup_suppressed")
    op.drop_column("trip_notification", "last_escalated_at")
    op.drop_column("trip_notification", "manually_resolved_by")
    op.drop_column("trip_notification", "manually_resolved_at")
    op.drop_column("trip_notification", "snoozed_until")

    op.drop_column("person", "alert_profile")
