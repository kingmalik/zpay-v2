"""batch_rate_decision — the operator's per-route / per-ride choice on the
negative-margin table, so it survives leaving the workflow page.

Revision ID: s13_batch_rate_decision
Revises: s12_paychex_api_check
Create Date: 2026-09-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s13_batch_rate_decision"
down_revision: Union[str, None] = "s12_paychex_api_check"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "batch_rate_decision",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("payroll_batch_id", sa.Integer(), sa.ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("ride_id", sa.Integer(), sa.ForeignKey("ride.ride_id", ondelete="CASCADE"), nullable=True),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("z_rate", sa.Numeric(12, 2), nullable=True),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_batch_rate_decision_batch", "batch_rate_decision", ["payroll_batch_id"])
    # One route-level row per (batch, route); one ride-level row per (batch, ride).
    op.create_index(
        "uq_batch_rate_decision_route", "batch_rate_decision", ["payroll_batch_id", "service_name"],
        unique=True, postgresql_where=sa.text("ride_id IS NULL"),
    )
    op.create_index(
        "uq_batch_rate_decision_ride", "batch_rate_decision", ["payroll_batch_id", "ride_id"],
        unique=True, postgresql_where=sa.text("ride_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_batch_rate_decision_ride", table_name="batch_rate_decision")
    op.drop_index("uq_batch_rate_decision_route", table_name="batch_rate_decision")
    op.drop_index("ix_batch_rate_decision_batch", table_name="batch_rate_decision")
    op.drop_table("batch_rate_decision")
