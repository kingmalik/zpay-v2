"""add uq_z_rate_service_scope unique index

Revision ID: z5a6b7c8d9e0
Revises: y4z5a6b7c8d9
Create Date: 2026-04-15
"""

from typing import Sequence, Union

from alembic import op


revision: str = "z5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "y4z5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deduplicate any rows that would violate the composite unique before creating it.
    op.execute("""
        DELETE FROM z_rate_service a
        USING z_rate_service b
        WHERE a.z_rate_service_id > b.z_rate_service_id
          AND a.source = b.source
          AND a.company_name = b.company_name
          AND a.service_name = b.service_name;
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_z_rate_service_scope
        ON z_rate_service (source, company_name, service_name);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_z_rate_service_scope;")
