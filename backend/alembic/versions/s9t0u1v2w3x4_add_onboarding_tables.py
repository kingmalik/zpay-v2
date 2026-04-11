"""
Add onboarding_record, onboarding_document, and onboarding_file tables.

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-04-09
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "s9t0u1v2w3x4"
down_revision: Union[str, None] = "r8s9t0u1v2w3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # onboarding_record — one row per driver, tracks all step statuses
    op.create_table(
        "onboarding_record",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "person_id",
            sa.Integer(),
            sa.ForeignKey("person.person_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("consent_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("consent_envelope_id", sa.Text(), nullable=True),
        sa.Column("priority_email_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("brandon_email_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("bgc_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("drug_test_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("contract_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("contract_envelope_id", sa.Text(), nullable=True),
        sa.Column("files_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("paychex_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_onboarding_record_person", "onboarding_record", ["person_id"])

    # onboarding_document — Adobe Sign envelope per doc type
    op.create_table(
        "onboarding_document",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "onboarding_id",
            sa.Integer(),
            sa.ForeignKey("onboarding_record.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("envelope_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signer_email", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_onboarding_document_onboarding", "onboarding_document", ["onboarding_id"])
    op.create_index(
        "uq_onboarding_document_envelope",
        "onboarding_document",
        ["envelope_id"],
        unique=True,
    )

    # onboarding_file — driver document files in Cloudflare R2
    op.create_table(
        "onboarding_file",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "onboarding_id",
            sa.Integer(),
            sa.ForeignKey("onboarding_record.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_type", sa.Text(), nullable=False),
        sa.Column("r2_key", sa.Text(), nullable=True),
        sa.Column("r2_url", sa.Text(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_onboarding_file_onboarding", "onboarding_file", ["onboarding_id"])


def downgrade() -> None:
    op.drop_index("ix_onboarding_file_onboarding", table_name="onboarding_file")
    op.drop_table("onboarding_file")

    op.drop_index("uq_onboarding_document_envelope", table_name="onboarding_document")
    op.drop_index("ix_onboarding_document_onboarding", table_name="onboarding_document")
    op.drop_table("onboarding_document")

    op.drop_index("ix_onboarding_record_person", table_name="onboarding_record")
    op.drop_table("onboarding_record")
