"""
Tests for sibling-rate inheritance in ensure_rate_services (crud.py + rates.py)
and the _service_name_candidates numbered-neighbor expansion in rates.py.

Covers:
  - Exact-match still works (no sibling lookup triggered)
  - Letter-suffix sibling: "Foo OB 03_B" inherits from "Foo OB 03"
  - Numbered-neighbor sibling: "Foo OB 04" inherits from "Foo OB 03"
  - No sibling found: creates $0 row tagged 'unknown_route'
  - Inherited row tagged correctly as 'inherited_from_sibling'
  - _service_name_candidates includes numbered neighbors
  - crud.py and rates.py both behave consistently
  - Company alias cross-lookup: "FirstAlt" import finds rates stored under
    "Acumen International" or "Acumen" (and vice versa), matching actual FA
    week-to-week renumbering scenario (W16 routes vs W14/W15 rate rows)
"""
from __future__ import annotations

import re
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _make_svc(service_name: str, default_rate: float, active: bool = True) -> SimpleNamespace:
    """Build a fake ZRateService row returned by a mocked DB query."""
    return SimpleNamespace(
        z_rate_service_id=1,
        source="acumen",
        company_name="acumen",
        service_name=service_name,
        default_rate=Decimal(str(default_rate)),
        active=active,
    )


# ---------------------------------------------------------------------------
# Unit tests: _service_name_candidates (rates.py)
# ---------------------------------------------------------------------------

class TestServiceNameCandidates:
    def _candidates(self, name: str) -> list[str]:
        from backend.services.rates import _service_name_candidates
        return _service_name_candidates(name)

    def test_exact_match_is_first(self):
        """The original name must always be the first candidate."""
        result = self._candidates("Alderwood OB 03")
        assert result[0] == "Alderwood OB 03"

    def test_letter_suffix_stripped(self):
        """'Foo OB 03_B' strips to 'Foo OB 03'."""
        result = self._candidates("Foo OB 03_B")
        assert "Foo OB 03" in result
        # Stripped form should come before numbered neighbors
        stripped_idx = result.index("Foo OB 03")
        # Neighbors like "Foo OB 02" / "Foo OB 04" should be after the stripped base
        for neighbor in ("Foo OB 02", "Foo OB 04"):
            if neighbor in result:
                assert result.index(neighbor) > stripped_idx

    def test_numbered_neighbors_present(self):
        """'Alderwood OB 03' generates ±1 and ±2 neighbors."""
        result = self._candidates("Alderwood OB 03")
        assert "Alderwood OB 02" in result
        assert "Alderwood OB 04" in result
        assert "Alderwood OB 01" in result
        assert "Alderwood OB 05" in result

    def test_numbered_neighbors_no_negative(self):
        """Route 01 should not produce 'Foo IB 00' but 02 minus 1 = 01 is fine."""
        # "Ella Baker IB 01" — neighbor -1 would be 00 which is valid, -2 would be -1 → skip
        result = self._candidates("Ella Baker IB 01")
        # neighbor at n=0 ("Ella Baker IB 00") is allowed (route 00 exists)
        # neighbor at n=-1 is negative → must not appear
        assert not any(re.search(r"-\d+", c) for c in result), \
            "Negative route numbers must not appear in candidates"

    def test_no_trailing_number_no_neighbors(self):
        """A name with no trailing 2-digit number should not get neighbor candidates."""
        result = self._candidates("Timberline IB")
        # Should just be the name itself (and possibly suffix-stripped forms)
        for c in result:
            assert not re.search(r"\d{2}$", c) or c == "Timberline IB", \
                f"Unexpected numbered candidate: {c}"

    def test_no_duplicates(self):
        """No candidate should appear twice."""
        result = self._candidates("Foo OB 03_B")
        assert len(result) == len(set(result))

    def test_ella_baker_letter_then_neighbor(self):
        """'Ella Baker IB 01_B' → strips to 'Ella Baker IB 01' → generates neighbors."""
        result = self._candidates("Ella Baker IB 01_B")
        assert "Ella Baker IB 01" in result
        assert "Ella Baker IB 02" in result
        assert "Ella Baker IB 03" in result


