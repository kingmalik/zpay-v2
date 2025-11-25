"""init schema

Revision ID: 348ee4aac5d1
Revises: 
Create Date: 2025-09-19 22:40:07.537734

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '348ee4aac5d1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade():
    op.create_table(
        "person",
        sa.Column("person_id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, unique=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("email", sa.Text),
        sa.Column("phone", sa.Text),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "commission_rule",
        sa.Column("rule_id", sa.Integer, primary_key=True),
        sa.Column("person_id", sa.Integer, sa.ForeignKey("person.person_id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.Text, nullable=False, server_default=sa.text("'finder_fee'")),
        sa.Column("pct_fee", sa.Numeric(6,4), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date),
    )
    op.create_unique_constraint(
        "uq_commission_person_name_from",
        "commission_rule",
        ["person_id", "name", "effective_from"],
    )

    op.create_table(
        "ride",
        sa.Column("ride_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("person_id", sa.Integer, sa.ForeignKey("person.person_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ride_start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ride_end_ts", sa.DateTime(timezone=True)),
        sa.Column("origin", sa.Text),
        sa.Column("destination", sa.Text),
        sa.Column("distance_km", sa.Numeric(10,3)),
        sa.Column("duration_min", sa.Numeric(10,2)),
        sa.Column("base_fare", sa.Numeric(12,2), nullable=False, server_default=sa.text("0")),
        sa.Column("tips", sa.Numeric(12,2), nullable=False, server_default=sa.text("0")),
        sa.Column("adjustments", sa.Numeric(12,2), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'USD'")),
        sa.Column("source_ref", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ride_person_id_idx", "ride", ["person_id"])
    op.create_index("ride_start_ts_idx", "ride", ["ride_start_ts"])


def downgrade():
    op.drop_index("ride_start_ts_idx", table_name="ride")
    op.drop_index("ride_person_id_idx", table_name="ride")
    op.drop_table("ride")
    op.drop_constraint("uq_commission_person_name_from", "commission_rule", type_="unique")
    op.drop_table("commission_rule")
    op.drop_table("person")
