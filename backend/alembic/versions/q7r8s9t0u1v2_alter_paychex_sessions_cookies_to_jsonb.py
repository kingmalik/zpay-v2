"""
Alter paychex_sessions: rename cookies_json (Text) to cookies (JSONB) for native JSON storage.

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-04-08
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "q7r8s9t0u1v2"
down_revision: Union[str, Sequence[str], None] = "p6q7r8s9t0u1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Add the new JSONB column
    op.add_column(
        "paychex_sessions",
        sa.Column("cookies", JSONB, nullable=True),
    )
    # Copy data from the old Text column, casting JSON string → JSONB
    op.execute("UPDATE paychex_sessions SET cookies = cookies_json::jsonb")
    # Make the new column non-nullable now that data is migrated
    op.alter_column("paychex_sessions", "cookies", nullable=False)
    # Drop the old column
    op.drop_column("paychex_sessions", "cookies_json")


def downgrade():
    # Re-add the text column
    op.add_column(
        "paychex_sessions",
        sa.Column("cookies_json", sa.Text(), nullable=True),
    )
    # Serialize JSONB back to text
    op.execute("UPDATE paychex_sessions SET cookies_json = cookies::text")
    op.alter_column("paychex_sessions", "cookies_json", nullable=False)
    op.drop_column("paychex_sessions", "cookies")
