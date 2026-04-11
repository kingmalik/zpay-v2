"""
Add invite_token and personal_info to onboarding_record.

invite_token — unique URL token for driver self-onboarding portal
personal_info — JSONB field for driver-submitted personal data

Revision ID: v1w2x3y4z5a6
Revises: u1v2w3x4y5z6
Create Date: 2026-04-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "v1w2x3y4z5a6"
down_revision: Union[str, None] = "u1v2w3x4y5z6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add invite_token column — unique, nullable, VARCHAR(64) with index
    op.add_column(
        "onboarding_record",
        sa.Column("invite_token", sa.String(64), nullable=True),
    )
    op.create_index(
        "uq_onboarding_record_invite_token",
        "onboarding_record",
        ["invite_token"],
        unique=True,
    )

    # Add personal_info column — JSON, nullable
    op.add_column(
        "onboarding_record",
        sa.Column("personal_info", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("onboarding_record", "personal_info")
    op.drop_index("uq_onboarding_record_invite_token", table_name="onboarding_record")
    op.drop_column("onboarding_record", "invite_token")
