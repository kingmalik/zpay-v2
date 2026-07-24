"""partner_payment — external_ref for EFT auto-ingest dedupe

Revision ID: s8c_partner_payment_external_ref
Revises: s8b_intake_source_msg
Create Date: 2026-07-23

Rationale (EFT remittance auto-ingest, T2):
  remit_ingest.py auto-creates partner_payment rows from First Student ACH
  advice PDFs. Every Railway replica runs the poll scheduler, so SELECT-
  then-INSERT dedupe alone races across replicas (the same defect class
  s8b's unique index closed for ride_intake). external_ref stores the
  business key of the advice line — "eft:<ach-payment#>:<invoice-ref>" —
  which is stable across re-sent emails (new Gmail id, same payment#) and
  distinct across genuine repeat deposits to the same batch (new payment#).
  NULL for every manually-entered row; the partial unique index therefore
  only constrains watcher-created rows, never manual ones.

Online-safe:
  - ADD COLUMN ... NULL — metadata-only in Postgres, no table rewrite.
  - Partial UNIQUE index (WHERE external_ref IS NOT NULL) — built on a
    brand-new, all-NULL column, so it's instant regardless of table size.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "s8c_partner_payment_external_ref"
down_revision = "s8b_intake_source_msg"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "partner_payment",
        sa.Column("external_ref", sa.Text(), nullable=True),
    )
    op.create_index(
        "ux_partner_payment_external_ref",
        "partner_payment",
        ["external_ref"],
        unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )


def downgrade():
    op.drop_index("ux_partner_payment_external_ref", table_name="partner_payment")
    op.drop_column("partner_payment", "external_ref")
