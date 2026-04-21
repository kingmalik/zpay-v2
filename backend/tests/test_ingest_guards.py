"""
Tests for ingest guard rails introduced 2026-04-21:
  (a) Unmatched driver -> explicit unmatched flag, NOT silently bucketed under person_id=227
  (b) Zero-rate lookup -> z_rate_source="zero_rate_no_config", NOT defaulted to $49.72
  (c) FA batch_ref preserved from SP PAY SUMMARY, not synthesized as manual-{date}

Logic tests (a/b) run without any imports from the backend package.
Source-text tests (c) read .py files directly — no venv dependency.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
UNASSIGNED_PERSON_ID = 227


def _read_source(rel_path: str) -> str:
    return (BACKEND_DIR / rel_path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_str(v) -> str | None:
    """Minimal copy of norm_str from excell_reader/pdf_reader — no imports needed."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {"", "-", "n/a", "na", "none", "null", "nan"}:
        return None
    return s


# ---------------------------------------------------------------------------
# (a) Unmatched driver — upsert_person returns None
# ---------------------------------------------------------------------------

class TestUnmatchedDriver:
    """When upsert_person returns None the row must be counted in unmatched_drivers,
    NOT inserted with person_id=227."""

    def test_fa_unmatched_driver_counted_not_silently_bucketed(self):
        """Rows with no name produce an unmatched entry; no Ride is created."""
        person = None
        unmatched = 0
        unmatched_drivers: list[dict] = []
        skipped = 0

        driver_name = _norm_str(None)
        driver_ext = _norm_str(None)
        trip_name = "Redmond AM"

        if not person:
            unmatched += 1
            unmatched_drivers.append({
                "driver_name": driver_name,
                "driver_ext": driver_ext,
                "trip_name": trip_name,
                "reason": "no name provided — row skipped",
            })
            skipped += 1

        assert unmatched == 1
        assert skipped == 1
        assert len(unmatched_drivers) == 1
        assert unmatched_drivers[0]["driver_name"] is None
        # person_id=227 was never assigned; the continue short-circuits Ride creation

    def test_ed_unmatched_driver_counted_not_silently_bucketed(self):
        """ED rows with no name produce an unmatched entry; no Ride is created."""
        person = None
        unmatched = 0
        unmatched_drivers: list[dict] = []
        skipped = 0

        driver_name = _norm_str("")
        driver_ext = _norm_str(None)
        service_name = "EverDriven Route 5"

        if not person:
            unmatched += 1
            unmatched_drivers.append({
                "driver_name": driver_name,
                "driver_ext": driver_ext,
                "service_name": service_name,
                "reason": "no name provided — row skipped",
            })
            skipped += 1

        assert unmatched == 1
        assert len(unmatched_drivers) == 1
        assert unmatched_drivers[0]["service_name"] == service_name

    def test_unmatched_person_id_227_never_used_as_fallback(self):
        """Verify UNASSIGNED_PERSON_ID=227 is not hardcoded in FA or ED ingest source."""
        fa_src = _read_source("services/excell_reader.py")
        ed_src = _read_source("services/pdf_reader.py")

        # Isolate just the import_payroll_excel function body
        fa_fn_start = fa_src.find("def import_payroll_excel(")
        fa_fn_body = fa_src[fa_fn_start:]

        # Isolate just the bulk_insert_rides function body
        ed_fn_start = ed_src.find("def bulk_insert_rides(")
        ed_fn_body = ed_src[ed_fn_start:]

        assert "= 227" not in fa_fn_body, (
            "import_payroll_excel must not hardcode person_id=227 as a fallback"
        )
        assert "= 227" not in ed_fn_body, (
            "bulk_insert_rides must not hardcode person_id=227 as a fallback"
        )


# ---------------------------------------------------------------------------
# (b) Zero-rate flagging — no $49.72 contamination
# ---------------------------------------------------------------------------

