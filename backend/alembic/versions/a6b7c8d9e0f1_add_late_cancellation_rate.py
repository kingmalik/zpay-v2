"""add late_cancellation_rate to z_rate_service

Revision ID: a6b7c8d9e0f1
Revises: aa1b2c3d4e5f6
Create Date: 2026-04-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, Sequence[str], None] = "aa1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "z_rate_service",
        sa.Column("late_cancellation_rate", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("z_rate_service", "late_cancellation_rate")
