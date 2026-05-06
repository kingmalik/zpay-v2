"""add default_rate_source to z_rate_service

Revision ID: zq5r6s7t8u9v
Revises: zp4q5r6s7t8u
Create Date: 2026-05-06

Adds a nullable text column `default_rate_source` to z_rate_service so the
importer can tag how each row's default_rate was populated:

  'imported'                — rate came from the import file
  'inherited_from_sibling'  — rate copied from a letter-suffix / numbered-neighbor
                              sibling (avoids a silent $0 phantom row)
  'unknown_route'           — no sibling found; defaulted to $0 (needs manual pricing)
  'manual'                  — set via the admin rates UI

Existing rows (pre-migration) are left as NULL — they were inserted before this
column existed and their rate provenance is unknown.  NULL means "pre-dating this
feature", not "error".
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "zq5r6s7t8u9v"
down_revision: Union[str, None] = "zp4q5r6s7t8u"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "z_rate_service",
        sa.Column("default_rate_source", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("z_rate_service", "default_rate_source")