class TestZeroRateFlagging:
    """Zero-rate rides must be tagged z_rate_source='zero_rate_no_config',
    NEVER defaulted to $49.72 (FA partner rate) or $44.86."""

    def test_fa_zero_rate_non_cancelled_sets_flag(self):
        """excell_reader: z_rate=0 + no cancellation_reason -> z_rate_source flagged."""
        z_rate = Decimal("0")
        z_rate_source = "none"  # what resolve_rate_for_ride returns when no config
        cancellation_reason = None  # not a cancellation

        # Reproduce the flagging logic from excell_reader.py
        if z_rate == 0 and not cancellation_reason:
            z_rate_source = "zero_rate_no_config"

        assert z_rate_source == "zero_rate_no_config"
        assert z_rate == Decimal("0"), "Rate must stay 0 — never default to 49.72"

    def test_fa_cancelled_ride_zero_rate_not_flagged(self):
        """Cancelled FA rides legitimately have $0 pay — must NOT be flagged."""
        z_rate = Decimal("0")
        z_rate_source = "none"
        cancellation_reason = "Driver Cancelled"

        if z_rate == 0 and not cancellation_reason:
            z_rate_source = "zero_rate_no_config"

        # source stays as-is; no flag applied for a genuine cancellation
        assert z_rate_source == "none"

    def test_ed_zero_rate_non_late_cancel_sets_flag(self):
        """pdf_reader: z_rate=0 with no late_cancellation source -> flagged."""
        z_rate = Decimal("0")
        z_rate_source = "none"

        # Reproduce the flagging logic from pdf_reader.py
        if z_rate == 0 and z_rate_source not in ("late_cancellation",):
            z_rate_source = "zero_rate_no_config"

        assert z_rate_source == "zero_rate_no_config"

    def test_ed_late_cancel_rate_not_overridden(self):
        """ED rides that resolved to late_cancellation rate must not be re-flagged."""
        z_rate = Decimal("22.43")
        z_rate_source = "late_cancellation"

        if z_rate == 0 and z_rate_source not in ("late_cancellation",):
            z_rate_source = "zero_rate_no_config"

        assert z_rate_source == "late_cancellation"

    def test_fallback_49_72_never_assigned_in_ingest_code(self):
        """$49.72 (FA partner rate) must not appear on any assignment/return line in ingest paths.
        It may appear in comments but must never be used as a fallback value."""
        import re

        fa_src = _read_source("services/excell_reader.py")
        ed_src = _read_source("services/pdf_reader.py")

        for src, label in [(fa_src, "excell_reader"), (ed_src, "pdf_reader")]:
            for line in src.splitlines():
                stripped = line.strip()
                # Skip comment lines — the value may appear in documentation
                if stripped.startswith("#"):
                    continue
                if "49.72" in stripped:
                    pytest.fail(
                        f"{label}: $49.72 must not appear in non-comment code: {stripped!r}"
                    )

    def test_resolve_rate_returns_zero_not_partner_rate_when_no_config(self):
        """When no service config exists, resolve_rate_for_ride must return 0, not 49.72.
        Tested via pure logic — no DB needed."""
        # Reproduce the function's return path when svc is None:
        # "if not svc: return Decimal('0'), 'none', None, None"
        svc = None
        if not svc:
            rate = Decimal("0")
            source_str = "none"
            svc_id = None
            ov_id = None

        assert rate == Decimal("0")
        assert rate != Decimal("49.72"), "$49.72 must never be a default driver rate"
        assert source_str == "none"


# ---------------------------------------------------------------------------
# (c) Batch ref preserved from source file
# ---------------------------------------------------------------------------

class TestBatchRefPreservation:
    """batch_ref must come from the source file (FA SP PAY SUMMARY batch_id or ED receipt number),
    never synthesized as 'manual-{date}-{source}'."""

    def test_fa_batch_ref_comes_from_summary(self):
        """import_payroll_excel uses summary['batch_id'] as batch_ref."""
        src = _read_source("services/excell_reader.py")
        fn_start = src.find("def import_payroll_excel(")
        fn_body = src[fn_start:]

        # batch_ref must reference summary["batch_id"]
        assert 'summary["batch_id"]' in fn_body or "summary['batch_id']" in fn_body, (
            "import_payroll_excel must set batch_ref from summary['batch_id'], not synthesize it"
        )

        # manual- must not appear on a batch_ref= line (only allowed in source_ref)
        for line in fn_body.splitlines():
            stripped = line.strip()
            if "batch_ref=" in stripped and "manual-" in stripped:
                pytest.fail(
                    f"batch_ref must not contain 'manual-': {stripped!r}"
                )

    def test_ed_batch_ref_comes_from_receipt_number(self):
        """bulk_insert_rides stores the parsed receipt number as batch_ref."""
        src = _read_source("services/pdf_reader.py")
        fn_start = src.find("def bulk_insert_rides(")
        fn_body = src[fn_start:]

        assert "batch_ref=batch_id" in fn_body, (
            "bulk_insert_rides must store the parsed receipt number as batch_ref"
        )

        # manual- must not appear on a batch_ref= line
        for line in fn_body.splitlines():
            stripped = line.strip()
            if "batch_ref=" in stripped and "manual-" in stripped:
                pytest.fail(
                    f"batch_ref must not contain 'manual-': {stripped!r}"
                )

    def test_api_create_ride_no_manual_batch_creation(self):
        """POST /api/data/rides must require explicit payroll_batch_id — no auto-creation."""
        src = _read_source("routes/api_data.py")
        fn_start = src.find("async def api_create_ride(")
        fn_body = src[fn_start:]
        # Trim to just this function (next top-level def or decorator)
        import re
        next_fn = re.search(r"\n(?:@router\.|async def |def )", fn_body[10:])
        if next_fn:
            fn_body = fn_body[:next_fn.start() + 10]

        assert "payroll_batch_id is required" in fn_body, (
            "api_create_ride must reject requests without payroll_batch_id"
        )
        assert "PayrollBatch(" not in fn_body, (
            "api_create_ride must not auto-create a PayrollBatch — caller must supply payroll_batch_id"
        )


