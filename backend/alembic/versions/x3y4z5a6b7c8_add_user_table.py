"""add user table for team accounts (admin/operator/associate)

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-04-14

Phase 1 of the Team OS rollout. Introduces a real user table so team
members have personal accounts (vs the env-var registry used previously).

Seeds Malik (admin) + Mom (operator) using password hashes already set in
the ZPAY_PASSWORD_HASH_MALIK / ZPAY_PASSWORD_HASH_MOM env vars. If those
env vars are missing at migration time the rows are still created with
empty password hashes — set them via /settings/profile before the first
login.

The env-var auth path remains functional as a fallback for one release
cycle; once /login is confirmed working against the DB the env-var
fallback can be removed.
"""
from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x3y4z5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "w2x3y4z5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_account",  # avoid reserved word "user" in Postgres
        sa.Column("user_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.Text, nullable=False, unique=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column(
            "role",
            sa.Text,
            nullable=False,
            server_default=sa.text("'associate'"),
        ),
        sa.Column("password_hash", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("email", sa.Text, nullable=True),
        sa.Column("phone", sa.Text, nullable=True),
        sa.Column(
            "language",
            sa.Text,
            nullable=False,
            server_default=sa.text("'en'"),
        ),
        sa.Column(
            "color",
            sa.Text,
            nullable=False,
            server_default=sa.text("'#4facfe'"),
        ),
        sa.Column(
            "initials",
            sa.Text,
            nullable=False,
            server_default=sa.text("'?'"),
        ),
        sa.Column("avatar_url", sa.Text, nullable=True),
        sa.Column(
            "active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('admin', 'operator', 'associate')",
            name="ck_user_account_role_valid",
        ),
    )
    op.create_index("ix_user_account_username", "user_account", ["username"], unique=True)
    op.create_index("ix_user_account_role", "user_account", ["role"])

    # Seed the two known team members from existing env-var hashes
    malik_hash = os.environ.get("ZPAY_PASSWORD_HASH_MALIK", "").strip()
    mom_hash = os.environ.get("ZPAY_PASSWORD_HASH_MOM", "").strip()
    malik_display = os.environ.get("ZPAY_DISPLAY_MALIK", "Malik").strip() or "Malik"
    mom_display = os.environ.get("ZPAY_DISPLAY_MOM", "Mom").strip() or "Mom"

    op.execute(
        sa.text(
            """
            INSERT INTO user_account
                (username, full_name, display_name, role, password_hash,
                 color, initials, language)
            VALUES
                (:username, :full_name, :display_name, :role, :password_hash,
                 :color, :initials, :language)
            ON CONFLICT (username) DO NOTHING
            """
        ).bindparams(
            username="malik",
            full_name="Malik Milion",
            display_name=malik_display,
            role="admin",
            password_hash=malik_hash,
            color="#4facfe",
            initials="M",
            language="en",
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO user_account
                (username, full_name, display_name, role, password_hash,
                 color, initials, language)
            VALUES
                (:username, :full_name, :display_name, :role, :password_hash,
                 :color, :initials, :language)
            ON CONFLICT (username) DO NOTHING
            """
        ).bindparams(
            username="mom",
            full_name="Zubeda Adem",
            display_name=mom_display,
            role="operator",
            password_hash=mom_hash,
            color="#764ba2",
            initials="♡",
            language="en",
        )
    )


def downgrade() -> None:
    op.drop_index("ix_user_account_role", table_name="user_account")
    op.drop_index("ix_user_account_username", table_name="user_account")
    op.drop_table("user_account")
