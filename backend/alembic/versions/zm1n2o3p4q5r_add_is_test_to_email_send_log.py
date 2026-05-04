"""add is_test to email_send_log

Revision ID: zm1n2o3p4q5r
Revises: zl4m5n6o7p8q
Create Date: 2026-05-04

Adds is_test boolean to email_send_log so admin test-sends (recipient override)
are distinguishable from real driver sends and don't pollute re-send logic.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "zm1n2o3p4q5r"
down_revision: Union[str, None] = "zl4m5n6o7p8q"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_send_log",
        sa.Column(
            "is_test",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("email_send_log", "is_test")
