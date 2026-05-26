"""add_r2_key_columns

Revision ID: zy5z6a7b8c9d
Revises: zy4z5a6b7c8d
Create Date: 2026-05-26

Rationale:
  Cloudflare R2 is already in production use for driver onboarding files.
  This migration adds r2_key columns to payroll_batch and paystub_archive so
  the new r2_payroll_archive service can record where each file landed.

  Both columns are:
    - Nullable VARCHAR — NULL until the R2 upload completes. Pre-existing rows
      stay NULL; the backfill script fills them on demand.
    - Indexed with a partial index on IS NOT NULL — supports efficient queries
      for "which batches/stubs still need uploading" in the backfill CLI.

  Online-safe: ADD COLUMN on a nullable column with no DEFAULT is an
  instantaneous metadata-only operation in Postgres — no table rewrite,
  no lock beyond an ACCESS EXCLUSIVE for < 1ms.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────────
revision: str = "zy5z6a7b8c9d"
down_revision: Union[str, None] = "zy4z5a6b7c8d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── payroll_batch.r2_key ─────────────────────────────────────────────────
    op.add_column(
        "payroll_batch",
        sa.Column("r2_key", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_payroll_batch_r2_key_notnull",
        "payroll_batch",
        ["r2_key"],
        unique=False,
        postgresql_where=sa.text("r2_key IS NOT NULL"),
    )

    # ── paystub_archive.r2_key ───────────────────────────────────────────────
    op.add_column(
        "paystub_archive",
        sa.Column("r2_key", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_paystub_archive_r2_key_notnull",
        "paystub_archive",
        ["r2_key"],
        unique=False,
        postgresql_where=sa.text("r2_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_paystub_archive_r2_key_notnull",
        table_name="paystub_archive",
        postgresql_where=sa.text("r2_key IS NOT NULL"),
    )
    op.drop_column("paystub_archive", "r2_key")

    op.drop_index(
        "ix_payroll_batch_r2_key_notnull",
        table_name="payroll_batch",
        postgresql_where=sa.text("r2_key IS NOT NULL"),
    )
    op.drop_column("payroll_batch", "r2_key")
