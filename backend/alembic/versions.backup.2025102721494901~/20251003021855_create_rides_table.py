
"""create rides table

Revision ID: 20251003021855
Revises: 
Create Date: 2025-10-03 02:18:55

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20251003021855"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("person", sa.String(length=200), nullable=False, index=True),
        sa.Column("code", sa.String(length=50), nullable=True, index=True),
        sa.Column("date", sa.Date(), nullable=True, index=True),
        sa.Column("key", sa.String(length=50), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=True),
        sa.Column("miles", sa.Float(), nullable=True),
        sa.Column("gross", sa.Numeric(12,2), nullable=True),
        sa.Column("net_pay", sa.Numeric(12,2), nullable=True),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_ride_dedupe",
        "rides",
        ["person","code","date","key","name","miles","gross","net_pay","source_file"]
    )
    op.create_index("ix_rides_person", "rides", ["person"])
    op.create_index("ix_rides_code", "rides", ["code"])
    op.create_index("ix_rides_date", "rides", ["date"])


def downgrade() -> None:
    op.drop_index("ix_rides_date", table_name="rides")
    op.drop_index("ix_rides_code", table_name="rides")
    op.drop_index("ix_rides_person", table_name="rides")
    op.drop_constraint("uq_ride_dedupe", "rides", type_="unique")
    op.drop_table("rides")
