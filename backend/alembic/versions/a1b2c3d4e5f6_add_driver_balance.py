"""
add driver_balance table

Revision ID: a1b2c3d4e5f6
Revises: 348ee4aac5d1
Create Date: 2026-03-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "348ee4aac5d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "driver_balance",
        sa.Column("driver_balance_id", sa.Integer, primary_key=True),
        sa.Column(
            "person_id",
            sa.Integer,
            sa.ForeignKey("person.person_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "payroll_batch_id",
            sa.Integer,
            sa.ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "carried_over",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            onupdate=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "uq_driver_balance_person_batch",
        "driver_balance",
        ["person_id", "payroll_batch_id"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_driver_balance_person_batch", table_name="driver_balance")
    op.drop_table("driver_balance")
