"""add_drive_archive_url_to_payroll_batch

Revision ID: zt8u9v0w1x2y
Revises: zs7t8u9v0w1x
Create Date: 2026-05-07

Adds drive_archive_url (TEXT, nullable) to payroll_batch.

Purpose:
  After a Maz batch is approved, Z-Pay automatically uploads the payroll
  Excel to Google Drive (Master/Maz/Z-Pay Outputs/) and stores the
  shareable Drive URL here.

  FA/Acumen batches use sp_file_bytes for the passthrough Excel — the Drive
  archive column is Maz-only in practice but is left unconstrained at the
  DB level for flexibility.

  NULL = no archive uploaded yet (all batches before this feature shipped).
  Backfill script: scripts/backfill_maz_drive_archive.py
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "zt8u9v0w1x2y"
down_revision: Union[str, None] = "zs7t8u9v0w1x"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payroll_batch",
        sa.Column("drive_archive_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payroll_batch", "drive_archive_url")
