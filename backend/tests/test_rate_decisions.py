"""
Rate decisions on the negative-margin table survive leaving the page.

Bug (Malik, 2026-09-23): on the workflow page's negative-margin table the
operator picks "Save rate (all batches)" / "Apply to this batch only" /
"Skip — rate is correct". The choice lived only in React state, so opening a
driver's stub and coming back re-rendered the table with every button again.

Now every choice is recorded per (batch, route[, ride]) in batch_rate_decision,
and payroll-preview returns it with each negative-margin row so the table
renders the decision after a remount.

Endpoints under test:
  PATCH  /api/data/workflow/{batch_id}/update-ride-rate   (records decision)
  PATCH  /api/data/workflow/{batch_id}/rate-decision      (dismiss)
  DELETE /api/data/workflow/{batch_id}/rate-decision      (undo)
  GET    /api/data/workflow/{batch_id}/payroll-preview    (decision attached)

DB strategy matches test_workflow_advance_admin_override.py (in-memory SQLite).
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from unittest.mock import patch
from sqlalchemy import BigInteger, Integer, Text, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-key-for-rate-decision-tests-32chars")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import (  # noqa: E402
    Base, BatchRateDecision, PayrollBatch, Person, Ride, ZRateService,
)

Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.server_default is not None:
            try:
                _arg = (
                    _col.server_default.arg.text
                    if hasattr(_col.server_default, "arg") and hasattr(_col.server_default.arg, "text")
                    else ""
                )
            except Exception:
                _arg = ""
            if "NOW()" in _arg:
                _col.nullable = True
                _col.server_default = None

_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(_engine)
# payroll-preview reads two raw-SQL tables that have no ORM model.
with _engine.begin() as _conn:
    _conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS payroll_withheld_override (batch_id INTEGER NOT NULL, person_id INTEGER NOT NULL, PRIMARY KEY (batch_id, person_id))"
    )
    _conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS payroll_manual_withhold (person_id INTEGER PRIMARY KEY, note TEXT, created_at TEXT)"
    )
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

from fastapi.testclient import TestClient  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.routes import workflow as workflow_routes  # noqa: E402
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

_OPERATOR_COOKIE = create_session(
    username="testoperator", display_name="Test Operator", color="#666", initials="TO", role="operator", user_id=2,
)
client = TestClient(app, raise_server_exceptions=True)
client.cookies.set(COOKIE_NAME, _OPERATOR_COOKIE)

ROUTE = "Serene ES IB 01"
_EMPTY_TOTALS = {k: 0 for k in ("carried_over", "days", "deduction", "driver_pay", "miles", "net_pay", "partner_pays", "pay_this_period", "rides")}


def _seed():
    """One batch, one driver, two rides on ROUTE where driver rate > company rate."""
    with _SessionFactory() as db:
        for model in (BatchRateDecision, Ride, ZRateService, PayrollBatch, Person):
            db.query(model).delete(synchronize_session=False)
        db.commit()
        batch = PayrollBatch(status="payroll_review", source="acumen", company_name="FirstAlt",
                             week_start=date(2026, 9, 7), week_end=date(2026, 9, 11))
        person = Person(full_name="Abbas Driver", email="abbas@example.com", active=True)
        svc = ZRateService(source="acumen", company_name="FirstAlt", service_key="serene-es-ib-01", service_name=ROUTE, default_rate=Decimal("45.00"))
        db.add_all([batch, person, svc])
        db.commit()
        db.refresh(batch); db.refresh(person)
        rides = []
        for _ in range(2):
            r = Ride(payroll_batch_id=batch.payroll_batch_id, person_id=person.person_id, source="acumen",
                     source_ref=str(uuid.uuid4()), service_name=ROUTE, z_rate=Decimal("45.00"),
                     z_rate_source="default", gross_pay=Decimal("42.00"), net_pay=Decimal("42.00"),
                     deduction=Decimal("0"), spiff=Decimal("0"), miles=Decimal("10"))
            db.add(r); rides.append(r)
        db.commit()
        return batch.payroll_batch_id, [r.ride_id for r in rides]


def _negative_margin_rows(batch_id: int) -> list[dict]:
    # _build_summary is Postgres-only SQL (one-arg coalesce); the negative-margin
    # warning is built from ORM queries after it, which is what we test here.
    with patch.object(workflow_routes, "_build_summary", return_value={"rows": [], "totals": _EMPTY_TOTALS}):
        r = client.get(f"/api/data/workflow/{batch_id}/payroll-preview")
    assert r.status_code == 200, r.text
    warnings = [w for w in r.json()["warnings"] if w["type"] == "negative_margin"]
    return warnings[0]["affected"] if warnings else []


def _decisions(batch_id: int) -> list[BatchRateDecision]:
    with _SessionFactory() as db:
        return db.query(BatchRateDecision).filter_by(payroll_batch_id=batch_id).all()


class TestDecisionRecording:
    def test_route_save_is_recorded_and_returned_by_preview(self):
        batch_id, _ = _seed()
        r = client.patch(f"/api/data/workflow/{batch_id}/update-ride-rate",
                         json={"service_name": ROUTE, "z_rate": 44, "mode": "batch_only"})
        assert r.status_code == 200, r.text

        rows = _negative_margin_rows(batch_id)
        assert len(rows) == 1 and rows[0]["service_name"] == ROUTE  # still negative: 44 > 42
        assert rows[0]["decision"] == {"decision": "batch_only", "z_rate": 44.0}

    def test_permanent_save_recorded_as_default(self):
        batch_id, _ = _seed()
        client.patch(f"/api/data/workflow/{batch_id}/update-ride-rate",
                     json={"service_name": ROUTE, "z_rate": 43, "mode": "default"})
        rows = _negative_margin_rows(batch_id)
        assert rows[0]["decision"]["decision"] == "default"

    def test_single_ride_save_is_recorded_on_that_ride_only(self):
        batch_id, ride_ids = _seed()
        r = client.patch(f"/api/data/workflow/{batch_id}/update-ride-rate",
                         json={"ride_id": ride_ids[0], "z_rate": 43, "mode": "single_ride"})
        assert r.status_code == 200, r.text
        rows = _negative_margin_rows(batch_id)
        # route-level decision stays empty; the ride carries its own
        assert rows[0]["decision"] is None
        by_ride = {x["ride_id"]: x.get("decision") for x in rows[0]["rides"]}
        assert by_ride[ride_ids[0]] == {"decision": "single_ride", "z_rate": 43.0}
        assert by_ride[ride_ids[1]] is None

    def test_latest_route_decision_wins(self):
        batch_id, _ = _seed()
        client.patch(f"/api/data/workflow/{batch_id}/update-ride-rate",
                     json={"service_name": ROUTE, "z_rate": 44, "mode": "batch_only"})
        client.patch(f"/api/data/workflow/{batch_id}/update-ride-rate",
                     json={"service_name": ROUTE, "z_rate": 43, "mode": "default"})
        route_rows = [d for d in _decisions(batch_id) if d.ride_id is None]
        assert len(route_rows) == 1
        assert route_rows[0].decision == "default" and float(route_rows[0].z_rate) == 43.0


class TestDismissAndUndo:
    def test_dismiss_persists_and_preview_marks_it(self):
        batch_id, _ = _seed()
        r = client.patch(f"/api/data/workflow/{batch_id}/rate-decision",
                         json={"service_name": ROUTE, "decision": "dismissed"})
        assert r.status_code == 200, r.text
        rows = _negative_margin_rows(batch_id)
        assert rows[0]["decision"] == {"decision": "dismissed", "z_rate": None}

    def test_undo_clears_the_decision(self):
        batch_id, _ = _seed()
        client.patch(f"/api/data/workflow/{batch_id}/rate-decision",
                     json={"service_name": ROUTE, "decision": "dismissed"})
        r = client.delete(f"/api/data/workflow/{batch_id}/rate-decision", params={"service_name": ROUTE}, headers={"Accept": "application/json"})
        assert r.status_code == 200, r.text
        assert _negative_margin_rows(batch_id)[0]["decision"] is None
        assert _decisions(batch_id) == []

    def test_only_dismissed_is_accepted_here(self):
        batch_id, _ = _seed()
        r = client.patch(f"/api/data/workflow/{batch_id}/rate-decision",
                         json={"service_name": ROUTE, "decision": "default"})
        assert r.status_code == 400

    def test_unknown_batch_is_404(self):
        r = client.patch("/api/data/workflow/999999/rate-decision",
                         json={"service_name": ROUTE, "decision": "dismissed"})
        assert r.status_code == 404
