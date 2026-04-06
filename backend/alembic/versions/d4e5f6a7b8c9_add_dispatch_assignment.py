"""
add dispatch_assignment table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "dispatch_assignment",
        sa.Column("assignment_id",   sa.Integer,  primary_key=True),
        sa.Column("assigned_date",   sa.Date,     nullable=False),
        sa.Column("pickup_address",  sa.Text,     nullable=False),
        sa.Column("dropoff_address", sa.Text,     nullable=False),
        sa.Column("pickup_time",     sa.Text,     nullable=False),
        sa.Column("dropoff_time",    sa.Text,     nullable=False),
        sa.Column("person_id",       sa.Integer,  sa.ForeignKey("person.person_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source",          sa.Text,     nullable=False),
        sa.Column("notes",           sa.Text,     nullable=True),
        sa.Column("created_at",      sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_dispatch_assignment_date",   "dispatch_assignment", ["assigned_date"])
    op.create_index("ix_dispatch_assignment_person", "dispatch_assignment", ["person_id"])


def downgrade():
    op.drop_index("ix_dispatch_assignment_person", table_name="dispatch_assignment")
    op.drop_index("ix_dispatch_assignment_date",   table_name="dispatch_assignment")
    op.drop_table("dispatch_assignment")
