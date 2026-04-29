"""Ensure batch_correction_log table exists (idempotent recovery from prod drift).

Revision ID: zc3d4e5f6g7h8
Revises: zb2c3d4e5f6g7
Create Date: 2026-04-29

Background
----------
Prod hit ``relation "batch_correction_log" does not exist`` when adding a manual
adjustment. The original ``ab1b2c3d4e5f6_add_batch_correction_log`` migration was
recorded as applied on prod's alembic_version row but the table was never
actually created (state drift — likely from a merge-migration jumping past it).

This migration uses ``CREATE TABLE IF NOT EXISTS`` so it is safe to re-run on
any environment regardless of whether the table already exists.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "zc3d4e5f6g7h8"
down_revision: Union[str, Sequence[str], None] = "zb2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS batch_correction_log (
            id            SERIAL PRIMARY KEY,
            batch_id      INTEGER NOT NULL REFERENCES payroll_batch(payroll_batch_id) ON DELETE CASCADE,
            person_id     INTEGER REFERENCES person(person_id) ON DELETE SET NULL,
            field         TEXT NOT NULL,
            old_value     TEXT,
            new_value     TEXT,
            reason        TEXT,
            corrected_by  TEXT NOT NULL DEFAULT 'user',
            corrected_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_batch_correction_batch ON batch_correction_log(batch_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_batch_correction_person ON batch_correction_log(person_id);")


def downgrade() -> None:
    pass
