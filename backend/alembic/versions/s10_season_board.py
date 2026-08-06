"""S10 season assignment board — school, season_ride, driver_loop + person.capabilities.

Revision ID: s10_season_board
Revises: s8c_partner_payment_external_ref
Create Date: 2026-08-06

Rationale (S10 — "Corridor Board + Loop Builder", docs/SEASON-BOARD-PLAN.md):
  Mom assigns ALL 2026-27 school-year rides to drivers this month. Rides pool
  as season_ride rows (via inbox auto-intake or sheet upload) with status
  unassigned; she batch-assigns from the board instead of a by-hand puzzle.

  - school: address book keyed off the route identity's school text.
    Filled once by mom, inherited by every ride at that school forever.
  - season_ride: one row per standing (season, source, route_school,
    route_direction, route_number, route_is_odt) identity — same dedupe
    grammar as route_roster/ride from route_identity.RouteIdentity.
  - driver_loop: the Loop Builder's output — a driver's standing weekly
    schedule. Rides link back via season_ride.loop_id.
  - person.capabilities: driver equipment/skill flags, checked against
    season_ride.requires when assigning loops (with manual override).

Online-safe:
  - New tables only, plus one ADD COLUMN ... NULL on person (metadata-only
    in Postgres, no table rewrite).
  - CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS guard re-runs.
  - Fully reversible via downgrade().
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "s10_season_board"
down_revision: Union[str, None] = "s8c_partner_payment_external_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE person
            ADD COLUMN IF NOT EXISTS capabilities JSONB
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS school (
            school_id       SERIAL PRIMARY KEY,
            name            TEXT NOT NULL UNIQUE,
            display_name    TEXT NOT NULL,
            address         TEXT,
            city            TEXT,
            district        TEXT,
            notes           TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS driver_loop (
            loop_id      SERIAL PRIMARY KEY,
            season       TEXT NOT NULL,
            label        TEXT NOT NULL,
            day_part     TEXT NOT NULL,
            days         TEXT,
            person_id    INTEGER REFERENCES person(person_id) ON DELETE SET NULL,
            status       TEXT NOT NULL DEFAULT 'proposed',
            origin       TEXT NOT NULL DEFAULT 'system',
            meta         JSONB DEFAULT '{}',
            created_at   TIMESTAMPTZ DEFAULT NOW(),
            updated_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_driver_loop_season_status
            ON driver_loop (season, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_driver_loop_person
            ON driver_loop (person_id)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS season_ride (
            season_ride_id      SERIAL PRIMARY KEY,
            season               TEXT NOT NULL DEFAULT '2026-27',
            source               TEXT NOT NULL DEFAULT 'firstalt',
            intake_id            INTEGER REFERENCES ride_intake(intake_id) ON DELETE SET NULL,
            route_school         TEXT NOT NULL,
            route_direction      TEXT NOT NULL,
            route_number         TEXT NOT NULL,
            route_is_odt         BOOLEAN NOT NULL DEFAULT false,
            school_id            INTEGER REFERENCES school(school_id) ON DELETE SET NULL,
            days                 TEXT,
            pickup_address       TEXT,
            dropoff_address      TEXT,
            pickup_city          TEXT,
            dropoff_city         TEXT,
            pickup_time          TEXT,
            dropoff_time         TEXT,
            miles                NUMERIC(6,1),
            net_pay              NUMERIC(8,2),
            requires             JSONB NOT NULL DEFAULT '{}',
            status               TEXT NOT NULL DEFAULT 'unassigned',
            assigned_person_id   INTEGER REFERENCES person(person_id) ON DELETE SET NULL,
            loop_id              INTEGER REFERENCES driver_loop(loop_id) ON DELETE SET NULL,
            loop_position        INTEGER,
            notes                TEXT,
            created_at           TIMESTAMPTZ DEFAULT NOW(),
            updated_at           TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_season_ride_identity UNIQUE (
                season, source, route_school, route_direction, route_number, route_is_odt
            )
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_season_ride_season_status
            ON season_ride (season, status)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS season_ride")
    op.execute("DROP TABLE IF EXISTS driver_loop")
    op.execute("DROP TABLE IF EXISTS school")
    op.execute("""
        ALTER TABLE person
            DROP COLUMN IF EXISTS capabilities
    """)
