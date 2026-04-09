"""
Add driver_promise and driver_blackout tables.

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-04-09
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "r8s9t0u1v2w3"
down_revision: Union[str, None] = "q7r8s9t0u1v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "driver_promise",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("promised_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fulfilled_ride_ref", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_driver_promise_person", "driver_promise", ["person_id"])

    op.create_table(
        "driver_blackout",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("recurring", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("recurring_days", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_driver_blackout_person", "driver_blackout", ["person_id"])
    op.create_index("ix_driver_blackout_dates", "driver_blackout", ["start_date", "end_date"])


def downgrade() -> None:
    op.drop_index("ix_driver_blackout_dates", table_name="driver_blackout")
    op.drop_index("ix_driver_blackout_person", table_name="driver_blackout")
    op.drop_table("driver_blackout")
    op.drop_index("ix_driver_promise_person", table_name="driver_promise")
    op.drop_table("driver_promise")
