"""add sex column to person

Revision ID: bb7c8d9e0f1a2
Revises: b7c8d9e0f1a2
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = "bb7c8d9e0f1a2"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("person", sa.Column("sex", sa.String(10), nullable=True))


def downgrade():
    op.drop_column("person", "sex")
