"""add_z_rate_locked_at

Revision ID: aa1b2c3d4e5f
Revises: zz6a7b8c9d0e
Create Date: 2026-06-22

Rationale:
  Defensive audit-trail column for ride.z_rate.

  Today's cross-driver rate-drift audit (Nuraynie W11 investigation)
  surfaced a structural gap: ride.z_rate has no updated_at, no lock
  column, and no protection against silent post-stub edits.  The audit
  found no current drift (1,062 person/batch pairs match), but if any
  service ever re-prices rides in place after stubs are emailed the
  mutation would be invisible.

  Add z_rate_locked_at TIMESTAMPTZ NULL.  Set to NOW() when a paystub
  is generated or sent for a (person, batch).  Currently informational
  — no service writes to ride.z_rate after ingest, so no runtime guard
  is needed yet.  If a future change introduces a write path,
  z_rate_locked_at provides the lock signal.

  Online-safe:
    - Nullable column with no server default — zero table rewrite.
    - Additive only; existing rows remain NULL.
    - Fully reversible via downgrade().
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────────
revision: str = "aa1b2c3d4e5f"
down_revision: Union[str, None] = "zz6a7b8c9d0e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ride",
        sa.Column("z_rate_locked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ride", "z_rate_locked_at")
