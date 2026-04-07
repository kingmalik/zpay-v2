"""
SECURITY: wipe and drop tin + license_number columns from person table.
These columns contained SSN data that must be permanently removed.

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-04-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "n4o5p6q7r8s9"
down_revision: Union[str, Sequence[str], None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # First wipe all data (defense in depth — even if drop fails, data is gone)
    op.execute("UPDATE person SET tin = NULL, license_number = NULL")
    # Then drop the columns entirely
    op.drop_column("person", "tin")
    op.drop_column("person", "license_number")


def downgrade():
    # Do NOT restore these columns — SSN data must never be re-added
    pass
