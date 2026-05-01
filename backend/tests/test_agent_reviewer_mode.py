"""
Tests for reviewer mode — read-only payroll batch sanity checks.

Strategy: SQLite in-memory DB with fixture data (no Railway, no Anthropic).
Each tool is tested in isolation.  A routing test verifies that
mode='reviewer' exposes reviewer tools (not dispatcher tools) to run_agent.

Hard invariant: NO tool in reviewer_tools.py may call db.commit().
This is enforced by a _CommitGuard that raises if commit() is called.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

# Import models so their registrations land in Base.metadata before patching.
from backend.db.models import Base, DriverBalance, PayrollBatch, Person, Ride  # noqa: E402

# ── Metadata patches (same pattern as test_manual_adjustments.py) ─────────────

# Patch 1: DATERANGE is PostgreSQL-only — replace with Text for SQLite
Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()

# Patch 2: BigInteger PKs aren't autoincrement-capable in SQLite; use Integer
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()

# Patch 3: NOW() server_defaults don't exist in SQLite — nullify them
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.server_default is not None:
            _sd = _col.server_default
            try:
                _arg = _sd.arg.text if hasattr(_sd, "arg") and hasattr(_sd.arg, "text") else ""
            except Exception:
                _arg = ""
            if "NOW()" in _arg:
                _col.nullable = True
                _col.server_default = None

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_engine)

_SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db() -> Session:  # type: ignore[type-arg]
    """Fresh session per test; rolls back after each test."""
    session = _SessionLocal()
    yield session
    session.rollback()
    session.close()


# ─── DB object builders ────────────────────────────────────────────────────────

def _make_person(
    db: Session,
    person_id: int,
    name: str,
    paycheck_code: str | None = "1001",
    paycheck_code_maz: str | None = None,
    active: bool = True,
) -> Person:
    p = Person(
        person_id=person_id,
        full_name=name,
        active=active,
        paycheck_code=paycheck_code,
        paycheck_code_maz=paycheck_code_maz,
    )
    db.add(p)
    return p


def _make_batch(
    db: Session,
    batch_id: int,
    source: str = "acumen",
    status: str = "payroll_review",
) -> PayrollBatch:
    b = PayrollBatch(
        payroll_batch_id=batch_id,
        source=source,
        company_name="Test Co",
        currency="USD",
        status=status,
    )
    db.add(b)
    return b


def _make_ride(
    db: Session,
    ride_id: int,
    batch_id: int,
    person_id: int,
    z_rate: float = 100.0,
    gross_pay: float = 120.0,
    net_pay: float = 100.0,
    source: str = "acumen",
    source_ref: str | None = None,
) -> Ride:
    r = Ride(
        ride_id=ride_id,
        payroll_batch_id=batch_id,
        person_id=person_id,
        z_rate=Decimal(str(z_rate)),
        gross_pay=Decimal(str(gross_pay)),
        net_pay=Decimal(str(net_pay)),
        deduction=Decimal("0"),
        spiff=Decimal("0"),
        miles=Decimal("10"),
        source=source,
        source_ref=source_ref or f"ref-{ride_id}",
    )
    db.add(r)
    return r


# ─── Import tools under test ───────────────────────────────────────────────────

from backend.services.reviewer_tools import (  # noqa: E402
    REVIEWER_TOOLS,
    find_anomalous_drivers,
    find_missing_paycheck_codes,
    find_zero_rides_with_pay,
    review_batch_totals,
)


# ─── Read-only invariant helper ────────────────────────────────────────────────

class _CommitGuard:
    """Context manager that patches db.commit to raise if called."""

    def __init__(self, db: Session):
        self._db = db
        self._original = db.commit

    def __enter__(self):
        def _no_commit():
            raise AssertionError(
                "Reviewer tool called db.commit() — tools must be READ-ONLY"
            )
        self._db.commit = _no_commit  # type: ignore[method-assign]
        return self

    def __exit__(self, *_):
        self._db.commit = self._original  # type: ignore[method-assign]


# ─── review_batch_totals ──────────────────────────────────────────────────────

class TestReviewBatchTotals:

    def test_basic_summary(self, db: Session):
        _make_batch(db, 1, source="acumen")
        _make_person(db, 10, "Rahim Jama", paycheck_code="1001")
        _make_person(db, 11, "Dawit Tesfaye", paycheck_code="1002")
        _make_ride(db, 1, 1, 10, z_rate=200.0)
        _make_ride(db, 2, 1, 11, z_rate=150.0)
        db.flush()

        with _CommitGuard(db):
            result = review_batch_totals(db, 1)

        assert result["batch_id"] == 1
        assert result["driver_count"] == 2
        assert Decimal(result["total_pay"]) == Decimal("350.00")
        assert result["source"] == "acumen"

    def test_batch_not_found(self, db: Session):
        with _CommitGuard(db):
            result = review_batch_totals(db, 9999)
        assert "error" in result

    def test_wow_comparison_populated(self, db: Session):
        _make_batch(db, 20, source="acumen")
        _make_batch(db, 21, source="acumen")
        _make_person(db, 20, "Nuraynie Ali", paycheck_code="1010")
        _make_ride(db, 20, 20, 20, z_rate=300.0)
        _make_ride(db, 21, 21, 20, z_rate=200.0)
        db.flush()

        with _CommitGuard(db):
            result = review_batch_totals(db, 21)

        assert result["prior_batch_id"] == 20
        assert result["prior_batch_total"] is not None
        assert result["wow_change_pct"] is not None

    def test_no_rides_returns_zero_totals(self, db: Session):
        _make_batch(db, 30, source="acumen")
        db.flush()

        with _CommitGuard(db):
            result = review_batch_totals(db, 30)

        assert result["driver_count"] == 0
        assert result["total_pay"] == "0.00"

    def test_read_only_no_commit(self, db: Session):
        _make_batch(db, 40, source="maz")
        _make_person(db, 40, "Test Driver", paycheck_code_maz="2001")
        _make_ride(db, 40, 40, 40, z_rate=100.0, source="maz")
        db.flush()

        with _CommitGuard(db):
            # Must complete without tripping the commit guard
            review_batch_totals(db, 40)


# ─── find_anomalous_drivers ───────────────────────────────────────────────────

class TestFindAnomalousDrivers:

    def test_flags_large_deviation(self, db: Session):
        # Batches 50-53 = history; 54 = current (with anomaly)
        for bid in range(50, 55):
            _make_batch(db, bid, source="acumen")
        _make_person(db, 50, "Mamadou Diallo", paycheck_code="1020")
        # Historical weeks: $100 each
        for rid, bid in enumerate(range(50, 54), start=500):
            _make_ride(db, rid, bid, 50, z_rate=100.0)
        # This week: $500 — >50% deviation from $100 avg
        _make_ride(db, 510, 54, 50, z_rate=500.0)
        db.flush()

        with _CommitGuard(db):
            result = find_anomalous_drivers(db, 54)

        assert result["anomaly_count"] >= 1
        names = [a["driver"] for a in result["anomalies"]]
        assert "Mamadou Diallo" in names

    def test_no_anomaly_when_stable(self, db: Session):
        for bid in range(60, 65):
            _make_batch(db, bid, source="acumen")
        _make_person(db, 60, "Stable Driver", paycheck_code="1030")
        for rid, bid in enumerate(range(60, 64), start=600):
            _make_ride(db, rid, bid, 60, z_rate=100.0)
        # This week same $100
        _make_ride(db, 610, 64, 60, z_rate=100.0)
        db.flush()

        with _CommitGuard(db):
            result = find_anomalous_drivers(db, 64)

        assert result["anomaly_count"] == 0

    def test_batch_not_found(self, db: Session):
        with _CommitGuard(db):
            result = find_anomalous_drivers(db, 9998)
        assert "error" in result

    def test_read_only_no_commit(self, db: Session):
        _make_batch(db, 70, source="acumen")
        db.flush()
        with _CommitGuard(db):
            find_anomalous_drivers(db, 70)


# ─── find_missing_paycheck_codes ──────────────────────────────────────────────

class TestFindMissingPaychexCodes:

    def test_flags_driver_without_code(self, db: Session):
        _make_batch(db, 80, source="acumen")
        # No paycheck_code set
        _make_person(db, 80, "Ghost Driver", paycheck_code=None)
        _make_ride(db, 80, 80, 80, z_rate=150.0)
        db.flush()

        with _CommitGuard(db):
            result = find_missing_paycheck_codes(db, 80)

        assert result["missing_count"] >= 1
        names = [m["driver"] for m in result["missing"]]
        assert "Ghost Driver" in names

    def test_no_flag_when_code_present(self, db: Session):
        _make_batch(db, 81, source="acumen")
        _make_person(db, 81, "Coded Driver", paycheck_code="1099")
        _make_ride(db, 81, 81, 81, z_rate=200.0)
        db.flush()

        with _CommitGuard(db):
            result = find_missing_paycheck_codes(db, 81)

        assert result["missing_count"] == 0

    def test_maz_batch_checks_paycheck_code_maz(self, db: Session):
        _make_batch(db, 82, source="maz")
        # Has FA code but NOT Maz code — must be flagged for a Maz batch
        _make_person(db, 82, "Maz Ghost", paycheck_code="1099", paycheck_code_maz=None)
        _make_ride(db, 82, 82, 82, z_rate=100.0, source="maz")
        db.flush()

        with _CommitGuard(db):
            result = find_missing_paycheck_codes(db, 82)

        assert result["code_field_checked"] == "paycheck_code_maz"
        assert result["missing_count"] >= 1

    def test_zero_pay_driver_not_flagged(self, db: Session):
        _make_batch(db, 83, source="acumen")
        _make_person(db, 83, "Zero Pay Ghost", paycheck_code=None)
        _make_ride(db, 83, 83, 83, z_rate=0.0, gross_pay=0.0, net_pay=0.0)
        db.flush()

        with _CommitGuard(db):
            result = find_missing_paycheck_codes(db, 83)

        # $0 pay + missing code = no Paychex risk, must not be flagged
        assert result["missing_count"] == 0

    def test_read_only_no_commit(self, db: Session):
        _make_batch(db, 84, source="acumen")
        db.flush()
        with _CommitGuard(db):
            find_missing_paycheck_codes(db, 84)


# ─── find_zero_rides_with_pay ─────────────────────────────────────────────────

class TestFindZeroRidesWithPay:

    def test_flags_zero_rate_with_gross_pay(self, db: Session):
        _make_batch(db, 90, source="acumen")
        _make_person(db, 90, "Adjustment Driver", paycheck_code="1050")
        # z_rate=0 but gross_pay > 0 (manual adjustment scenario)
        _make_ride(db, 90, 90, 90, z_rate=0.0, gross_pay=75.0, net_pay=75.0)
        db.flush()

        with _CommitGuard(db):
            result = find_zero_rides_with_pay(db, 90)

        assert result["flagged_count"] >= 1
        names = [f["driver"] for f in result["flagged"]]
        assert "Adjustment Driver" in names

    def test_no_flag_when_normal(self, db: Session):
        _make_batch(db, 91, source="acumen")
        _make_person(db, 91, "Normal Driver", paycheck_code="1051")
        _make_ride(db, 91, 91, 91, z_rate=100.0, gross_pay=120.0)
        db.flush()

        with _CommitGuard(db):
            result = find_zero_rides_with_pay(db, 91)

        assert result["flagged_count"] == 0

    def test_batch_not_found(self, db: Session):
        with _CommitGuard(db):
            result = find_zero_rides_with_pay(db, 9997)
        assert "error" in result

    def test_read_only_no_commit(self, db: Session):
        _make_batch(db, 92, source="acumen")
        db.flush()
        with _CommitGuard(db):
            find_zero_rides_with_pay(db, 92)


# ─── Tool schema ───────────────────────────────────────────────────────────────

class TestReviewerToolSchema:

    def test_four_tools_defined(self):
        assert len(REVIEWER_TOOLS) == 4

    def test_tool_names(self):
        names = {t["name"] for t in REVIEWER_TOOLS}
        assert names == {
            "review_batch_totals",
            "find_anomalous_drivers",
            "find_missing_paycheck_codes",
            "find_zero_rides_with_pay",
        }

    def test_each_tool_has_batch_id_required(self):
        for tool in REVIEWER_TOOLS:
            schema = tool["input_schema"]
            assert "batch_id" in schema["properties"], (
                f"{tool['name']} missing batch_id property"
            )
            assert "required" in schema and "batch_id" in schema["required"], (
                f"{tool['name']} must require batch_id"
            )


# ─── Mode routing — reviewer gets reviewer tools, dispatcher does not ──────────

class TestModeRoutingToolSeparation:
    """
    Verify run_agent selects the correct tool set per mode without making
    a live Anthropic call.
    """

    def _run_with_captured_tools(self, mode: str, db: Session) -> list[dict]:
        """Patch anthropic so the first create() call captures tool list and returns end_turn."""
        captured: list[dict] = []

        class _FakeBlock:
            type = "text"
            text = "ok"

            def model_dump(self):
                return {"type": "text", "text": "ok"}

        class _FakeResp:
            stop_reason = "end_turn"
            content = [_FakeBlock()]

        def _fake_create(**kwargs):
            captured.extend(kwargs.get("tools", []))
            return _FakeResp()

        with patch("anthropic.Anthropic") as MockAnthropicClass:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = _fake_create
            MockAnthropicClass.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from backend.services.dispatch_agent import run_agent
                from backend.services.agent_modes import get_system_prompt

                run_agent(
                    db,
                    "check batch 1",
                    system_prompt=get_system_prompt(mode),
                    mode=mode,
                )

        return captured

    def test_reviewer_mode_exposes_reviewer_tools(self, db: Session):
        tools = self._run_with_captured_tools("reviewer", db)
        tool_names = {t["name"] for t in tools}
        assert "review_batch_totals" in tool_names
        assert "find_anomalous_drivers" in tool_names
        assert "find_missing_paycheck_codes" in tool_names
        assert "find_zero_rides_with_pay" in tool_names

    def test_reviewer_mode_does_not_expose_dispatcher_tools(self, db: Session):
        tools = self._run_with_captured_tools("reviewer", db)
        tool_names = {t["name"] for t in tools}
        assert "propose_reassignment" not in tool_names
        assert "search_rides" not in tool_names
        assert "list_drivers" not in tool_names

    def test_dispatcher_mode_does_not_expose_reviewer_tools(self, db: Session):
        tools = self._run_with_captured_tools("dispatcher", db)
        tool_names = {t["name"] for t in tools}
        assert "review_batch_totals" not in tool_names
        assert "find_missing_paycheck_codes" not in tool_names

    def test_dispatcher_mode_exposes_dispatcher_tools(self, db: Session):
        tools = self._run_with_captured_tools("dispatcher", db)
        tool_names = {t["name"] for t in tools}
        assert "propose_reassignment" in tool_names
        assert "search_rides" in tool_names
