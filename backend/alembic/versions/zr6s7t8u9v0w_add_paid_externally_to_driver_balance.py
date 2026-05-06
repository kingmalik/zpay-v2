"""add_paid_externally_to_driver_balance

Revision ID: zr6s7t8u9v0w
Revises: zq5r6s7t8u9v
Create Date: 2026-05-06

Adds a "Paid Externally" disposition to driver_balance.

A driver_balance row can now be in one of three states:
  1. Paid via Paychex   — settled_externally=FALSE, carried_over=0
  2. Withheld           — settled_externally=FALSE, carried_over>0
  3. Paid Externally    — settled_externally=TRUE,  carried_over=0

New columns:
  settled_externally  BOOLEAN NOT NULL DEFAULT FALSE
  external_method     TEXT    NULL — 'zelle' | 'cash' | 'retained' | 'custom'
  external_amount     NUMERIC(10,2) NULL — amount actually settled
  external_note       TEXT    NULL — free-text reason / context
  settled_at          TIMESTAMP WITH TIME ZONE NULL
  settled_by          TEXT    NULL — username / 'system' / 'zpay-agent-retroactive'
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "zr6s7t8u9v0w"
down_revision: Union[str, None] = "zq5r6s7t8u9v"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "driver_balance",
        sa.Column(
            "settled_externally",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "driver_balance",
        sa.Column("external_method", sa.Text(), nullable=True),
    )
    op.add_column(
        "driver_balance",
        sa.Column("external_amount", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "driver_balance",
        sa.Column("external_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "driver_balance",
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "driver_balance",
        sa.Column("settled_by", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("driver_balance", "settled_by")
    op.drop_column("driver_balance", "settled_at")
    op.drop_column("driver_balance", "external_note")
    op.drop_column("driver_balance", "external_amount")
    op.drop_column("driver_balance", "external_method")
    op.drop_column("driver_balance", "settled_externally")
