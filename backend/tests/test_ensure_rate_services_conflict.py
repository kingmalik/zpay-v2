"""
Regression: FirstAlt upload failed on 2026-09-29 with
  InvalidColumnReference: there is no unique or exclusion constraint matching
  the ON CONFLICT specification
because migration s14 made uq_z_rate_service_scope PARTIAL (WHERE active) and
added an expression index on the canonical service name, while
ensure_rate_services still targeted the old full (source, company_name,
service_name) index.

The statement-shape test runs everywhere. The Postgres test runs only when
ZPAY_TEST_PG_URL points at a THROWAWAY database (never prod).
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from backend.db import crud
from backend.db.models import ZRateService

PG_URL = os.environ.get("ZPAY_TEST_PG_URL")

CANON_INDEX_SQL = (
    "CREATE UNIQUE INDEX uq_z_rate_service_source_canon_name_active "
    "ON z_rate_service (source, lower(regexp_replace(service_name, '\\s+', ' ', 'g'))) "
    "WHERE active = true"
)


def test_upsert_statement_has_no_conflict_target(monkeypatch):
    captured = {}

    class FakeDB:
        def execute(self, stmt):
            captured["sql"] = str(stmt.compile(dialect=postgresql.dialect()))

    monkeypatch.setattr(crud, "_find_sibling_rate", lambda *a, **k: None)
    crud.ensure_rate_services(
        FakeDB(),
        [{"service_name": "Route 1", "service_key": "k1"}],
        source="acumen",
        company_name="Acumen International",
    )
    assert "ON CONFLICT DO NOTHING" in captured["sql"]


@pytest.fixture
def pg_session():
    if not PG_URL:
        pytest.skip("ZPAY_TEST_PG_URL not set")
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS z_rate_service CASCADE"))
    ZRateService.__table__.create(engine)
    with engine.begin() as conn:
        conn.execute(text(CANON_INDEX_SQL))
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS z_rate_service CASCADE"))


def _rows(session):
    return session.execute(
        text("SELECT company_name, service_name, default_rate, active FROM z_rate_service ORDER BY 1, 2")
    ).all()


def test_reupload_against_partial_indexes_keeps_existing_rate(pg_session):
    pg_session.add(ZRateService(
        source="acumen", company_name="FirstAlt", service_key="old",
        service_name="Alderwood OB 03", currency="USD", default_rate=85, active=True,
    ))
    # soft-merged loser sharing the scope triple of the upload
    pg_session.add(ZRateService(
        source="acumen", company_name="Acumen International", service_key="dup",
        service_name="Alderwood OB 03", currency="USD", default_rate=40, active=False,
    ))
    pg_session.commit()

    crud.ensure_rate_services(
        pg_session,
        [
            {"service_name": "Alderwood OB 03", "service_key": "k1"},   # label differs
            {"service_name": "Alderwood  OB 03", "service_key": "k2"},  # whitespace variant
            {"service_name": "Brand New Route 07", "service_key": "k3"},
        ],
        source="acumen",
        company_name="Acumen International",
    )
    pg_session.commit()

    active = [r for r in _rows(pg_session) if r.active]
    names = sorted(r.service_name for r in active)
    assert names == ["Alderwood OB 03", "Brand New Route 07"]
    kept = next(r for r in active if r.service_name == "Alderwood OB 03")
    assert float(kept.default_rate) == 85
