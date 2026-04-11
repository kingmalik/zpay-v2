"""
Add training_status to onboarding_record.

training_status — tracks driver training/class completion step.
Possible values: pending | complete | manual | skipped

The monitor auto-detects training completion via the FirstAlt driver profile.
If no clear training field is found, status falls back to 'manual' for admin
to mark done via POST /onboarding/{id}/mark-training-complete.

Revision ID: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
Create Date: 2026-04-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "w2x3y4z5a6b7"
down_revision: Union[str, None] = "v1w2x3y4z5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "onboarding_record",
        sa.Column(
            "training_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
    )


def downgrade() -> None:
    op.drop_column("onboarding_record", "training_status")
