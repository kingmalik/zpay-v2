"""
Add payroll_withheld_override and payroll_manual_withhold tables.

These tables were used in the workflow routes (force-pay / manual-withhold
features) but never had Alembic migrations. After the May 3 DB wipe + restore,
they were missing from prod, causing 500 errors on the Excel export endpoint
(InFailedSqlTransaction because the query error poisoned the DB session).

payroll_withheld_override — per-batch force-pay overrides:
  batch_id   → the payroll_batch this override applies to
  person_id  → the driver being force-paid
  PRIMARY KEY (batch_id, person_id)

payroll_manual_withhold — permanent per-driver manual withhold flag:
  person_id  → the driver to withhold regardless of earnings
  note       → reason / operator note
  created_at → when the flag was set

Both statements use CREATE TABLE IF NOT EXISTS so they are idempotent
and safe to run on a DB that already has these tables.

Revision ID: zl4m5n6o7p8q
Revises: zk3l4m5n6o7p
Create Date: 2026-05-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "zl4m5n6o7p8q"
down_revision: Union[str, None] = "zk3l4m5n6o7p"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_withheld_override (
            batch_id   INTEGER NOT NULL,
            person_id  INTEGER NOT NULL,
            PRIMARY KEY (batch_id, person_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_manual_withhold (
            person_id  INTEGER NOT NULL PRIMARY KEY,
            note       TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payroll_manual_withhold")
    op.execute("DROP TABLE IF EXISTS payroll_withheld_override")
