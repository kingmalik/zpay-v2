"""
Add workflow status tracking to payroll_batch and create batch_workflow_log table.

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-04-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "o5p6q7r8s9t0"
down_revision: Union[str, Sequence[str], None] = "n4o5p6q7r8s9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Add status and paychex_exported_at to payroll_batch
    op.add_column("payroll_batch", sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'uploaded'")))
    op.add_column("payroll_batch", sa.Column("paychex_exported_at", sa.DateTime(timezone=True), nullable=True))

    # Backfill: finalized batches → 'complete', others → 'uploaded'
    op.execute("UPDATE payroll_batch SET status = 'complete' WHERE finalized_at IS NOT NULL")
    op.execute("UPDATE payroll_batch SET status = 'uploaded' WHERE finalized_at IS NULL")

    # Create batch_workflow_log table
    op.create_table(
        "batch_workflow_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("payroll_batch_id", sa.Integer(), sa.ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("triggered_by", sa.Text(), nullable=False, server_default=sa.text("'system'")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_batch_workflow_log_batch", "batch_workflow_log", ["payroll_batch_id"])


def downgrade():
    op.drop_table("batch_workflow_log")
    op.drop_column("payroll_batch", "paychex_exported_at")
    op.drop_column("payroll_batch", "status")
