"""add tin and license_number to person

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-04-01
"""
from alembic import op
import sqlalchemy as sa

revision = 'h8i9j0k1l2m3'
down_revision = 'g7h8i9j0k1l2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('person', sa.Column('tin', sa.Text(), nullable=True))
    op.add_column('person', sa.Column('license_number', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('person', 'license_number')
    op.drop_column('person', 'tin')
