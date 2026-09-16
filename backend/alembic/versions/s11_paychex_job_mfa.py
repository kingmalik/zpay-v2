"""S11 paychex_job MFA handoff — mode + mfa_code + mfa_requested_at.

Revision ID: s11_paychex_job_mfa
Revises: s10_season_board
Create Date: 2026-09-16

Rationale:
  The Paychex bot could never pass SMS MFA on its own login path — it waited
  for a dashboard that no human could reach inside a headless browser. The
  only working login was the weekly cookie capture. These columns let a
  human hand the bot the texted code from inside Z-Pay (POST /mfa/{job_id})
  and let the bot run in login-only mode to refresh the session without a
  payroll (mode = 'login').

Online-safe: ADD COLUMN ... NULL / DEFAULT on a tiny table. Reversible.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision = "s11_paychex_job_mfa"
down_revision = "s10_season_board"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE paychex_job ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'entry'")
    op.execute("ALTER TABLE paychex_job ADD COLUMN IF NOT EXISTS mfa_code TEXT NULL")
    op.execute("ALTER TABLE paychex_job ADD COLUMN IF NOT EXISTS mfa_requested_at TIMESTAMPTZ NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE paychex_job DROP COLUMN IF EXISTS mfa_requested_at")
    op.execute("ALTER TABLE paychex_job DROP COLUMN IF EXISTS mfa_code")
    op.execute("ALTER TABLE paychex_job DROP COLUMN IF EXISTS mode")
