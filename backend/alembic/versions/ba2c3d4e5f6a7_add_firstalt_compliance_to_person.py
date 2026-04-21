"""add firstalt_compliance to person

Revision ID: ba2c3d4e5f6a7
Revises: ac1b2c3d4e5f6
Create Date: 2026-04-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ba2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "ac1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "person",
        sa.Column("firstalt_compliance", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("person", "firstalt_compliance")
