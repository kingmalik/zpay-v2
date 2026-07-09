"""add_paychex_job

Revision ID: s1a_paychex_job
Revises: aa1b2c3d4e5f
Create Date: 2026-07-08

Rationale:
  S1-B Monday-proofing sprint. Railway runs multiple replicas of the backend
  behind a round-robin proxy. The Paychex bot (routes/paychex_bot.py) kept
  job status in a module-level in-memory `_jobs` dict — a status poll that
  landed on a different replica than the one running the job 404'd, so the
  frontend progress page (PaychexBotPanel.tsx) never showed "done" (the
  owner's #1 complaint). A container restart also silently orphaned any
  in-flight job with no trace.

  This table makes Postgres the source of truth for job state so any
  replica can answer GET /status/{job_id}, and gives the crash-orphan
  sweep (jobs stuck 'running' past 15 min) something to read updated_at
  from.

  Columns:
    job_id                str UUID primary key (matches the existing
                           uuid4-based job_id scheme).
    payroll_batch_id       Soft reference to payroll_batch, SET NULL on
                           delete — a job's audit trail should outlive the
                           batch row's lifecycle.
    company                "acumen" or "maz".
    status                 Free-text, not a DB enum — the bot writes richer
                           transient values (pending/running/mfa_required/
                           driver_error/done/failed) that the API passes
                           through unchanged.
    stage                  Human "what's happening now" label (e.g. current
                           driver name or login sub-stage).
    message                Human-readable status line.
    progress_current/total Driver-count progress bar inputs.
    error                  Populated only on failure.
    debug_urls             JSON list of R2 presigned debug-snapshot URLs.
    created_at/updated_at  NOW() defaults; updated_at bumps on every write
                           and is what the orphan sweep compares against.
    finished_at            Set once the job reaches a terminal state.

  Indexes:
    ix_paychex_job_created_at — supports a future "recent jobs" admin view
                                 and general housekeeping queries.

  Online-safe: new table only, no existing table touched.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────────
revision: str = "s1a_paychex_job"
down_revision: Union[str, None] = "aa1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paychex_job",
        sa.Column("job_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "payroll_batch_id",
            sa.Integer(),
            sa.ForeignKey("payroll_batch.payroll_batch_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("debug_urls", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_paychex_job_created_at",
        "paychex_job",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_paychex_job_created_at", table_name="paychex_job")
    op.drop_table("paychex_job")
