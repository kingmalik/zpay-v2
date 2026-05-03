"""
Add person.status and onboarding_record.maz_contract_status.

These two columns are defined in the SQLAlchemy models but were never
covered by an Alembic migration, causing Railway to fail at startup:

  column person.status does not exist
  column onboarding_record.maz_contract_status does not exist

Both use IF NOT EXISTS so the migration is safe to run on a prod DB
that may have had these columns added manually.

person.status values: 'active' | 'inactive' | 'suspended'
  - server_default 'active' backfills every existing driver row.

onboarding_record.maz_contract_status values:
  'pending' | 'sent' | 'signed' | 'complete' | 'manual' | 'skipped'
  - server_default 'pending' matches what the code already assumes for
    records that pre-date this column.

Revision ID: zk3l4m5n6o7p
Revises: zj2k3l4m5n6o
Create Date: 2026-05-03
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "zk3l4m5n6o7p"
down_revision: Union[str, None] = "zj2k3l4m5n6o"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. person.status — the startup-blocking error
    op.execute(
        """
        ALTER TABLE person
        ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
        """
    )

    # 2. onboarding_record.maz_contract_status — referenced heavily in
    #    onboarding routes and the monitor loop; also produces errors at startup.
    op.execute(
        """
        ALTER TABLE onboarding_record
        ADD COLUMN IF NOT EXISTS maz_contract_status TEXT NOT NULL DEFAULT 'pending'
        """
    )


def downgrade() -> None:
    op.drop_column("onboarding_record", "maz_contract_status")
    op.drop_column("person", "status")
