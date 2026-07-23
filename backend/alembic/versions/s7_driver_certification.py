"""driver_certification — S7 trilingual certification course + quiz sign-off

Revision ID: s7_driver_certification
Revises: s6b_partner_contract_signed_cols
Create Date: 2026-07-23

Rationale (MASTER-PLAN S7 — driver certification):
  Step 8 of driver onboarding (maz_training) becomes a real certification:
  6 content modules + 10-question comprehension quiz (pass = 8/10) + typed-
  name e-sign. This table is the certification RECORD, separate from
  onboarding_record.maz_training_status (which just tracks whether the
  onboarding step is complete) — driver_certification is a durable history
  of every attempt/pass, keyed by person so it survives onboarding_record
  churn (re-hires, re-onboarding) and lets us detect "needs recert" when
  COURSE_VERSION bumps (course content/rule changes).

  Multiple rows per person are allowed on purpose — every certification
  event (including recertifications after a course-version bump) gets its
  own row; the latest row per person is the current certification state.

Online-safe:
  - CREATE TABLE — no lock on any existing table.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "s7_driver_certification"
down_revision = "s6b_partner_contract_signed_cols"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "driver_certification",
        sa.Column("cert_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "person_id",
            sa.Integer(),
            sa.ForeignKey("person.person_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_version", sa.Text(), nullable=False),
        sa.Column("quiz_score", sa.SmallInteger(), nullable=False),
        sa.Column("quiz_total", sa.SmallInteger(), nullable=False),
        sa.Column("signed_name", sa.Text(), nullable=False),
        sa.Column(
            "certified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_driver_certification_person_id",
        "driver_certification",
        ["person_id"],
    )
    # Speeds up "latest cert per person" lookups (is_certified/needs_recert).
    op.create_index(
        "ix_driver_certification_person_certified_at",
        "driver_certification",
        ["person_id", "certified_at"],
    )


def downgrade():
    op.drop_index("ix_driver_certification_person_certified_at", table_name="driver_certification")
    op.drop_index("ix_driver_certification_person_id", table_name="driver_certification")
    op.drop_table("driver_certification")
