"""pricing engine v2 — route identity on rides + shadow results table

Revision ID: s34_pricing_v2
Revises: s15_partner_payment
Create Date: 2026-07-09

Rationale (MASTER-PLAN §S2/S3, executed as sessions 3+4):
  - ride.route_* columns persist the parsed FA route identity
    (school / direction / number / odt-class) on every ride. Powers
    Pricing v2 resolution audits and unlocks student-continuity
    tracking for S5 driver assignment.
  - rate_shadow_result records, per ride per upload, what Pricing v2
    WOULD have priced next to what v1 actually did — the S3 shadow-mode
    evidence trail. One row per (ride, engine run).

Online-safe:
  - ADD COLUMN ... NULL on ride: metadata-only in Postgres, no rewrite.
  - Backfill runs as batched UPDATEs by service_name (550 distinct names).
  - New table only otherwise. Fully reversible.
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "s34_pricing_v2"
down_revision: Union[str, None] = "s15_partner_payment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ride
            ADD COLUMN IF NOT EXISTS route_school    text,
            ADD COLUMN IF NOT EXISTS route_direction text,
            ADD COLUMN IF NOT EXISTS route_number    text,
            ADD COLUMN IF NOT EXISTS route_is_odt    boolean
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_ride_route_identity
            ON ride (route_school, route_direction, route_number)
            WHERE route_school IS NOT NULL
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS rate_shadow_result (
            id               BIGSERIAL PRIMARY KEY,
            payroll_batch_id INTEGER NOT NULL REFERENCES payroll_batch(payroll_batch_id) ON DELETE CASCADE,
            ride_id          BIGINT REFERENCES ride(ride_id) ON DELETE CASCADE,
            service_name     TEXT NOT NULL,
            miles            NUMERIC(10,3),
            v1_rate          NUMERIC(12,2) NOT NULL,
            v1_source        TEXT NOT NULL,
            v2_rate          NUMERIC(12,2) NOT NULL,
            v2_tier          TEXT NOT NULL,
            v2_evidence      TEXT NOT NULL DEFAULT '',
            agrees           BOOLEAN NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_rate_shadow_batch
            ON rate_shadow_result (payroll_batch_id, created_at)
    """)

    # ── Backfill route identity for existing acumen rides ──────────────────
    # Parsing happens in Python (the route_identity module is the single
    # source of the grammar); one UPDATE per distinct service_name.
    from sqlalchemy import text as _text

    from backend.services.route_identity import parse_route_identity

    conn = op.get_bind()
    names = [
        r[0] for r in conn.execute(_text(
            "SELECT DISTINCT service_name FROM ride "
            "WHERE source = 'acumen' AND service_name IS NOT NULL"
        ))
    ]
    for name in names:
        ident = parse_route_identity(name)
        if ident is None:
            continue
        conn.execute(
            _text(
                "UPDATE ride SET route_school = :school, route_direction = :direction, "
                "route_number = :number, route_is_odt = :odt "
                "WHERE source = 'acumen' AND service_name = :name"
            ),
            {
                "school": ident.school,
                "direction": ident.direction,
                "number": ident.number,
                "odt": ident.is_odt,
                "name": name,
            },
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rate_shadow_result")
    op.execute("DROP INDEX IF EXISTS ix_ride_route_identity")
    op.execute("""
        ALTER TABLE ride
            DROP COLUMN IF EXISTS route_school,
            DROP COLUMN IF EXISTS route_direction,
            DROP COLUMN IF EXISTS route_number,
            DROP COLUMN IF EXISTS route_is_odt
    """)
