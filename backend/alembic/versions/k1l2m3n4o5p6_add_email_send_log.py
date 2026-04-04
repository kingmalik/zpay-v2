"""add email_send_log table

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-04-04

"""
from alembic import op
import sqlalchemy as sa

revision = 'k1l2m3n4o5p6'
down_revision = 'j0k1l2m3n4o5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'email_send_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('payroll_batch_id', sa.Integer(), sa.ForeignKey('payroll_batch.payroll_batch_id', ondelete='CASCADE'), nullable=False),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('person.person_id', ondelete='CASCADE'), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column('status', sa.Text(), server_default=sa.text("'sent'"), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
    )
    op.create_index('ix_email_send_log_batch', 'email_send_log', ['payroll_batch_id'])
    op.create_index('ix_email_send_log_person', 'email_send_log', ['person_id'])


def downgrade():
    op.drop_index('ix_email_send_log_person')
    op.drop_index('ix_email_send_log_batch')
    op.drop_table('email_send_log')
