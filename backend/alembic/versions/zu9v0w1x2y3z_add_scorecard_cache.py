"""add_scorecard_cache

Revision ID: zu9v0w1x2y3z
Revises: zt8u9v0w1x2y
Create Date: 2026-05-07

Adds scorecard_cache table — weekly snapshot per driver, written by the Sunday
cron and by manual send-now. Enables week-over-week delta computation and the
30-day rolling average view without re-running the full scoring pipeline.

Columns
-------
id                  SERIAL PK
person_id           FK → person.person_id (indexed, CASCADE delete)
week_num            INT  — ISO week number (1-53)
year                INT  — ISO year (matches ISO week year, not calendar year)
week_iso            TEXT — 'YYYY-Www' denormalized for fast lookup
self_serve_pct      FLOAT nullable — (total_trips - escalations) / total_trips * 100
on_time_pct         FLOAT nullable — on_time_pickup_arrival raw * 100
escalation_count    INT   nullable
composite_score     FLOAT nullable
total_trips         INT   default 0
computed_at         TIMESTAMPTZ — when the snapshot was written
source              VARCHAR(16) — 'cron' | 'manual'

Unique constraint: (person_id, week_num, year) — one snapshot per driver per week.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "zu9v0w1x2y3z"
down_revision: Union[str, None] = "zt8u9v0w1x2y"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scorecard_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_num", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("week_iso", sa.Text(), nullable=False),
        sa.Column("self_serve_pct", sa.Float(), nullable=True),
        sa.Column("on_time_pct", sa.Float(), nullable=True),
        sa.Column("escalation_count", sa.Integer(), nullable=True),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column("total_trips", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("source", sa.String(16), nullable=False, server_default="cron"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "week_num", "year", name="uq_scorecard_cache_person_week"),
    )
    op.create_index("ix_scorecard_cache_person_id", "scorecard_cache", ["person_id"])
    op.create_index("ix_scorecard_cache_week", "scorecard_cache", ["year", "week_num"])


def downgrade() -> None:
    op.drop_index("ix_scorecard_cache_week", table_name="scorecard_cache")
    op.drop_index("ix_scorecard_cache_person_id", table_name="scorecard_cache")
    op.drop_table("scorecard_cache")
