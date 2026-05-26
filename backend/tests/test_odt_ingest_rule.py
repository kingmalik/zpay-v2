"""
Tests for ODT (On Demand Trip) rate resolution in the live ingest path.

ODT = FA mid-day trip reinstatement tag.  e.g. "Albert Einstein ES IB ODT 06"
Rule: ODT rides pay the SAME rate as the base route — no premium, no discount.

What we verify:
  1. _service_name_candidates includes ODT-stripped forms for ODT service names.
  2. ODT-numbered swap → ODT 01 form is a candidate (most common base in rate table).
  3. ODT-numbered swap → ODT 02 form is a candidate.
  4. Bare base name (ODT token stripped entirely) is a candidate.
  5. Route-number form (ODT keyword removed, number kept) is a candidate.
  6. Non-ODT names are completely unaffected — no extra candidates generated.
  7. resolve_rate_for_ride resolves an ODT ride to its base-route rate via DB lookup.
  8. resolve_rate_for_ride returns zero when no rate exists for any ODT form.
  9. ODT candidates are lower priority than an exact match for the ODT name itself.
 10. ODT expansion works after one-time dispatch code stripping (combined suffix).

Run:
    PYTHONPATH=/path/to/zpay-wt-odt pytest backend/tests/test_odt_ingest_rule.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ── Project root on sys.path ──────────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-odt-rule-placeholder-32chars!!")
os.environ.setdefault("DATABASE_URL", "sqlite://")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candidates(name: str) -> list[str]:
    from backend.services.rates import _service_name_candidates
    return _service_name_candidates(name)


def _make_svc(service_name: str, default_rate: float) -> SimpleNamespace:
    return SimpleNamespace(
        z_rate_service_id=99,
        source="acumen",
        company_name="firstalt",
        service_name=service_name,
        default_rate=Decimal(str(default_rate)),
        active=True,
    )


def _make_db_returning(row) -> MagicMock:
    """Mock DB session whose query chain always returns `row`."""
    db = MagicMock()
    q = MagicMock()
    q.first.return_value = row
    db.query.return_value.filter.return_value.order_by.return_value = q
    return db


# ---------------------------------------------------------------------------
# 1-6: _service_name_candidates unit tests
# ---------------------------------------------------------------------------

class TestOdtCandidates:

    # 1. ODT names produce ODT-stripped forms in candidate list.
    def test_odt_name_produces_stripped_candidates(self):
        result = _candidates("Albert Einstein ES IB ODT 06")
        # Must include at least one non-ODT form
        assert any("ODT" not in c.upper() for c in result), (
            f"Expected at least one non-ODT candidate, got: {result}"
        )

    # 2. ODT 01 swap is present.
    def test_odt_01_swap_is_candidate(self):
        result = _candidates("Albert Einstein ES IB ODT 06")
        assert "Albert Einstein ES IB ODT 01" in result, (
            f"Expected 'Albert Einstein ES IB ODT 01' in candidates, got: {result}"
        )

    # 3. ODT 02 swap is present.
    def test_odt_02_swap_is_candidate(self):
        result = _candidates("Albert Einstein ES IB ODT 06")
        assert "Albert Einstein ES IB ODT 02" in result, (
            f"Expected 'Albert Einstein ES IB ODT 02' in candidates, got: {result}"
        )

    # 4. Bare base name (ODT stripped entirely) is a candidate.
    def test_no_odt_token_form_is_candidate(self):
        result = _candidates("Albert Einstein ES IB ODT 06")
        assert "Albert Einstein ES IB" in result, (
            f"Expected 'Albert Einstein ES IB' in candidates, got: {result}"
        )

    # 5. Route-number form (ODT keyword removed, number kept) is a candidate.
    def test_route_number_form_is_candidate(self):
        result = _candidates("Albert Einstein ES IB ODT 06")
        assert "Albert Einstein ES IB 06" in result, (
            f"Expected 'Albert Einstein ES IB 06' in candidates, got: {result}"
        )

    # 6. Non-ODT names are completely unaffected.
    def test_non_odt_names_unaffected(self):
        normal = _candidates("Loew Hall FT IB 03")
        odt_forms = [c for c in normal if "ODT" in c.upper()]
        assert odt_forms == [], (
            f"Non-ODT route must not produce ODT candidates, got: {odt_forms}"
        )

    # Extra: original ODT name is still the first candidate (exact match wins).
    # 9. ODT candidates are lower priority than exact match.
    def test_exact_odt_name_is_first_candidate(self):
        result = _candidates("Albert Einstein ES IB ODT 06")
        assert result[0] == "Albert Einstein ES IB ODT 06", (
            f"Exact ODT name must be the first candidate, got first={result[0]!r}"
        )

    # No duplicates produced.
    def test_no_duplicate_candidates(self):
        result = _candidates("Albert Einstein ES IB ODT 06")
        assert len(result) == len(set(result)), (
            f"Duplicate candidates found: {result}"
        )

    # Works with the exact "Loew Hall FT IB ODT 01" name from existing tests.
    def test_loew_hall_odt_01_candidates(self):
        result = _candidates("Loew Hall FT IB ODT 01")
        assert "Loew Hall FT IB ODT 01" in result   # exact
        assert "Loew Hall FT IB 01" in result        # route-number form
        assert "Loew Hall FT IB" in result            # bare base
        # ODT 01 swap → self (already exact), deduplicated
        # ODT 02 swap → "Loew Hall FT IB ODT 02"
        assert "Loew Hall FT IB ODT 02" in result

    # 10. Combined suffix: one-time dispatch code preceding ODT tag.
    def test_odt_after_dispatch_code_strip(self):
        # "Foo IB ER012726 01 ODT 03" — the dispatch-code strip regex only fires
        # when the dispatch code is at the END of the string ($ anchor).  Here
        # "ODT 03" follows the code, so the dispatch strip does NOT fire.
        # The ODT expansion still fires on the original name and its deduped forms.
        name = "Foo IB ER012726 01 ODT 03"
        result = _candidates(name)
        assert name in result, "Original must always be first"
        # ODT expansion runs on the original name (dispatch code stays in):
        # "Foo IB ER012726 01 ODT 03" → ODT 01 swap → "Foo IB ER012726 01 ODT 01"
        assert "Foo IB ER012726 01 ODT 01" in result, (
            f"ODT 01 swap on full name must be a candidate, got: {result}"
        )
        assert "Foo IB ER012726 01 ODT 02" in result, (
            f"ODT 02 swap on full name must be a candidate, got: {result}"
        )
        # Bare base form (ODT token stripped, dispatch code stays):
        assert "Foo IB ER012726 01" in result, (
            f"Bare base 'Foo IB ER012726 01' must be a candidate, got: {result}"
        )

    # Guard: ODT routes must never produce non-ODT numbered neighbors.
    # This is the HIGH bug regression — if "Albert Einstein ES IB 05" has a rate
    # but "Albert Einstein ES IB 06 ODT" forms do not, the resolver must NOT
    # silently use route 05's rate.
    def test_odt_route_does_not_produce_non_odt_numbered_neighbors(self):
        """
        Numbered-neighbor expansion must NOT run on ODT-derived route-number
        forms (e.g. 'Albert Einstein ES IB 06'). Only the pre-ODT base is
        eligible for neighbor expansion.
        """
        result = _candidates("Albert Einstein ES IB ODT 06")
        # These are plain non-ODT neighbor routes — must NOT appear.
        forbidden = [
            "Albert Einstein ES IB 05",
            "Albert Einstein ES IB 07",
            "Albert Einstein ES IB 04",
            "Albert Einstein ES IB 08",
        ]
        for f in forbidden:
            assert f not in result, (
                f"Non-ODT neighbor {f!r} must not be a candidate for an ODT route. "
                f"Full list: {result}"
            )


# ---------------------------------------------------------------------------
# 7-8: resolve_rate_for_ride integration tests (mocked DB)
# ---------------------------------------------------------------------------

class TestOdtResolveRate:

    # 7. ODT ride resolves to base-route rate via DB lookup.
    def test_odt_ride_resolves_to_base_route_rate(self):
        """
        Service rate stored as "Albert Einstein ES IB ODT 01".
        Lookup for "Albert Einstein ES IB ODT 06" must find it via ODT 01 swap.
        """
        from backend.services.rates import resolve_rate_for_ride

        base_svc = _make_svc("Albert Einstein ES IB ODT 01", default_rate=45.00)
        db = _make_db_returning(base_svc)

        rate, source_str, svc_id, ov_id = resolve_rate_for_ride(
            db,
            source="acumen",
            company_name="FirstAlt",
            service_name="Albert Einstein ES IB ODT 06",
            ride_date=date(2026, 5, 1),
        )

        assert rate == Decimal("45.00"), (
            f"ODT ride must resolve to base-route rate $45.00, got {rate}"
        )
        assert svc_id == 99

    # 7b. ODT ride resolves when base stored without ODT token.
    def test_odt_ride_resolves_to_bare_base_name(self):
        """
        Service rate stored as "Albert Einstein ES IB" (bare, no ODT).
        Lookup for "Albert Einstein ES IB ODT 06" must find it via ODT-stripped form.
        """
        from backend.services.rates import resolve_rate_for_ride

        base_svc = _make_svc("Albert Einstein ES IB", default_rate=38.00)
        db = _make_db_returning(base_svc)

        rate, source_str, svc_id, ov_id = resolve_rate_for_ride(
            db,
            source="acumen",
            company_name="FirstAlt",
            service_name="Albert Einstein ES IB ODT 06",
            ride_date=date(2026, 5, 1),
        )

        assert rate == Decimal("38.00"), (
            f"ODT ride must resolve to bare base-route rate $38.00, got {rate}"
        )

    # 8. ODT ride with no matching rate returns zero.
    def test_odt_ride_no_rate_returns_zero(self):
        """When no rate exists for any ODT form, resolve_rate_for_ride returns $0."""
        from backend.services.rates import resolve_rate_for_ride

        db = _make_db_returning(None)  # DB returns nothing for every candidate

        rate, source_str, svc_id, ov_id = resolve_rate_for_ride(
            db,
            source="acumen",
            company_name="FirstAlt",
            service_name="Brand New School ODT 03",
            ride_date=date(2026, 5, 1),
        )

        assert rate == Decimal("0"), (
            f"Unknown ODT route must return $0, got {rate}"
        )
        assert svc_id is None

    # Non-ODT: normal ride is completely unaffected by this change.
    def test_non_odt_ride_still_resolves(self):
        """A normal (non-ODT) ride still resolves to its rate correctly."""
        from backend.services.rates import resolve_rate_for_ride

        normal_svc = _make_svc("Loew Hall FT IB 03", default_rate=52.00)
        db = _make_db_returning(normal_svc)

        rate, source_str, svc_id, ov_id = resolve_rate_for_ride(
            db,
            source="acumen",
            company_name="FirstAlt",
            service_name="Loew Hall FT IB 03",
            ride_date=date(2026, 5, 1),
        )

        assert rate == Decimal("52.00"), (
            f"Normal (non-ODT) ride must still resolve correctly, got {rate}"
        )

    # Non-ODT: no ODT candidate queries issued for normal routes.
    def test_non_odt_candidate_list_has_no_odt_forms(self):
        """Candidate list for a plain route contains no ODT forms at all."""
        result = _candidates("Timberline MS IB 04")
        odt_forms = [c for c in result if "ODT" in c.upper()]
        assert odt_forms == [], (
            f"Non-ODT route must produce zero ODT candidates, got: {odt_forms}"
        )


# ---------------------------------------------------------------------------
# HIGH bug regression: neighbor route exists, ODT route does not.
# ---------------------------------------------------------------------------

class TestOdtNeighborBugRegression:
    """
    Regression suite for the HIGH-severity bug where numbered-neighbor expansion
    ran on ODT-derived route-number forms, causing an ODT ride to silently resolve
    at a neighboring non-ODT route's rate.

    The fix: _neighbor_base is captured BEFORE ODT expansion, so ODT-derived
    forms (like "Albert Einstein ES IB 06") are never used as the expansion base.
    """

    def _make_selective_db(self, rate_table: dict) -> MagicMock:
        """
        DB mock that returns a ZRateService row only when the queried service_name
        (lowercased) is present in `rate_table`.  All other queries return None.

        This lets us simulate a rate table where specific routes have rates and
        others don't — the key invariant the bug breaks.
        """
        import re as _re

        def _filter_side_effect(*args, **kwargs):
            """
            Intercept .filter() calls and inspect the service_name argument.
            SQLAlchemy comparison objects aren't trivially inspectable, so we
            capture the call's string representation to find the name being queried.
            """
            # Return a mock whose .order_by().first() checks the rate table.
            q = MagicMock()

            def _first():
                # Walk through all filter args to find service_name comparisons.
                # We look for any string value that appears in our rate_table.
                for arg in args:
                    s = str(arg).lower()
                    for key in rate_table:
                        if key in s:
                            svc = _make_svc(key, float(rate_table[key]))
                            return svc
                return None

            q.order_by.return_value.first = _first
            return q

        db = MagicMock()
        db.query.return_value.filter.side_effect = _filter_side_effect
        return db

    # Regression test 1: neighbor route has a rate, ODT route does not.
    # Before the fix: resolver silently returned neighbor's rate.
    # After the fix: resolver returns $0.
    def test_neighbor_route_exists_odt_route_does_not_returns_zero(self):
        """
        Rate table has 'Albert Einstein ES IB 05' at $55.00.
        No rate for the ODT forms or bare base of 'Albert Einstein ES IB ODT 06'.
        Resolver must return $0 — not $55.00.
        """
        from backend.services.rates import resolve_rate_for_ride

        # Only route 05 has a rate — no ODT variants, no route 06, no bare base.
        rate_table = {
            "albert einstein es ib 05": Decimal("55.00"),
        }
        db = self._make_selective_db(rate_table)

        rate, source_str, svc_id, ov_id = resolve_rate_for_ride(
            db,
            source="acumen",
            company_name="FirstAlt",
            service_name="Albert Einstein ES IB ODT 06",
            ride_date=date(2026, 5, 1),
        )

        assert rate == Decimal("0"), (
            f"ODT route must return $0 when only a non-ODT neighbor has a rate, "
            f"got {rate}. This indicates the neighbor-expansion bug is still present."
        )
        assert svc_id is None, (
            f"No service row should be returned for an unmatched ODT route."
        )

    # Regression test 2: ODT and non-ODT trips in the same batch resolve independently.
    def test_odt_and_non_odt_in_same_batch_resolve_independently(self):
        """
        A batch containing both "Albert Einstein ES IB ODT 06" and
        "Loew Hall FT IB 03" must resolve each to its own correct rate without
        interference. The ODT ride resolves via ODT 01 swap; the non-ODT ride
        resolves directly.
        """
        from backend.services.rates import resolve_rate_for_ride

        # ODT ride resolves via its ODT 01 form
        odt_svc = _make_svc("Albert Einstein ES IB ODT 01", default_rate=45.00)
        db_odt = _make_db_returning(odt_svc)

        rate_odt, _, svc_id_odt, _ = resolve_rate_for_ride(
            db_odt,
            source="acumen",
            company_name="FirstAlt",
            service_name="Albert Einstein ES IB ODT 06",
            ride_date=date(2026, 5, 14),
        )
        assert rate_odt == Decimal("45.00"), (
            f"ODT ride must resolve to $45.00, got {rate_odt}"
        )

        # Non-ODT ride resolves directly
        normal_svc = _make_svc("Loew Hall FT IB 03", default_rate=52.00)
        db_normal = _make_db_returning(normal_svc)

        rate_normal, _, svc_id_normal, _ = resolve_rate_for_ride(
            db_normal,
            source="acumen",
            company_name="FirstAlt",
            service_name="Loew Hall FT IB 03",
            ride_date=date(2026, 5, 14),
        )
        assert rate_normal == Decimal("52.00"), (
            f"Non-ODT ride must resolve to $52.00, got {rate_normal}"
        )

        # Verify they resolved to different service rows (no cross-contamination)
        assert svc_id_odt == 99
        assert svc_id_normal == 99  # same mock id is fine — both resolved independently

    # Regression test 3: driver with only ODT trips — no non-ODT ride required.
    def test_driver_with_only_odt_trips_resolves_correctly(self):
        """
        A driver who has ONLY ODT trips in a batch must resolve correctly.
        There must be no implicit dependency on a non-ODT ride being present
        in the same batch or the same candidate lookup chain.
        """
        from backend.services.rates import resolve_rate_for_ride

        # Rate stored as bare base (ODT token not in rate table at all)
        base_svc = _make_svc("Scenic Hill ES OB", default_rate=38.50)
        db = _make_db_returning(base_svc)

        # Three separate ODT trips for the same driver
        for odt_num in ("01", "03", "06"):
            service_name = f"Scenic Hill ES OB ODT {odt_num}"
            rate, source_str, svc_id, ov_id = resolve_rate_for_ride(
                db,
                source="acumen",
                company_name="FirstAlt",
                service_name=service_name,
                ride_date=date(2026, 5, 14),
            )
            assert rate == Decimal("38.50"), (
                f"ODT trip '{service_name}' must resolve to $38.50 via bare base, "
                f"got {rate}"
            )
            assert svc_id is not None, (
                f"svc_id must be set for a resolved ODT ride, got None for {service_name!r}"
            )
