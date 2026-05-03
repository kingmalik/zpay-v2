"""
Add maz_training_status to onboarding_record.

maz_training_status — tracks EverDriven (Maz) training completion step.
Possible values: pending | complete | manual | skipped

Mirrors training_status (FirstAlt/Acumen), but scoped to the EverDriven
onboarding pipeline.  The monitor was already referencing this column
causing: "column onboarding_record.maz_training_status does not exist"
every 30 minutes.

Revision ID: zj2k3l4m5n6o
Revises: zi1j2k3l4m5n
Create Date: 2026-05-03
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "zj2k3l4m5n6o"
down_revision: Union[str, None] = "zi1j2k3l4m5n"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use IF NOT EXISTS so this is safe whether prod is missing the column
    # (the normal case we're fixing) or it was added manually.
    op.execute(
        """
        ALTER TABLE onboarding_record
        ADD COLUMN IF NOT EXISTS maz_training_status TEXT NOT NULL DEFAULT 'pending'
        """
    )


def downgrade() -> None:
    op.drop_column("onboarding_record", "maz_training_status")
