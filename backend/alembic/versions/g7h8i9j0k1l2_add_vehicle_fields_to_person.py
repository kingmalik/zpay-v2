"""add vehicle fields to person

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-01

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('person', sa.Column('vehicle_make', sa.Text(), nullable=True))
    op.add_column('person', sa.Column('vehicle_model', sa.Text(), nullable=True))
    op.add_column('person', sa.Column('vehicle_year', sa.Integer(), nullable=True))
    op.add_column('person', sa.Column('vehicle_plate', sa.Text(), nullable=True))
    op.add_column('person', sa.Column('vehicle_color', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('person', 'vehicle_color')
    op.drop_column('person', 'vehicle_plate')
    op.drop_column('person', 'vehicle_year')
    op.drop_column('person', 'vehicle_model')
    op.drop_column('person', 'vehicle_make')
