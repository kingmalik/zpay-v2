"""add activity_log table

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-04-05
"""

from alembic import op
import sqlalchemy as sa

revision = 'l2m3n4o5p6q7'
down_revision = 'k1l2m3n4o5p6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'activity_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('username', sa.Text(), nullable=False),
        sa.Column('display_name', sa.Text(), nullable=False, server_default='Unknown'),
        sa.Column('user_color', sa.Text(), nullable=True),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.create_index('ix_activity_log_created', 'activity_log', ['created_at'])
    op.create_index('ix_activity_log_username', 'activity_log', ['username'])


def downgrade():
    op.drop_index('ix_activity_log_username', 'activity_log')
    op.drop_index('ix_activity_log_created', 'activity_log')
    op.drop_table('activity_log')
