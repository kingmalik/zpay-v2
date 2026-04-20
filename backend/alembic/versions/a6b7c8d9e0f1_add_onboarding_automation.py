"""add onboarding automation columns

Revision ID: a6b7c8d9e0f1
Revises: z5a6b7c8d9e0
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = "a6b7c8d9e0f1"
down_revision = "z5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("onboarding_record", sa.Column(
        "automation_live", sa.Boolean(), nullable=False, server_default=sa.text("false")
    ))
    op.add_column("onboarding_record", sa.Column(
        "automation_log", sa.JSON(), nullable=True
    ))
    op.add_column("onboarding_record", sa.Column(
        "maz_contract_signed_name", sa.Text(), nullable=True
    ))
    op.add_column("onboarding_record", sa.Column(
        "maz_contract_signed_at", sa.DateTime(timezone=True), nullable=True
    ))


def downgrade():
    op.drop_column("onboarding_record", "maz_contract_signed_at")
    op.drop_column("onboarding_record", "maz_contract_signed_name")
    op.drop_column("onboarding_record", "automation_log")
    op.drop_column("onboarding_record", "automation_live")
