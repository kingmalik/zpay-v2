"""add EverDriven onboarding fields

Revision ID: a7b8c9d0e1f2
Revises: bb7c8d9e0f1a2
Create Date: 2026-04-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "z5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── onboarding_record: partner + Contractor Compliance columns ──────────
    op.add_column(
        "onboarding_record",
        sa.Column(
            "partner",
            sa.String(20),
            nullable=False,
            server_default="firstalt",
        ),
    )
    op.add_column(
        "onboarding_record",
        sa.Column("cc_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "onboarding_record",
        sa.Column("cc_status", sa.JSON, nullable=True),
    )

    # ── onboarding_record: Hallo.ai columns ─────────────────────────────────
    op.add_column(
        "onboarding_record",
        sa.Column("hallo_link_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "onboarding_record",
        sa.Column("hallo_score", sa.Numeric(4, 1), nullable=True),
    )
    op.add_column(
        "onboarding_record",
        sa.Column("hallo_completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── onboarding_record: SafeRide columns ─────────────────────────────────
    op.add_column(
        "onboarding_record",
        sa.Column("saferide_link_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "onboarding_record",
        sa.Column("saferide_cert_uploaded_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── onboarding_record: EverDriven step status columns ───────────────────
    op.add_column(
        "onboarding_record",
        sa.Column(
            "ed_app_install_status",
            sa.String(20),
            nullable=True,
            server_default="pending",
        ),
    )
    op.add_column(
        "onboarding_record",
        sa.Column(
            "equipment_status",
            sa.String(20),
            nullable=True,
            server_default="pending",
        ),
    )
    op.add_column(
        "onboarding_record",
        sa.Column(
            "ed_vehicle_insp_1_status",
            sa.String(20),
            nullable=True,
            server_default="pending",
        ),
    )
    op.add_column(
        "onboarding_record",
        sa.Column(
            "ed_vehicle_insp_2_status",
            sa.String(20),
            nullable=True,
            server_default="pending",
        ),
    )
    op.add_column(
        "onboarding_record",
        sa.Column(
            "ed_bgc_status",
            sa.String(20),
            nullable=True,
            server_default="pending",
        ),
    )
    op.add_column(
        "onboarding_record",
        sa.Column(
            "ed_drug_test_status",
            sa.String(20),
            nullable=True,
            server_default="pending",
        ),
    )

    # ── person: Contractor Compliance fields ────────────────────────────────
    op.add_column(
        "person",
        sa.Column("contractor_compliance_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "person",
        sa.Column("cc_compliance", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("person", "cc_compliance")
    op.drop_column("person", "contractor_compliance_id")

    op.drop_column("onboarding_record", "ed_drug_test_status")
    op.drop_column("onboarding_record", "ed_bgc_status")
    op.drop_column("onboarding_record", "ed_vehicle_insp_2_status")
    op.drop_column("onboarding_record", "ed_vehicle_insp_1_status")
    op.drop_column("onboarding_record", "equipment_status")
    op.drop_column("onboarding_record", "ed_app_install_status")
    op.drop_column("onboarding_record", "saferide_cert_uploaded_at")
    op.drop_column("onboarding_record", "saferide_link_sent_at")
    op.drop_column("onboarding_record", "hallo_completed_at")
    op.drop_column("onboarding_record", "hallo_score")
    op.drop_column("onboarding_record", "hallo_link_sent_at")
    op.drop_column("onboarding_record", "cc_status")
    op.drop_column("onboarding_record", "cc_id")
    op.drop_column("onboarding_record", "partner")
