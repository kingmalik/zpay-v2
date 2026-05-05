"""add sp_file_bytes to payroll_batch

Revision ID: zo3p4q5r6s7t
Revises: zn2o3p4q5r6s
Create Date: 2026-05-05

Stores the raw FA xlsx bytes on the payroll_batch row so the export route
can return the original file as-is (passthrough) without re-generating it
from scratch. Nullable — older batches uploaded before this migration will
have NULL and the export route must fall back to the legacy builder.
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "zo3p4q5r6s7t"
down_revision: Union[str, None] = "zn2o3p4q5r6s"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payroll_batch",
        sa.Column("sp_file_bytes", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payroll_batch", "sp_file_bytes")
