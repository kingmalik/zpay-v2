"""add health monitor tables (merges prior divergent heads)

Revision ID: h9i0j1k2l3m4
Revises: a6b7c8d9e0f1, a7b8c9d0e1f2, g7h8i9j0k1l2
Create Date: 2026-04-21
"""

from typing import Sequence, Union

from alembic import op


revision: str = "h9i0j1k2l3m4"
down_revision: Union[str, Sequence[str], None] = (
    "a6b7c8d9e0f1",
    "a7b8c9d0e1f2",
    "g7h8i9j0k1l2",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS health_check (
            check_name         TEXT PRIMARY KEY,
            status             TEXT NOT NULL DEFAULT 'unknown',
            last_checked_at    TIMESTAMPTZ,
            last_ok_at         TIMESTAMPTZ,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            latency_ms         INTEGER,
            detail             JSONB,
            enabled            BOOLEAN NOT NULL DEFAULT TRUE,
            muted_until        TIMESTAMPTZ
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS health_alert (
            alert_id     BIGSERIAL PRIMARY KEY,
            check_name   TEXT NOT NULL,
            severity     TEXT NOT NULL,
            message      TEXT NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at  TIMESTAMPTZ,
            acked_at     TIMESTAMPTZ,
            notified     JSONB
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_health_alert_created_at
        ON health_alert (created_at DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_health_alert_unresolved
        ON health_alert (check_name)
        WHERE resolved_at IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_health_alert_unresolved;")
    op.execute("DROP INDEX IF EXISTS ix_health_alert_created_at;")
    op.execute("DROP TABLE IF EXISTS health_alert;")
    op.execute("DROP TABLE IF EXISTS health_check;")
