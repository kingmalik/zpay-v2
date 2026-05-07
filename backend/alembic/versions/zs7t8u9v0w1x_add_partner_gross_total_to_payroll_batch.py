"""add_partner_gross_total_to_payroll_batch

Revision ID: zs7t8u9v0w1x
Revises: zr6s7t8u9v0w
Create Date: 2026-05-07

Adds partner_gross_total (NUMERIC, nullable) to payroll_batch.

Purpose:
  Reconstruction imports (e.g. W14 batches rebuilt after the 2026-05-03 DB wipe)
  had no per-ride partner billing data, so the importer wrote driver net-pay into
  both gross_pay AND z_rate. This makes profit display as $0 on the history page.

  partner_gross_total stores the true FA/ED gross billing figure at the batch
  level when per-ride granularity is not recoverable. The payroll_history route
  uses it (when not NULL) instead of SUM(ride.gross_pay) for profit calculation.

  Normal batches (W15+) leave this NULL and are completely unaffected.

No backfill here — the two W14 batches are set in a separate apply script
  (scripts/apply_w14_partner_gross.py) after a DB backup.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "zs7t8u9v0w1x"
down_revision: Union[str, None] = "zr6s7t8u9v0w"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payroll_batch",
        sa.Column("partner_gross_total", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payroll_batch", "partner_gross_total")
