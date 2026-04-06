"""add email_template table

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa

revision = 'j0k1l2m3n4o5'
down_revision = 'i9j0k1l2m3n4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'email_template',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('scope', sa.Text(), nullable=False, server_default='default'),
        sa.Column('payroll_batch_id', sa.Integer(), sa.ForeignKey('payroll_batch.payroll_batch_id', ondelete='CASCADE'), nullable=True),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('person.person_id', ondelete='CASCADE'), nullable=True),
        sa.Column('subject', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )


def downgrade():
    op.drop_table('email_template')
