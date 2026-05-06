"""ensure malik user_account row has role=admin

Revision ID: zp4q5r6s7t8u
Revises: zo3p4q5r6s7t
Create Date: 2026-05-06

The user_account row for 'malik' may have been seeded with the wrong role
(e.g. 'operator' or 'associate') if the migration ran before the DB had
the correct env-var context, or if the row was inadvertently modified.

This migration force-sets role='admin' for username='malik'.  Safe to
re-run — it's a no-op if the role is already 'admin'.

Mom's row (username='mom') is intentionally NOT touched — she stays 'operator'.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "zp4q5r6s7t8u"
down_revision: Union[str, None] = "zo3p4q5r6s7t"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Check current role first (for logging / idempotency transparency)
    row = conn.execute(
        sa.text("SELECT role FROM user_account WHERE username = 'malik'")
    ).fetchone()

    if row is None:
        # No DB row — env-fallback is handling auth. Nothing to fix.
        return

    if row[0] == "admin":
        # Already correct. No-op.
        return

    # Row exists but role is wrong — fix it.
    conn.execute(
        sa.text(
            "UPDATE user_account SET role = 'admin' WHERE username = 'malik'"
        )
    )


def downgrade() -> None:
    # Not reversible — we don't know what the role was before.
    pass
