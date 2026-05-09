"""add audit_log table

Revision ID: zv1w2x3y4z5a
Revises: zu9v0w1x2y3z
Create Date: 2026-05-08

Rationale:
  On 2026-05-07 Malik mis-clicked the people-page Active toggle and deactivated
  random drivers. This migration adds an immutable audit_log table so every
  toggle (and future sensitive mutations) are traceable: who, when, from which
  IP, and the exact before/after state.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────────
revision: str = "zv1w2x3y4z5a"
down_revision: Union[str, None] = "zu9v0w1x2y3z"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("user_account.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_email", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("before_value", sa.JSON(), nullable=True),
        sa.Column("after_value", sa.JSON(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_audit_log_action",     "audit_log", ["action"])
    op.create_index("ix_audit_log_target",     "audit_log", ["target_type", "target_id"])
    op.create_index("ix_audit_log_actor",      "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_actor",      table_name="audit_log")
    op.drop_index("ix_audit_log_target",     table_name="audit_log")
    op.drop_index("ix_audit_log_action",     table_name="audit_log")
    op.drop_table("audit_log")
