"""
add home_address and firstalt_driver_id to person

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("person", sa.Column("home_address", sa.Text, nullable=True))
    op.add_column("person", sa.Column("firstalt_driver_id", sa.Integer, nullable=True))
    op.create_index("uq_person_firstalt_id", "person", ["firstalt_driver_id"], unique=True)


def downgrade():
    op.drop_index("uq_person_firstalt_id", table_name="person")
    op.drop_column("person", "firstalt_driver_id")
    op.drop_column("person", "home_address")
