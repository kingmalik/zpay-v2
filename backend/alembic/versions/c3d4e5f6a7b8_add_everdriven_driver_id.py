"""
add everdriven_driver_id to person

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("person", sa.Column("everdriven_driver_id", sa.Integer, nullable=True))
    op.create_index("uq_person_everdriven_id", "person", ["everdriven_driver_id"], unique=True)


def downgrade():
    op.drop_index("uq_person_everdriven_id", table_name="person")
    op.drop_column("person", "everdriven_driver_id")
