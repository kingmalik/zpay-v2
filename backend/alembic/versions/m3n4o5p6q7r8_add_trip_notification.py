"""
add trip_notification table

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-04-06 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "m3n4o5p6q7r8"
down_revision: Union[str, Sequence[str], None] = "l2m3n4o5p6q7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "trip_notification",
        sa.Column("id",                   sa.Integer,  primary_key=True, autoincrement=True),
        sa.Column("person_id",            sa.Integer,  sa.ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False),
        sa.Column("trip_date",            sa.Date,     nullable=False),
        sa.Column("source",              sa.Text,     nullable=False),
        sa.Column("trip_ref",            sa.Text,     nullable=False),
        sa.Column("trip_status",         sa.Text,     nullable=True),
        sa.Column("pickup_time",         sa.Text,     nullable=True),
        # Accept stage
        sa.Column("accept_sms_at",       sa.DateTime(timezone=True), nullable=True),
        sa.Column("accept_call_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("accept_escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at",         sa.DateTime(timezone=True), nullable=True),
        # Start stage
        sa.Column("start_sms_at",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_call_at",       sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_escalated_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at",          sa.DateTime(timezone=True), nullable=True),
        # Timestamps
        sa.Column("created_at",          sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("uq_trip_notification_ref", "trip_notification", ["source", "trip_ref", "trip_date"], unique=True)
    op.create_index("ix_trip_notification_date", "trip_notification", ["trip_date"])
    op.create_index("ix_trip_notification_person", "trip_notification", ["person_id"])


def downgrade():
    op.drop_index("ix_trip_notification_person", table_name="trip_notification")
    op.drop_index("ix_trip_notification_date", table_name="trip_notification")
    op.drop_index("uq_trip_notification_ref", table_name="trip_notification")
    op.drop_table("trip_notification")
