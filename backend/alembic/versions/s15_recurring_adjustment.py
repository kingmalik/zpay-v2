"""add recurring_adjustment table + ride.recurring_adjustment_id

Revision ID: s15_recurring_adjustment
Revises: s14_dedupe_z_rate_service
Create Date: 2026-09-26

Bug (operator report, 2026-09-23): on a driver's paystub page, a manual
adjustment marked "Permanent" did not carry forward to the next payroll
batch. Root cause — the "Permanent" choice was never persisted anywhere.
POST /api/data/rides always wrote a single `ride` row scoped to the one
batch it was created on; nothing about "permanent" existed in the schema,
so batch generation (services/excell_reader.py, services/pdf_reader.py)
had nothing to read even if it had tried.

Fix: `recurring_adjustment` is the template row for a permanent adjustment.
It stays active until the operator removes it (never hard-deleted — removal
sets active=false + deactivated_at/by). `ride.recurring_adjustment_id`
links each batch's concrete, materialized copy back to its template so
generation can tell "already applied to this batch" from "not yet applied".

Both statements use CREATE TABLE / ADD COLUMN IF NOT EXISTS so this is
idempotent and safe to run against a DB that already has live driver data.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "s15_recurring_adjustment"
down_revision: Union[str, None] = "s14_dedupe_z_rate_service"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS recurring_adjustment (
            id               SERIAL PRIMARY KEY,
            person_id        INTEGER NOT NULL REFERENCES person(person_id) ON DELETE CASCADE,
            source           TEXT NOT NULL,
            service_name     TEXT NOT NULL,
            driver_pay       NUMERIC(12, 2) NOT NULL,
            miles            NUMERIC(10, 3) NOT NULL DEFAULT 0,
            reason           TEXT,
            notes            TEXT,
            active           BOOLEAN NOT NULL DEFAULT true,
            created_by       TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            deactivated_by   TEXT,
            deactivated_at   TIMESTAMPTZ,
            origin_batch_id  INTEGER REFERENCES payroll_batch(payroll_batch_id) ON DELETE SET NULL
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_recurring_adjustment_person_active
            ON recurring_adjustment (person_id, active)
        """
    )

    op.execute(
        """
        ALTER TABLE ride
            ADD COLUMN IF NOT EXISTS recurring_adjustment_id INTEGER
                REFERENCES recurring_adjustment(id) ON DELETE SET NULL
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ride_recurring_adjustment_batch
            ON ride (recurring_adjustment_id, payroll_batch_id)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ride DROP COLUMN IF EXISTS recurring_adjustment_id")
    op.execute("DROP TABLE IF EXISTS recurring_adjustment")
