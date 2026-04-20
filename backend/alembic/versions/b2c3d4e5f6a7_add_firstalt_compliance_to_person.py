"""add firstalt_compliance to person

Revision ID: b2c3d4e5f6a7
Revises: z5a6b7c8d9e0
Create Date: 2026-04-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "z5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "person",
        sa.Column("firstalt_compliance", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("person", "firstalt_compliance")