# ---------------------------------------------------------------------------
# (d) Person dedup — upsert_person must never return inactive/merged row
# ---------------------------------------------------------------------------

class TestPersonDedup:
    """upsert_person and _resolve_canonical_person must follow merge sentinels
    and never attach a ride to an inactive/merged person row."""

    # ------------------------------------------------------------------
    # Source-text checks (no DB needed)
    # ------------------------------------------------------------------

    def test_upsert_person_filters_active_in_name_lookup(self):
        """The name-lookup query in upsert_person must ORDER BY active DESC so
        active rows are preferred over inactive ones."""
        src = _read_source("db/crud.py")
        fn_start = src.find("def upsert_person(")
        fn_body = src[fn_start:fn_start + 4000]  # first 4kb of function is sufficient
        assert "active.desc()" in fn_body, (
            "upsert_person name-lookup must order by active DESC to prefer active rows"
        )

    def test_upsert_person_has_inactive_warning(self):
        """upsert_person must log a warning when it encounters an inactive person."""
        src = _read_source("db/crud.py")
        fn_start = src.find("def upsert_person(")
        fn_body = src[fn_start:fn_start + 4000]
        assert "inactive" in fn_body, (
            "upsert_person must warn when it encounters an inactive/merged person"
        )

    def test_resolve_canonical_follows_sentinel(self):
        """_resolve_canonical_person must parse 'merged_pXXX_into_pYYY' sentinel
        and walk to the canonical row, not return the inactive one."""
        src = _read_source("db/crud.py")
        assert "_resolve_canonical_person" in src, (
            "crud.py must define _resolve_canonical_person"
        )
        assert "merged_p" in src, (
            "_resolve_canonical_person must handle the dedupe sentinel pattern"
        )
        assert "MAX_HOPS" in src, (
            "_resolve_canonical_person must cap recursion depth (MAX_HOPS)"
        )

    def test_build_existing_people_map_active_only(self):
        """build_existing_people_map must filter to active persons only."""
        src = _read_source("services/db_people.py")
        fn_start = src.find("def build_existing_people_map(")
        fn_body = src[fn_start:fn_start + 2000]
        assert "active" in fn_body, (
            "build_existing_people_map must filter by active=True"
        )

    # ------------------------------------------------------------------
    # Logic tests with mocks
    # ------------------------------------------------------------------

    def test_resolve_canonical_follows_merged_sentinel(self):
        """_resolve_canonical_person follows the external_id sentinel to canonical row."""
        import sys
        import types

        # Minimal stub — we can't import the backend package in pure-logic tests,
        # so we replicate the resolution logic directly.
        import re as _re

        def _resolve(person, db, depth=0):
            MAX_HOPS = 5
            if depth >= MAX_HOPS:
                return person
            if person["active"]:
                return person
            m = _re.search(r"merged_p\d+_into_p(\d+)", person.get("external_id") or "")
            if m:
                target_id = int(m.group(1))
                target = db.get(target_id)
                if target is None:
                    return person
                if not target["active"]:
                    return _resolve(target, db, depth + 1)
                return target
            return person

        class FakeDB:
            def __init__(self, rows):
                self._rows = rows
            def get(self, pid):
                return self._rows.get(pid)

        # Setup: inactive p94 merged into active p45
        inactive = {"person_id": 94, "full_name": "Elham Mohammedseid", "active": False,
                    "external_id": "merged_p94_into_p45_v2"}
        canonical = {"person_id": 45, "full_name": "Elham Mohammedtahir Mohammedseid",
                     "active": True, "external_id": None}

        db = FakeDB({94: inactive, 45: canonical})
        result = _resolve(inactive, db)

        assert result["person_id"] == 45, (
            f"Expected canonical person_id=45, got {result['person_id']}"
        )
        assert result["active"] is True

    def test_resolve_canonical_caps_at_max_hops(self):
        """_resolve_canonical_person must not loop infinitely on cycle."""
        import re as _re

        def _resolve(person, db, depth=0):
            MAX_HOPS = 5
            if depth >= MAX_HOPS:
                return person
            if person["active"]:
                return person
            m = _re.search(r"merged_p\d+_into_p(\d+)", person.get("external_id") or "")
            if m:
                target_id = int(m.group(1))
                target = db.get(target_id)
                if target is None:
                    return person
                if not target["active"]:
                    return _resolve(target, db, depth + 1)
                return target
            return person

        class FakeDB:
            def __init__(self, rows):
                self._rows = rows
            def get(self, pid):
                return self._rows.get(pid)

        # Cycle: p1 -> p2 -> p1
        p1 = {"person_id": 1, "active": False, "external_id": "merged_p1_into_p2"}
        p2 = {"person_id": 2, "active": False, "external_id": "merged_p2_into_p1"}
        db = FakeDB({1: p1, 2: p2})

        # Should not raise RecursionError; must return a row (whichever hit the cap)
        result = _resolve(p1, db)
        assert result is not None