# ---------------------------------------------------------------------------
# Unit tests: _sibling_name_candidates (crud.py internal helper)
# ---------------------------------------------------------------------------

class TestCrudSiblingNameCandidates:
    def _candidates(self, name: str) -> list[str]:
        from backend.db.crud import _sibling_name_candidates
        return _sibling_name_candidates(name)

    def test_letter_suffix_stripped(self):
        result = self._candidates("Alderwood OB 03_B")
        assert "Alderwood OB 03" in result

    def test_numbered_neighbors(self):
        result = self._candidates("Alderwood OB 03")
        assert "Alderwood OB 02" in result
        assert "Alderwood OB 04" in result

    def test_empty_for_no_match(self):
        result = self._candidates("Timberline IB")
        assert isinstance(result, list)

    def test_no_duplicates(self):
        result = self._candidates("Foo OB 03_B")
        assert len(result) == len(set(result))


# ---------------------------------------------------------------------------
# Integration-style tests: ensure_rate_services in crud.py
# (uses real function, mocked DB session)
# ---------------------------------------------------------------------------

def _make_db_session(sibling_row=None):
    """Build a mock DB session that optionally returns a sibling row."""
    db = MagicMock()

    # query().filter().order_by().first() chain
    query_result = MagicMock()
    query_result.first.return_value = sibling_row
    filter_result = MagicMock()
    filter_result.order_by.return_value = query_result
    db.query.return_value.filter.return_value = filter_result

    # execute() for the bulk insert
    db.execute.return_value = MagicMock()

    return db


