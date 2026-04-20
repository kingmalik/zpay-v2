"""add sex column to person

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("person", sa.Column("sex", sa.String(10), nullable=True))


def downgrade():
    op.drop_column("person", "sex")
