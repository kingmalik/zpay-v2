"""
init schema

Revision ID: 348ee4aac5d1
Revises:
Create Date: 2025-09-19 22:40:07.537734
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "348ee4aac5d1"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    # -----------------------------
    # person
    # -----------------------------
    op.create_table(
        "person",
        sa.Column("person_id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, nullable=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("email", sa.Text),
        sa.Column("phone", sa.Text),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("uq_person_external_id", "person", ["external_id"], unique=True)
    op.create_index(
        "uq_person_name_when_no_ext",
        "person",
        [sa.text(r"lower(regexp_replace(trim(full_name), '\s+', ' ', 'g'))")],
        unique=True,
        postgresql_where=sa.text("external_id IS NULL"),
    )

    # -----------------------------
    # payroll_batch
    # -----------------------------
    op.create_table(
        "payroll_batch",
        sa.Column("payroll_batch_id", sa.Integer, primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("company_name", sa.Text, nullable=False),
        sa.Column("batch_ref", sa.Text),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'USD'")),
        sa.Column("period_start", sa.Date),
        sa.Column("period_end", sa.Date),
        sa.Column("week_start", sa.Date),
        sa.Column("week_end", sa.Date),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("notes", sa.Text),
    )
    op.create_index(
        "ix_payroll_batch_source_company_uploaded",
        "payroll_batch",
        ["source", "company_name", "uploaded_at"],
    )
    op.create_index("ix_payroll_batch_period", "payroll_batch", ["period_start", "period_end"])

    # -----------------------------
    # z_rate_service
    # -----------------------------
    op.create_table(
        "z_rate_service",
        sa.Column("z_rate_service_id", sa.Integer, primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("company_name", sa.Text, nullable=False),
        sa.Column("service_key", sa.Text, nullable=False),
        sa.Column("service_name", sa.Text, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'USD'")),
        sa.Column("default_rate", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    # Non-unique helper indexes
    op.create_index("ix_z_rate_service_company", "z_rate_service", ["company_name"])
    op.create_index("ix_z_rate_service_key", "z_rate_service", ["service_key"])
    op.create_index("ix_z_rate_service_name", "z_rate_service", ["service_name"])
    op.create_index(
        "uq_z_rate_service_source_company_service_key",
        "z_rate_service",
        ["source", "company_name", "service_key"],
        unique=True,
    )
    op.create_index(
        "uq_z_rate_service_source_service_key",
        "z_rate_service",
        ["source", "service_key"],
        unique=True,
    )

    # IMPORTANT: clean up any old unique indexes from prior attempts
    op.execute("DROP INDEX IF EXISTS uq_z_rate_service_source_service_key;")

    

    # -----------------------------
    # z_rate_override
    # -----------------------------
    op.create_table(
        "z_rate_override",
        sa.Column("z_rate_override_id", sa.Integer, primary_key=True),
        sa.Column(
            "z_rate_service_id",
            sa.Integer,
            sa.ForeignKey("z_rate_service.z_rate_service_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("effective_during", postgresql.DATERANGE, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("override_rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.execute("""
    ALTER TABLE z_rate_override
      ADD CONSTRAINT ex_z_rate_override_no_overlap
      EXCLUDE USING gist (
        z_rate_service_id WITH =,
        effective_during WITH &&
      );
    """)

    op.create_index("ix_z_rate_override_service", "z_rate_override", ["z_rate_service_id"])
    op.create_index("ix_z_rate_override_during", "z_rate_override", ["effective_during"])

    # -----------------------------
    # ride  (summary page depends on it!)
    # -----------------------------
    op.create_table(
        "ride",
        sa.Column("ride_id", sa.BigInteger, primary_key=True),
        sa.Column(
            "payroll_batch_id",
            sa.Integer,
            sa.ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "person_id",
            sa.Integer,
            sa.ForeignKey("person.person_id", ondelete="RESTRICT"),
            nullable=False,
        ),

        # Add source so uniqueness can be per-source
        sa.Column("source", sa.Text, nullable=False),

        sa.Column("ride_start_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("service_ref", sa.Text),
        sa.Column("service_ref_type", sa.Text),
        sa.Column("service_name", sa.Text),

        sa.Column("z_rate", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("z_rate_source", sa.Text, nullable=False, server_default=sa.text("'default'")),
        sa.Column(
            "z_rate_service_id",
            sa.Integer,
            sa.ForeignKey("z_rate_service.z_rate_service_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "z_rate_override_id",
            sa.Integer,
            sa.ForeignKey("z_rate_override.z_rate_override_id", ondelete="SET NULL"),
            nullable=True,
        ),

        sa.Column("miles", sa.Numeric(10, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("gross_pay", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("net_pay", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("deduction", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("spiff", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),

        sa.Column("source_ref", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    # FIX: unique should NOT be only source_ref; make it (source, source_ref)
    op.execute("DROP INDEX IF EXISTS uq_ride_source_ref;")
    op.create_index("uq_ride_source_ref", "ride", ["source", "source_ref"], unique=True)

    op.create_index("ix_ride_batch_person", "ride", ["payroll_batch_id", "person_id"])
    op.create_index("ix_ride_person_date", "ride", ["person_id", "ride_start_ts"])
    op.create_index("ix_ride_service_name", "ride", ["service_name"])
    op.create_index("ix_ride_z_rate_ids", "ride", ["z_rate_service_id", "z_rate_override_id"])


def downgrade():
    # ---- ride (drop first because it depends on z_rate_* tables) ----
    op.drop_index("ix_ride_z_rate_ids", table_name="ride")
    op.drop_index("ix_ride_service_name", table_name="ride")
    op.drop_index("ix_ride_person_date", table_name="ride")
    op.drop_index("ix_ride_batch_person", table_name="ride")
    op.drop_index("uq_ride_source_ref", table_name="ride")
    op.drop_table("ride")

    # ---- z_rate_override ----
    op.drop_index("ix_z_rate_override_during", table_name="z_rate_override")
    op.drop_index("ix_z_rate_override_service", table_name="z_rate_override")
    op.execute(
        "ALTER TABLE z_rate_override DROP CONSTRAINT IF EXISTS ex_z_rate_override_no_overlap;"
    )
    op.drop_table("z_rate_override")

    # ---- z_rate_service ----
    # Drop the UNIQUE CONSTRAINT before dropping the table
    op.drop_constraint(
        "uq_z_rate_service_scope_service_name",
        "z_rate_service",
        type_="unique",
    )

    op.drop_index("ix_z_rate_service_name", table_name="z_rate_service")
    op.drop_index("ix_z_rate_service_key", table_name="z_rate_service")
    op.drop_index("ix_z_rate_service_company", table_name="z_rate_service")
    op.drop_table("z_rate_service")

    # ---- payroll_batch ----
    op.drop_index("ix_payroll_batch_period", table_name="payroll_batch")
    op.drop_index("ix_payroll_batch_source_company_uploaded", table_name="payroll_batch")
    op.drop_table("payroll_batch")

    # ---- person ----
    op.drop_index("uq_person_name_when_no_ext", table_name="person")
    op.drop_index("uq_person_external_id", table_name="person")
    op.drop_table("person")
