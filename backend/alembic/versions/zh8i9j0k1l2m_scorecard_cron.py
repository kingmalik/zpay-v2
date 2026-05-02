"""add scorecard_cron_run table

Revision ID: zh8i9j0k1l2m
Revises: zg7h8i9j0k1l
Create Date: 2026-05-02

New table: scorecard_cron_run
  - Tracks per-driver, per-week sends for idempotency.
  - UNIQUE(week_iso, person_id) prevents double-sends when cron fires twice.
"""

from alembic import op
import sqlalchemy as sa

revision = "zh8i9j0k1l2m"
down_revision = "zg7h8i9j0k1l"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scorecard_cron_run",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "person_id",
            sa.Integer,
            sa.ForeignKey("person.person_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_iso", sa.Text, nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sms_sent", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("email_sent", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("sms_error", sa.Text, nullable=True),
        sa.Column("email_error", sa.Text, nullable=True),
        sa.UniqueConstraint("week_iso", "person_id", name="uq_scorecard_cron_week_person"),
    )
    op.create_index(
        "ix_scorecard_cron_run_person_week",
        "scorecard_cron_run",
        ["person_id", "week_iso"],
    )


def downgrade() -> None:
    op.drop_index("ix_scorecard_cron_run_person_week", table_name="scorecard_cron_run")
    op.drop_table("scorecard_cron_run")
