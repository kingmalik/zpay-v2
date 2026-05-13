"""add paystub_archive table

Revision ID: zw2x3y4z5a6b
Revises: zv1w2x3y4z5a
Create Date: 2026-05-13

Rationale:
  Mom needs a permanent store of every pay stub PDF Z-Pay has ever
  generated or sent. This enables:
    - Driver requests for old stubs (e.g. "can I get my March stub?")
    - Tax-time document retrieval without digging through Gmail Sent
    - Re-email of any historical stub in two clicks

  One row per (person_id, payroll_batch_id) — idempotent.
  Regenerating or re-sending updates the existing row in place;
  we never accumulate duplicates for the same driver+batch.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────────
revision: str = "zw2x3y4z5a6b"
down_revision: Union[str, None] = "zv1w2x3y4z5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paystub_archive",
        sa.Column("paystub_id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "person_id",
            sa.Integer(),
            sa.ForeignKey("person.person_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "payroll_batch_id",
            sa.Integer(),
            sa.ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("sent_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipient_email", sa.Text(), nullable=True),
        sa.Column("file_path",       sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("total_pay",       sa.Numeric(12, 2), nullable=True),
        sa.Column("ride_count",      sa.Integer(), nullable=True),
        sa.Column(
            "regenerated_from_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Unique: one row per driver + batch
    op.create_index(
        "uq_paystub_archive_person_batch",
        "paystub_archive",
        ["person_id", "payroll_batch_id"],
        unique=True,
    )
    # Per-driver list descending by generation time
    op.create_index(
        "ix_paystub_archive_person_generated",
        "paystub_archive",
        ["person_id", "generated_at"],
    )
    # Batch-wise access (backfill, bulk resend)
    op.create_index(
        "ix_paystub_archive_batch",
        "paystub_archive",
        ["payroll_batch_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_paystub_archive_batch",          table_name="paystub_archive")
    op.drop_index("ix_paystub_archive_person_generated", table_name="paystub_archive")
    op.drop_index("uq_paystub_archive_person_batch",   table_name="paystub_archive")
    op.drop_table("paystub_archive")
