"""add fadv and cc_invite fields to onboarding_record

Revision ID: aa2b3c4d5e6f
Revises: z5a6b7c8d9e0
Create Date: 2026-04-30

Adds First Advantage BGC tracking fields to onboarding_record.
Also adds contractor_compliance_invite_sent_at for the ED CC invite step.
No columns removed — safe for live driver data.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "aa2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "z5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # First Advantage BGC tracking
    op.add_column(
        "onboarding_record",
        sa.Column("fadv_report_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "onboarding_record",
        sa.Column("fadv_status", sa.Text(), nullable=True),  # pending | initiated | clear | consider | suspended
    )
    op.add_column(
        "onboarding_record",
        sa.Column("fadv_initiated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "onboarding_record",
        sa.Column("fadv_result_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "onboarding_record",
        sa.Column("fadv_raw", sa.JSON(), nullable=True),  # store raw FADV response for audit
    )
    # Contractor Compliance invite tracking (ED step 1)
    op.add_column(
        "onboarding_record",
        sa.Column("cc_invite_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_onboarding_fadv_report_id",
        "onboarding_record",
        ["fadv_report_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_onboarding_fadv_report_id", table_name="onboarding_record")
    op.drop_column("onboarding_record", "cc_invite_sent_at")
    op.drop_column("onboarding_record", "fadv_raw")
    op.drop_column("onboarding_record", "fadv_result_at")
    op.drop_column("onboarding_record", "fadv_initiated_at")
    op.drop_column("onboarding_record", "fadv_status")
    op.drop_column("onboarding_record", "fadv_report_id")