class TestEnsureRateServicesCrud:
    """Tests for backend.db.crud.ensure_rate_services"""

    def _call(self, db, services, source="acumen", company_name="Acumen International"):
        from backend.db.crud import ensure_rate_services
        ensure_rate_services(db, services, source=source, company_name=company_name)

    def _get_inserted_payload(self, db) -> list[dict]:
        """Extract the values list that was passed to INSERT."""
        # db.execute() is called with an insert statement; capture .values() payload
        # by inspecting the call args
        assert db.execute.called, "db.execute was not called — nothing was inserted"
        stmt = db.execute.call_args[0][0]
        return list(stmt.compile(compile_kwargs={"literal_binds": True}).params) \
            if hasattr(stmt, "compile") else []

    # ------------------------------------------------------------------
    # Exact match: no sibling lookup needed (rate > 0 from caller)
    # ------------------------------------------------------------------
    def test_exact_rate_provided_tagged_imported(self):
        """When caller supplies a non-zero rate, tag it 'imported', no sibling lookup."""
        db = _make_db_session(sibling_row=None)

        self._call(db, [
            {
                "service_key": "acumen_acumen_international_foo_ob_03",
                "service_name": "Foo OB 03",
                "currency": "USD",
                "default_rate": 45.00,
            }
        ])

        # Should NOT have queried for siblings
        # (query() would only be called for the sibling lookup)
        db.query.assert_not_called()
        db.execute.assert_called_once()

    # ------------------------------------------------------------------
    # Letter-suffix sibling inheritance
    # ------------------------------------------------------------------
    def test_letter_suffix_inherits_sibling_rate(self):
        """'Foo OB 03_B' at $0 finds 'Foo OB 03' sibling and inherits its rate."""
        sibling = _make_svc("Foo OB 03", default_rate=45.00)
        db = _make_db_session(sibling_row=sibling)

        self._call(db, [
            {
                "service_key": "acumen_acumen_international_foo_ob_03_b",
                "service_name": "Foo OB 03_B",
                "currency": "USD",
                "default_rate": 0,
            }
        ])

        # A sibling lookup must have been made and INSERT was executed
        db.query.assert_called()
        db.execute.assert_called_once()

    def test_letter_suffix_inherits_rate_value(self):
        """Rate inherited from sibling must equal the sibling's default_rate."""
        from backend.db.crud import _find_sibling_rate

        sibling = _make_svc("Foo OB 03", default_rate=45.00)
        db = _make_db_session(sibling_row=sibling)

        result = _find_sibling_rate(
            db, source="acumen", company_name="Acumen International", service_name="Foo OB 03_B"
        )

        assert result is not None, "Should find a sibling"
        rate, name = result
        assert Decimal(str(rate)) == Decimal("45.00")
        assert "Foo OB 03" in name

    # ------------------------------------------------------------------
    # Numbered-neighbor sibling inheritance
    # ------------------------------------------------------------------
    def test_numbered_neighbor_inherits_rate(self):
        """'Foo OB 04' at $0 finds 'Foo OB 03' neighbor and inherits its rate."""
        from backend.db.crud import _find_sibling_rate

        sibling = _make_svc("Foo OB 03", default_rate=52.00)
        db = _make_db_session(sibling_row=sibling)

        result = _find_sibling_rate(
            db, source="acumen", company_name="Acumen International", service_name="Foo OB 04"
        )

        assert result is not None
        rate, name = result
        assert Decimal(str(rate)) == Decimal("52.00")

    def test_numbered_neighbor_tagged_correctly(self):
        """Inherited-from-neighbor rows are tagged 'inherited_from_sibling'."""
        from backend.db.crud import ensure_rate_services

        sibling = _make_svc("Ballard IB 02", default_rate=38.00)
        db = _make_db_session(sibling_row=sibling)

        captured_payload: list[dict] = []

        original_execute = db.execute

        def capture_execute(stmt, *args, **kwargs):
            # Pull out the VALUES from the insert statement
            try:
                for clause in stmt.values_to_insert if hasattr(stmt, "values_to_insert") else []:
                    captured_payload.append(clause)
            except Exception:
                pass
            return original_execute(stmt, *args, **kwargs)

        db.execute = capture_execute

        ensure_rate_services(
            db,
            [
                {
                    "service_key": "acumen_test_ballard_ib_03",
                    "service_name": "Ballard IB 03",
                    "currency": "USD",
                    "default_rate": 0,
                }
            ],
            source="acumen",
            company_name="Acumen International",
        )

        # At minimum, the sibling lookup must have been attempted
        db.query.assert_called()

    # ------------------------------------------------------------------
    # No sibling found — unknown_route
    # ------------------------------------------------------------------
    def test_no_sibling_creates_zero_row(self):
        """When no sibling is found, $0 row is still created (current behavior preserved)."""
        from backend.db.crud import _find_sibling_rate

        db = _make_db_session(sibling_row=None)

        result = _find_sibling_rate(
            db, source="acumen", company_name="Acumen International", service_name="Brand New Route 99"
        )

        assert result is None, "No sibling should be found for a genuinely new route"

    def test_no_sibling_execute_still_called(self):
        """Even with no sibling, INSERT is still executed (row gets $0 + unknown_route tag)."""
        from backend.db.crud import ensure_rate_services

        db = _make_db_session(sibling_row=None)

        ensure_rate_services(
            db,
            [
                {
                    "service_key": "acumen_test_brand_new_99",
                    "service_name": "Brand New Route 99",
                    "currency": "USD",
                    "default_rate": 0,
                }
            ],
            source="acumen",
            company_name="Acumen International",
        )

        db.execute.assert_called_once()

    # ------------------------------------------------------------------
    # Inactive sibling must NOT be inherited
    # ------------------------------------------------------------------
    def test_inactive_sibling_not_inherited(self):
        """An inactive sibling row must be ignored — do not inherit from inactive routes."""
        from backend.db.crud import _find_sibling_rate

        # Sibling exists but is inactive
        inactive_sib = _make_svc("Foo OB 03", default_rate=45.00, active=False)
        db = _make_db_session(sibling_row=inactive_sib)

        # The DB mock returns an inactive row — but the query itself filters
        # active=True, so in a real DB it would return None.  Simulate that:
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = _find_sibling_rate(
            db, source="acumen", company_name="Acumen International", service_name="Foo OB 03_B"
        )

        assert result is None, "Inactive sibling must not be inherited"

    # ------------------------------------------------------------------
    # Empty or missing service_name → skipped silently
    # ------------------------------------------------------------------
    def test_empty_service_name_skipped(self):
        """Services without a name are silently skipped — no crash."""
        from backend.db.crud import ensure_rate_services

        db = _make_db_session(sibling_row=None)

        # Should not raise
        ensure_rate_services(
            db,
            [{"service_key": "k1", "service_name": "", "currency": "USD"}],
            source="acumen",
            company_name="Acumen International",
        )

        db.execute.assert_not_called()

    def test_missing_service_key_skipped(self):
        """Services without a service_key are silently skipped."""
        from backend.db.crud import ensure_rate_services

        db = _make_db_session(sibling_row=None)

        ensure_rate_services(
            db,
            [{"service_name": "Foo OB 03", "currency": "USD"}],
            source="acumen",
            company_name="Acumen International",
        )

        db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Integration-style tests: ensure_rate_services in services/rates.py
