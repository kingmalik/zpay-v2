"""S5 assignment helper + coverage — rosters, backups, ride intake, home area/zip.

Revision ID: s5_assignment
Revises: s34_pricing_v2
Create Date: 2026-07-22

Rationale (S5 — Assignment Helper + Coverage):
  - person.home_area / home_zip: lightweight free-text home-location fields
    used as a scoring seam for driver-to-route proximity (v1 is
    presence/tie-break only — no geocoding yet).
  - route_roster: one row per recurring (source, school, direction, number,
    is_odt) identity — the standing "who normally drives this" + who's the
    backup roster, derived from ride history by coverage_service.sync_rosters.
  - route_backup: ranked backup drivers per roster row.
  - ride_intake: raw Brandon/FirstStudent emails for new rides, parsed
    best-effort by ride_intake_service, with a take/pass decision trail.

Online-safe:
  - ADD COLUMN ... NULL on person: metadata-only in Postgres, no rewrite.
  - New tables only otherwise. Fully reversible.
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "s5_assignment"
down_revision: Union[str, None] = "s34_pricing_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE person
            ADD COLUMN IF NOT EXISTS home_area text,
            ADD COLUMN IF NOT EXISTS home_zip  text
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS route_roster (
            roster_id            SERIAL PRIMARY KEY,
            source                TEXT NOT NULL,
            route_school          TEXT NOT NULL,
            route_direction       TEXT NOT NULL,
            route_number          TEXT NOT NULL,
            route_is_odt          BOOLEAN NOT NULL DEFAULT false,
            service_name_sample   TEXT,
            primary_person_id     INTEGER REFERENCES person(person_id),
            active                BOOLEAN NOT NULL DEFAULT true,
            last_seen_ride_ts     TIMESTAMPTZ,
            created_at            TIMESTAMPTZ DEFAULT NOW(),
            updated_at            TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_route_roster_identity UNIQUE (
                source, route_school, route_direction, route_number, route_is_odt
            )
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_route_roster_active
            ON route_roster (active)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS route_backup (
            backup_id      SERIAL PRIMARY KEY,
            roster_id      INTEGER NOT NULL REFERENCES route_roster(roster_id) ON DELETE CASCADE,
            person_id      INTEGER NOT NULL REFERENCES person(person_id),
            rank           SMALLINT NOT NULL,
            confirmed_by   TEXT,
            created_at     TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_route_backup_roster_rank UNIQUE (roster_id, rank),
            CONSTRAINT uq_route_backup_roster_person UNIQUE (roster_id, person_id)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS ride_intake (
            intake_id       SERIAL PRIMARY KEY,
            raw_text        TEXT NOT NULL,
            parsed          JSONB NOT NULL DEFAULT '{}',
            status          TEXT NOT NULL DEFAULT 'draft',
            decision_reason TEXT,
            reply_draft     TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            decided_at      TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_ride_intake_status
            ON ride_intake (status)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ride_intake")
    op.execute("DROP TABLE IF EXISTS route_backup")
    op.execute("DROP TABLE IF EXISTS route_roster")
    op.execute("""
        ALTER TABLE person
            DROP COLUMN IF EXISTS home_area,
            DROP COLUMN IF EXISTS home_zip
    """)
