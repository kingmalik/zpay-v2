"""add paycheck_code_maz to person

Revision ID: zi1j2k3l4m5n
Revises: 1024a56610b6
Create Date: 2026-05-02

Adds paycheck_code_maz (VARCHAR/Text, nullable) to the person table.
This is the Maz Services LLC Paychex worker ID for EverDriven batches.
paycheck_code (already exists) is the Acumen/FirstAlt side.

Uses IF NOT EXISTS so this migration is idempotent — safe to run on prod
where the column was added manually before this file was written.
"""

from alembic import op
import sqlalchemy as sa

revision = "zi1j2k3l4m5n"
down_revision = "1024a56610b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS makes this safe to run on prod where the column already exists.
    op.execute(
        "ALTER TABLE person ADD COLUMN IF NOT EXISTS paycheck_code_maz VARCHAR"
    )


def downgrade() -> None:
    op.drop_column("person", "paycheck_code_maz")