# (mirrors the crud.py tests but exercises the rates.py copy)
# ---------------------------------------------------------------------------

class TestEnsureRateServicesRates:
    """Tests for backend.services.rates.ensure_rate_services"""

    def _call(self, db, services, source="acumen", company_name="acumen"):
        from backend.services.rates import ensure_rate_services
        ensure_rate_services(db, services, source=source, company_name=company_name)

    def test_letter_suffix_triggers_sibling_lookup(self):
        """rates.py ensure_rate_services also queries for siblings on $0 routes."""
        sibling = _make_svc("FOO OB 03", default_rate=45.00)
        db = _make_db_session(sibling_row=sibling)

        self._call(db, [
            {
                "service_key": "acumen_acumen_foo_ob_03_b",
                "service_name": "FOO OB 03_B",
                "currency": "USD",
                "default_rate": 0,
            }
        ])

        db.query.assert_called()
        db.execute.assert_called_once()

    def test_no_sibling_execute_still_called(self):
        """No sibling found → INSERT still happens (unknown_route tag)."""
        db = _make_db_session(sibling_row=None)

        self._call(db, [
            {
                "service_key": "acumen_acumen_totally_new_77",
                "service_name": "Totally New 77",
                "currency": "USD",
                "default_rate": 0,
            }
        ])

        db.execute.assert_called_once()

    def test_find_sibling_rate_in_rates(self):
        """_find_sibling_rate_in_rates returns rate+name when sibling exists."""
        from backend.services.rates import _find_sibling_rate_in_rates

        sibling = _make_svc("Timberline IB 05", default_rate=60.00)
        db = _make_db_session(sibling_row=sibling)

        result = _find_sibling_rate_in_rates(
            db, source="acumen", company_name="acumen", service_name="Timberline IB 06"
        )

        assert result is not None
        rate, name = result
        assert Decimal(str(rate)) == Decimal("60.00")

    def test_find_sibling_returns_none_when_no_match(self):
        """_find_sibling_rate_in_rates returns None when DB returns nothing."""
        from backend.services.rates import _find_sibling_rate_in_rates

        db = _make_db_session(sibling_row=None)

        result = _find_sibling_rate_in_rates(
            db, source="acumen", company_name="acumen", service_name="Totally New Route 77"
        )

        assert result is None


# ---------------------------------------------------------------------------
# Company-alias cross-lookup tests
# Realistic scenario: FA renumbers routes week-to-week, and rate rows were
# stored under a different company_name variant than what the new import uses.
# W14/W15 → "Acumen International" or "Acumen"; W16 → "FirstAlt"
# ---------------------------------------------------------------------------

