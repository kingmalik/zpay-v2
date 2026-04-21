"""add batch_correction_log table

Revision ID: ab1b2c3d4e5f6
Revises: a6b7c8d9e0f1
Create Date: 2026-04-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ab1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "batch_correction_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.Integer, sa.ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.Integer, sa.ForeignKey("person.person_id", ondelete="SET NULL"), nullable=True),
        sa.Column("field", sa.Text, nullable=False),
        sa.Column("old_value", sa.Text, nullable=True),
        sa.Column("new_value", sa.Text, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("corrected_by", sa.Text, nullable=False, server_default="user"),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_batch_correction_batch", "batch_correction_log", ["batch_id"])
    op.create_index("ix_batch_correction_person", "batch_correction_log", ["person_id"])


def downgrade() -> None:
    op.drop_index("ix_batch_correction_person")
    op.drop_index("ix_batch_correction_batch")
    op.drop_table("batch_correction_log")
