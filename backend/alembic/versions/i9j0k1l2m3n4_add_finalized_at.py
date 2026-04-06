"""add finalized_at to payroll_batch

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa

revision = 'i9j0k1l2m3n4'
down_revision = 'h8i9j0k1l2m3'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('payroll_batch', sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column('payroll_batch', 'finalized_at')