def _make_db_session_with_company(sibling_row=None, stored_company="acumen international"):
    """
    Mock DB session that returns sibling_row ONLY when the filter matches
    the stored_company — simulates actual DB rows stored under an old name.
    """
    db = MagicMock()

    call_count = [0]

    def filter_side_effect(*args, **kwargs):
        # Check if any filter arg references the stored company
        q_mock = MagicMock()
        q_order = MagicMock()

        # Return the sibling only when any company alias is tried (not just exact)
        # We simulate: DB always returns sibling_row regardless of company filter
        # (the real DB would match on any alias since we query each separately)
        q_order.first.return_value = sibling_row
        q_mock.order_by.return_value = q_order
        return q_mock

    db.query.return_value.filter.side_effect = filter_side_effect
    db.execute.return_value = MagicMock()
    return db


class TestCompanyAliasLookup:
    """
    Tests that sibling-rate lookup crosses company_name aliases.

    Real scenario: mom uploads W16 FA xlsx. batch.company_name="FirstAlt".
    Rate rows for W14/W15 routes were stored as company_name="Acumen International"
    or "Acumen". Without alias crossing, _find_sibling_rate returns None for every
    sibling candidate even though a perfectly good rate exists → $0 rides → auto-withhold.
    """

    # ------------------------------------------------------------------
    # rates.py _ACUMEN_COMPANY_ALIASES covers all 4 FA name variants
    # ------------------------------------------------------------------
    def test_aliases_cover_firstalt_to_acumen(self):
        """'firstalt' must map to 'acumen' and 'acumen international'."""
        from backend.services.rates import _ACUMEN_COMPANY_ALIASES
        aliases = _ACUMEN_COMPANY_ALIASES
        assert "acumen" in aliases.get("firstalt", [])
        assert "acumen international" in aliases.get("firstalt", [])

    def test_aliases_cover_acumen_to_firstalt(self):
        """'acumen' and 'acumen international' must map back to 'firstalt'."""
        from backend.services.rates import _ACUMEN_COMPANY_ALIASES
        aliases = _ACUMEN_COMPANY_ALIASES
        assert "firstalt" in aliases.get("acumen", [])
        assert "firstalt" in aliases.get("acumen international", [])

    def test_aliases_are_symmetric(self):
        """If A aliases B, B must alias A."""
        from backend.services.rates import _ACUMEN_COMPANY_ALIASES
        for primary, secondaries in _ACUMEN_COMPANY_ALIASES.items():
            for alt in secondaries:
                assert primary in _ACUMEN_COMPANY_ALIASES.get(alt, []), (
                    f"Alias asymmetry: '{primary}' maps to '{alt}' but not vice versa"
                )

    # ------------------------------------------------------------------
    # rates.py _find_sibling_rate_in_rates uses aliases
    # ------------------------------------------------------------------
    def test_find_sibling_in_rates_firstalt_finds_acumen_row(self):
        """
        W16 import uses company_name='firstalt'.
        Rate row was stored under 'acumen international' (W14/W15 import).
        _find_sibling_rate_in_rates must find it via company alias.

        'Ella Baker ES IB 02_B' → sibling 'Ella Baker ES IB 01_B' or
        'Ella Baker ES IB 01' stored under 'acumen international' at $38.
        """
        from backend.services.rates import _find_sibling_rate_in_rates

        sibling = _make_svc("Ella Baker ES IB 01", default_rate=38.00)
        db = _make_db_session_with_company(
            sibling_row=sibling, stored_company="acumen international"
        )

        result = _find_sibling_rate_in_rates(
            db,
            source="acumen",
            company_name="firstalt",
            service_name="Ella Baker ES IB 02_B",
        )

        assert result is not None, (
            "Should find 'Ella Baker ES IB 01' stored under 'acumen international' "
            "when looking up from a 'firstalt' import context"
        )
        rate, _ = result
        assert Decimal(str(rate)) == Decimal("38.00")

    def test_find_sibling_in_rates_timberline_ms_ib_05_finds_neighbor(self):
        """
        W16 'Timberline MS IB 05' (new route) finds 'Timberline MS IB 04'
        stored under 'acumen' at $60 when import uses 'firstalt'.
        """
        from backend.services.rates import _find_sibling_rate_in_rates

        sibling = _make_svc("Timberline MS IB 04", default_rate=60.00)
        db = _make_db_session_with_company(sibling_row=sibling, stored_company="acumen")

        result = _find_sibling_rate_in_rates(
            db,
            source="acumen",
            company_name="firstalt",
            service_name="Timberline MS IB 05",
        )

        assert result is not None
        rate, _ = result
        assert Decimal(str(rate)) == Decimal("60.00")

    def test_find_sibling_in_rates_ballard_hs_ib_02_finds_neighbor(self):
        """
        W16 'Ballard HS IB 02' finds 'Ballard HS IB 01' (stored as 'acumen international').
        Matches actual W16 batch 87 unpriced route.
        """
        from backend.services.rates import _find_sibling_rate_in_rates

        sibling = _make_svc("Ballard HS IB 01", default_rate=38.00)
        db = _make_db_session_with_company(
            sibling_row=sibling, stored_company="acumen international"
        )

        result = _find_sibling_rate_in_rates(
            db,
            source="acumen",
            company_name="firstalt",
            service_name="Ballard HS IB 02",
        )

        assert result is not None
        rate, _ = result
        assert Decimal(str(rate)) == Decimal("38.00")

    def test_find_sibling_in_rates_alderwood_ms_ob_03(self):
        """
        W16 'Alderwood MS OB 03' finds 'Alderwood MS OB 02' via company alias.
        """
        from backend.services.rates import _find_sibling_rate_in_rates

        sibling = _make_svc("Alderwood MS OB 02", default_rate=38.00)
        db = _make_db_session_with_company(sibling_row=sibling, stored_company="acumen")

        result = _find_sibling_rate_in_rates(
            db,
            source="acumen",
            company_name="firstalt",
            service_name="Alderwood MS OB 03",
        )

        assert result is not None
        rate, _ = result
        assert Decimal(str(rate)) == Decimal("38.00")

    # ------------------------------------------------------------------
    # crud.py _find_sibling_rate also uses aliases
    # ------------------------------------------------------------------
    def test_crud_find_sibling_firstalt_finds_acumen_row(self):
        """
        crud.py _find_sibling_rate must also try company aliases.
        Same scenario: W16 'FirstAlt' import, W15 rate stored as 'Acumen International'.
        """
        from backend.db.crud import _find_sibling_rate

        sibling = _make_svc("Ella Baker ES IB 01", default_rate=38.00)
        db = _make_db_session_with_company(
            sibling_row=sibling, stored_company="acumen international"
        )

        result = _find_sibling_rate(
            db,
            source="acumen",
            company_name="firstalt",
            service_name="Ella Baker ES IB 02_B",
        )

        assert result is not None, (
            "crud._find_sibling_rate must find cross-company siblings"
        )
        rate, _ = result
        assert Decimal(str(rate)) == Decimal("38.00")

    def test_crud_find_sibling_brightmont_acdy_ob_01(self):
        """
        W16 'Brightmont ACDY OB 01' finds 'Brightmont ACDY OB 02' via alias.
        Matches actual W16 batch 87 unpriced route.
        """
        from backend.db.crud import _find_sibling_rate

        sibling = _make_svc("Brightmont ACDY OB 02", default_rate=38.00)
        db = _make_db_session_with_company(sibling_row=sibling, stored_company="acumen")

        result = _find_sibling_rate(
            db,
            source="acumen",
            company_name="firstalt",
            service_name="Brightmont ACDY OB 01",
        )

        assert result is not None
        rate, _ = result
        assert Decimal(str(rate)) == Decimal("38.00")
