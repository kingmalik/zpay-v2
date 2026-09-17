"""
Tests for the Paychex External API rail (S12) — replaces the Playwright bot.

No real network calls anywhere: backend.services.paychex_api.PaychexApiClient
tests inject a fake `transport` callable (method, url, **kwargs) -> fake
response; route-level tests patch `backend.routes.paychex_api.PaychexApiClient`
with a stub and `_eligible_rows` with canned summary rows, so business logic
(matching, period selection, idempotency, partial failure, role/flag gating)
is exercised without depending on _build_summary's ride-join internals.

Run in isolation:
    PYTHONPATH=. python3 -m pytest backend/tests/test_paychex_api_rail.py -q --no-header -p no:cacheprovider
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import BigInteger, Integer, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-key-for-paychex-api-rail-tests-long-enough")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import Text as _Text  # noqa: E402
from backend.db.models import Base, PaychexApiCheck, PayrollBatch, Person  # noqa: E402

Base.metadata.tables["z_rate_override"].c["effective_during"].type = _Text()
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()
        if _col.server_default is not None:
            _sd = _col.server_default
            _arg = getattr(getattr(_sd, "arg", None), "text", "") or ""
            if "NOW()" in _arg:
                _col.nullable = True
                _col.server_default = None

_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@event.listens_for(_engine, "connect")
def _register_now(dbapi_conn, _rec):
    dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())


Base.metadata.create_all(_engine)
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402
from backend.routes import paychex_api as api_routes  # noqa: E402
from backend.services import paychex_api as api_service  # noqa: E402
from backend.services.paychex_api import (  # noqa: E402
    PaychexApiClient,
    PaychexApiConfigError,
    PaychexApiError,
)
from backend.services.paychex_api_matching import (  # noqa: E402
    build_worker_index,
    component_supports_contractor,
    count_contractor_workers,
    filter_contractor_components,
    match_rows,
    select_pay_period,
)


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app, raise_server_exceptions=True)
_JSON = {"Accept": "application/json"}


def _cookie(role: str) -> dict:
    token = create_session(username=f"t-{role}", display_name=role, color="#000", initials="T", role=role)
    return {COOKIE_NAME: token}


@pytest.fixture(autouse=True)
def _clean_state():
    api_service._TOKEN_CACHE.clear()
    with _SessionFactory() as s:
        s.query(PaychexApiCheck).delete()
        s.query(PayrollBatch).delete()
        s.query(Person).delete()
        s.commit()
    env_patch = {
        "PAYCHEX_API_ENABLED": "1",
        "PAYCHEX_API_CLIENT_ID_ACUMEN": "id-acumen",
        "PAYCHEX_API_CLIENT_SECRET_ACUMEN": "secret-acumen",
        "PAYCHEX_API_COMPANY_ID_ACUMEN": "company-acumen",
        "PAYCHEX_API_1099_COMPONENT_ID_ACUMEN": "comp-1099",
    }
    with patch.dict(os.environ, env_patch):
        yield


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json = json_body
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


# ── PaychexApiClient: token caching + refresh ────────────────────────────────

class TestTokenCaching:
    def test_token_is_cached_across_calls(self):
        calls = []

        def transport(method, url, **kwargs):
            calls.append((method, url))
            return _FakeResponse(200, {"access_token": "tok-1", "expires_in": 3600})

        client_obj = PaychexApiClient("acumen", transport=transport)
        assert client_obj.get_access_token() == "tok-1"
        assert client_obj.get_access_token() == "tok-1"
        assert len(calls) == 1

    def test_token_refetches_after_expiry(self):
        calls = []
        tokens = iter(["tok-1", "tok-2"])

        def transport(method, url, **kwargs):
            calls.append((method, url))
            return _FakeResponse(200, {"access_token": next(tokens), "expires_in": 100})

        with patch.object(api_service.time, "time", side_effect=[1000.0, 1050.0, 1200.0]):
            client_obj = PaychexApiClient("acumen", transport=transport)
            first = client_obj.get_access_token()
            second = client_obj.get_access_token()  # still within skew window -> cached
            third = client_obj.get_access_token()   # past expiry -> refetch

        assert first == "tok-1"
        assert second == "tok-1"
        assert third == "tok-2"
        assert len(calls) == 2

    def test_missing_credentials_raise_config_error(self):
        with patch.dict(os.environ, {"PAYCHEX_API_CLIENT_ID_ACUMEN": ""}):
            client_obj = PaychexApiClient("acumen", transport=lambda *a, **k: _FakeResponse(200, {}))
            with pytest.raises(PaychexApiConfigError):
                client_obj.get_access_token()

    def test_token_http_error_raises_paychex_api_error(self):
        def transport(method, url, **kwargs):
            return _FakeResponse(401, {"error": "invalid_client"})

        client_obj = PaychexApiClient("acumen", transport=transport)
        with pytest.raises(PaychexApiError):
            client_obj.get_access_token()


# ── PaychexApiClient: worker pagination ──────────────────────────────────────

class TestWorkerPagination:
    def test_offset_pagination_follows_short_page_stop(self):
        page_size = api_service.WORKERS_PAGE_SIZE
        full_page = [{"employeeId": f"E{i}", "workerId": f"W{i}", "workerType": "INDEPENDENT_CONTRACTOR"} for i in range(page_size)]
        last_page = [{"employeeId": "ELAST", "workerId": "WLAST", "workerType": "INDEPENDENT_CONTRACTOR"}]
        offsets_seen = []

        def transport(method, url, **kwargs):
            if url.endswith(api_service.TOKEN_PATH):
                return _FakeResponse(200, {"access_token": "tok", "expires_in": 3600})
            params = kwargs.get("params", {})
            offset = params.get("offset", 0)
            offsets_seen.append(offset)
            return _FakeResponse(200, full_page if offset == 0 else last_page)

        client_obj = PaychexApiClient("acumen", transport=transport)
        workers = client_obj.get_workers()

        assert offsets_seen == [0, page_size]
        assert len(workers) == page_size + 1
        assert workers[-1]["employeeId"] == "ELAST"

    def test_links_next_pagination_is_followed(self):
        next_url = "https://api.paychex.com/companies/company-acumen/workers?cursor=abc"

        def transport(method, url, **kwargs):
            if url.endswith(api_service.TOKEN_PATH):
                return _FakeResponse(200, {"access_token": "tok", "expires_in": 3600})
            if url == next_url:
                return _FakeResponse(200, {"content": [{"employeeId": "E2", "workerId": "W2", "workerType": "INDEPENDENT_CONTRACTOR"}]})
            return _FakeResponse(200, {
                "content": [{"employeeId": "E1", "workerId": "W1", "workerType": "INDEPENDENT_CONTRACTOR"}],
                "links": [{"rel": "next", "href": next_url}],
            })

        client_obj = PaychexApiClient("acumen", transport=transport)
        workers = client_obj.get_workers()
        assert [w["employeeId"] for w in workers] == ["E1", "E2"]

    def test_worker_list_http_error_raises(self):
        def transport(method, url, **kwargs):
            if url.endswith(api_service.TOKEN_PATH):
                return _FakeResponse(200, {"access_token": "tok", "expires_in": 3600})
            return _FakeResponse(500, {"error": "boom"})

        client_obj = PaychexApiClient("acumen", transport=transport)
        with pytest.raises(PaychexApiError):
            client_obj.get_workers()


# ── PaychexApiClient: stage_checks partial failure ───────────────────────────

class TestStageChecks:
    def test_partial_failure_records_each_row_independently(self):
        call_count = {"n": 0}

        def transport(method, url, **kwargs):
            if url.endswith(api_service.TOKEN_PATH):
                return _FakeResponse(200, {"access_token": "tok", "expires_in": 3600})
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _FakeResponse(200, [{"paycheckId": "PC-1"}])
            return _FakeResponse(400, {"message": "API-57: component not eligible"})

        client_obj = PaychexApiClient("acumen", transport=transport)
        results = client_obj.stage_checks([
            {"person_id": 1, "worker_id": "W1", "pay_period_id": "P1", "component_id": "C1", "amount": "100.00"},
            {"person_id": 2, "worker_id": "W2", "pay_period_id": "P1", "component_id": "C1", "amount": "50.00"},
        ])

        assert results[0] == {"person_id": 1, "status": "staged", "paycheck_id": "PC-1", "error": None}
        assert results[1]["status"] == "failed"
        assert "API-57" in results[1]["error"]


# ── Pure matching helpers ────────────────────────────────────────────────────

class TestMatchingHelpers:
    def test_build_worker_index_keys_by_employee_id(self):
        workers = [
            {"employeeId": "1031", "workerId": "W1", "workerType": "INDEPENDENT_CONTRACTOR", "name": "Abbas Driver"},
            {"employeeId": "", "workerId": "W2", "workerType": "EMPLOYEE"},
        ]
        index = build_worker_index(workers)
        assert set(index.keys()) == {"1031"}
        assert index["1031"]["worker_id"] == "W1"
        assert index["1031"]["name"] == "Abbas Driver"

    def test_match_rows_flags_missing_not_found_and_wrong_type(self):
        index = {
            "1031": {"worker_id": "W1", "worker_type": "INDEPENDENT_CONTRACTOR", "name": "Abbas"},
            "2000": {"worker_id": "W2", "worker_type": "EMPLOYEE", "name": "Joe"},
        }
        rows = [
            {"person_id": 1, "person": "Abbas Driver", "code": "1031", "pay_this_period": 332.0},
            {"person_id": 2, "person": "No Code", "code": "", "pay_this_period": 100.0},
            {"person_id": 3, "person": "Nowhere", "code": "9999", "pay_this_period": 100.0},
            {"person_id": 4, "person": "Joe W2", "code": "2000", "pay_this_period": 100.0},
        ]
        matched, unmatched = match_rows(rows, index)
        assert len(matched) == 1 and matched[0]["worker_id"] == "W1"
        reasons = {row["person_id"]: row["reason"] for row in unmatched}
        assert reasons[2] == "no_employee_id"
        assert reasons[3] == "not_found_in_paychex"
        assert reasons[4] == "wrong_worker_type:EMPLOYEE"
        # inputs never mutated
        assert "worker_id" not in rows[0]

    def test_select_pay_period_matches_by_start_end_date(self):
        periods = [
            {"payPeriodId": "P1", "startDate": "2026-09-01", "endDate": "2026-09-07", "status": "INITIAL"},
            {"payPeriodId": "P2", "startDate": "2026-09-08", "endDate": "2026-09-14", "status": "ENTRY"},
        ]
        found = select_pay_period(periods, date(2026, 9, 8), date(2026, 9, 14))
        assert found is not None and found["payPeriodId"] == "P2"
        assert select_pay_period(periods, date(2026, 10, 1), date(2026, 10, 7)) is None

    def test_component_helpers(self):
        components = [
            {"componentId": "C1", "appliesToWorkerTypes": ["EMPLOYEE"]},
            {"componentId": "C2", "appliesToWorkerTypes": ["INDEPENDENT_CONTRACTOR", "EMPLOYEE"]},
        ]
        assert filter_contractor_components(components) == [components[1]]
        assert component_supports_contractor(components, "C2") is True
        assert component_supports_contractor(components, "C1") is False
        assert component_supports_contractor(components, "unknown") is False

    def test_count_contractor_workers(self):
        workers = [{"workerType": "INDEPENDENT_CONTRACTOR"}, {"workerType": "EMPLOYEE"}, {"workerType": "INDEPENDENT_CONTRACTOR"}]
        assert count_contractor_workers(workers) == 2


# ── Route helpers ─────────────────────────────────────────────────────────────

def _seed_batch(
    company_name: str = "Acumen", period_start=date(2026, 9, 1), period_end=date(2026, 9, 7),
    status: str = "approved",
) -> int:
    with _SessionFactory() as s:
        batch = PayrollBatch(
            source="firstalt",
            company_name=company_name,
            status=status,
            period_start=period_start,
            period_end=period_end,
        )
        s.add(batch)
        s.commit()
        return batch.payroll_batch_id


def _seed_person(name: str = "Abbas Driver") -> int:
    with _SessionFactory() as s:
        person = Person(full_name=name, paycheck_code="1031")
        s.add(person)
        s.commit()
        return person.person_id


class _FakeClient:
    """Stand-in for PaychexApiClient used by route tests — no HTTP at all."""

    def __init__(self, workers=None, periods=None, components=None, component_id="comp-1099",
                 stage_results=None, raise_on=None):
        self.workers = workers or []
        self.periods = periods or []
        self.components = components if components is not None else [
            {"componentId": "comp-1099", "appliesToWorkerTypes": ["INDEPENDENT_CONTRACTOR"]}
        ]
        self.component_id = component_id
        self._stage_results = stage_results
        self._raise_on = raise_on or {}
        self.staged_calls: list[list[dict]] = []

    def _maybe_raise(self, name):
        if name in self._raise_on:
            raise self._raise_on[name]

    def get_access_token(self):
        self._maybe_raise("get_access_token")
        return "tok"

    def get_workers(self):
        self._maybe_raise("get_workers")
        return self.workers

    def get_open_pay_periods(self):
        self._maybe_raise("get_open_pay_periods")
        return self.periods

    def get_pay_periods(self, statuses):
        self._maybe_raise("get_pay_periods")
        return self.periods

    def get_pay_components(self):
        self._maybe_raise("get_pay_components")
        return self.components

    def get_company_name(self):
        return "Acumen Transportation LLC"

    def stage_checks(self, checks):
        self._maybe_raise("stage_checks")
        self.staged_calls.append(checks)
        if self._stage_results is not None:
            return self._stage_results
        return [{"person_id": c["person_id"], "status": "staged", "paycheck_id": f"PC-{c['person_id']}", "error": None} for c in checks]


def _row(person_id: int, code: str = "1031", person: str = "Abbas Driver", amount: float = 332.0) -> dict:
    return {"person_id": person_id, "person": person, "code": code, "pay_this_period": amount, "withheld": False}


_MATCHING_PERIOD = {"payPeriodId": "P1", "startDate": "2026-09-01", "endDate": "2026-09-07", "status": "INITIAL", "checkDate": "2026-09-10"}
_MATCHING_WORKER = {"employeeId": "1031", "workerId": "W1", "workerType": "INDEPENDENT_CONTRACTOR", "name": "Abbas Driver"}


# ── Flag / role gating ────────────────────────────────────────────────────────

class TestGating:
    def test_all_endpoints_404_when_flag_disabled(self):
        batch_id = _seed_batch()
        with patch.dict(os.environ, {"PAYCHEX_API_ENABLED": "0"}):
            r1 = client.get(f"/api/data/paychex-api/acumen/health", cookies=_cookie("admin"))
            r2 = client.post(f"/api/data/paychex-api/preview/{batch_id}", cookies=_cookie("admin"), headers=_JSON)
            r3 = client.post(f"/api/data/paychex-api/push/{batch_id}", cookies=_cookie("admin"), headers=_JSON)
        for r in (r1, r2, r3):
            assert r.status_code == 404
            assert r.json() == {"error": "Paychex API rail is disabled"}

    def test_health_requires_admin(self):
        r = client.get("/api/data/paychex-api/acumen/health", cookies=_cookie("operator"))
        assert r.status_code == 403

    def test_preview_and_push_require_admin_or_operator(self):
        batch_id = _seed_batch()
        r1 = client.post(f"/api/data/paychex-api/preview/{batch_id}", cookies=_cookie("associate"), headers=_JSON)
        r2 = client.post(f"/api/data/paychex-api/push/{batch_id}", cookies=_cookie("associate"), headers=_JSON)
        assert r1.status_code == 403
        assert r2.status_code == 403

    def test_preview_allows_operator(self):
        batch_id = _seed_batch()
        fake = _FakeClient(workers=[_MATCHING_WORKER], periods=[_MATCHING_PERIOD])
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            with patch.object(api_routes, "_eligible_rows", return_value=[_row(1)]):
                r = client.post(f"/api/data/paychex-api/preview/{batch_id}", cookies=_cookie("operator"), headers=_JSON)
        assert r.status_code == 200


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealth:
    def test_invalid_company_400(self):
        r = client.get("/api/data/paychex-api/acme/health", cookies=_cookie("admin"))
        assert r.status_code == 400

    def test_success_shape(self):
        fake = _FakeClient(
            workers=[_MATCHING_WORKER, {"employeeId": "2000", "workerId": "W2", "workerType": "EMPLOYEE"}],
            periods=[_MATCHING_PERIOD],
            components=[
                {"componentId": "comp-1099", "name": "1099 Pay", "appliesToWorkerTypes": ["INDEPENDENT_CONTRACTOR"]},
                {"componentId": "comp-w2", "name": "W2 Pay", "appliesToWorkerTypes": ["EMPLOYEE"]},
            ],
        )
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            r = client.get("/api/data/paychex-api/acumen/health", cookies=_cookie("admin"))
        assert r.status_code == 200
        body = r.json()
        assert body["token_ok"] is True
        assert body["contractor_count"] == 1
        assert body["company_name"] == "Acumen Transportation LLC"
        assert len(body["candidate_1099_components"]) == 1
        assert body["candidate_1099_components"][0]["component_id"] == "comp-1099"
        assert body["open_pay_periods"][0]["pay_period_id"] == "P1"

    def test_config_error_maps_to_400(self):
        fake = _FakeClient(raise_on={"get_access_token": PaychexApiConfigError("missing creds")})
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            r = client.get("/api/data/paychex-api/acumen/health", cookies=_cookie("admin"))
        assert r.status_code == 400
        assert "missing creds" in r.json()["error"]

    def test_upstream_error_maps_to_status_code(self):
        fake = _FakeClient(raise_on={"get_access_token": PaychexApiError("token rejected", status_code=401)})
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            r = client.get("/api/data/paychex-api/acumen/health", cookies=_cookie("admin"))
        assert r.status_code == 401


# ── /preview ──────────────────────────────────────────────────────────────────

class TestPreview:
    def test_batch_not_found_404(self):
        r = client.post("/api/data/paychex-api/preview/999999", cookies=_cookie("admin"), headers=_JSON)
        assert r.status_code == 404

    def test_unmatched_rows_are_listed_with_reasons(self):
        batch_id = _seed_batch()
        fake = _FakeClient(workers=[_MATCHING_WORKER], periods=[_MATCHING_PERIOD])
        rows = [_row(1, code="1031"), _row(2, code="9999", person="Nowhere Man")]
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            with patch.object(api_routes, "_eligible_rows", return_value=rows):
                r = client.post(f"/api/data/paychex-api/preview/{batch_id}", cookies=_cookie("admin"), headers=_JSON)
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert len(body["unmatched"]) == 1
        assert body["unmatched"][0]["reason"] == "not_found_in_paychex"

    def test_no_matching_pay_period_lists_open_periods(self):
        batch_id = _seed_batch(period_start=date(2026, 9, 15), period_end=date(2026, 9, 21))
        other_period = {"payPeriodId": "P9", "startDate": "2026-09-01", "endDate": "2026-09-07", "status": "INITIAL"}
        fake = _FakeClient(workers=[_MATCHING_WORKER], periods=[other_period])
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            with patch.object(api_routes, "_eligible_rows", return_value=[_row(1)]):
                r = client.post(f"/api/data/paychex-api/preview/{batch_id}", cookies=_cookie("admin"), headers=_JSON)
        body = r.json()
        assert body["pay_period"] is None
        assert body["open_pay_periods"] == [{
            "pay_period_id": "P9", "start_date": "2026-09-01", "end_date": "2026-09-07",
            "status": "INITIAL", "check_date": None, "description": None,
        }]

    def test_component_not_eligible_flagged(self):
        batch_id = _seed_batch()
        fake = _FakeClient(
            workers=[_MATCHING_WORKER], periods=[_MATCHING_PERIOD],
            components=[{"componentId": "comp-1099", "appliesToWorkerTypes": ["EMPLOYEE"]}],
        )
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            with patch.object(api_routes, "_eligible_rows", return_value=[_row(1)]):
                r = client.post(f"/api/data/paychex-api/preview/{batch_id}", cookies=_cookie("admin"), headers=_JSON)
        assert r.json()["component_ok"] is False


# ── /push ─────────────────────────────────────────────────────────────────────

class TestPush:
    def test_refuses_unmatched_unless_skip_flag(self):
        batch_id = _seed_batch()
        person_id = _seed_person()
        fake = _FakeClient(workers=[_MATCHING_WORKER], periods=[_MATCHING_PERIOD])
        rows = [_row(person_id, code="1031"), _row(person_id + 1000, code="9999", person="Nowhere")]
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            with patch.object(api_routes, "_eligible_rows", return_value=rows):
                refused = client.post(f"/api/data/paychex-api/push/{batch_id}", cookies=_cookie("admin"), headers=_JSON)
                assert refused.status_code == 400
                assert "unmatched" in refused.json()

                skipped = client.post(
                    f"/api/data/paychex-api/push/{batch_id}", cookies=_cookie("admin"),
                    json={"skip_unmatched": True},
                )
        assert skipped.status_code == 200
        assert skipped.json()["staged"] == 1
        assert fake.staged_calls[0] == [{
            "person_id": person_id, "worker_id": "W1", "pay_period_id": "P1",
            "component_id": "comp-1099", "amount": 332.0,
        }]

    def test_push_refuses_unapproved_batch(self):
        batch_id = _seed_batch(status="payroll_review")
        fake = _FakeClient(workers=[_MATCHING_WORKER], periods=[_MATCHING_PERIOD])
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            r = client.post(f"/api/data/paychex-api/push/{batch_id}", cookies=_cookie("admin"), headers=_JSON)
        assert r.status_code == 400
        assert "approved" in r.json()["error"]
        assert fake.staged_calls == []

    def test_claim_rows_returns_none_when_person_already_claimed(self):
        batch_id = _seed_batch()
        person_id = _seed_person()
        with _SessionFactory() as s:
            batch = s.get(PayrollBatch, batch_id)
            rows = [{"person_id": person_id, "worker_id": "W1", "amount": 10.0}]
            first = api_routes._claim_rows(s, batch, "acumen", "P1", rows)
            assert first is not None and first[0].status == api_routes.CLAIM_STATUS
            second = api_routes._claim_rows(s, batch, "acumen", "P1", rows)
            assert second is None
            assert s.query(PaychexApiCheck).filter_by(payroll_batch_id=batch_id).count() == 1

    def test_idempotent_refuses_when_batch_already_staged(self):
        batch_id = _seed_batch()
        person_id = _seed_person()
        with _SessionFactory() as s:
            s.add(PaychexApiCheck(
                payroll_batch_id=batch_id, person_id=person_id, company="acumen",
                worker_id="W1", pay_period_id="P1", amount=Decimal("332.00"), status="staged",
            ))
            s.commit()

        fake = _FakeClient(workers=[_MATCHING_WORKER], periods=[_MATCHING_PERIOD])
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            with patch.object(api_routes, "_eligible_rows", return_value=[_row(person_id)]):
                r = client.post(f"/api/data/paychex-api/push/{batch_id}", cookies=_cookie("admin"), headers=_JSON)
        assert r.status_code == 400
        assert person_id in r.json()["already_staged_person_ids"]
        assert fake.staged_calls == []

    def test_partial_failure_records_per_row_and_returns_207(self):
        batch_id = _seed_batch()
        p1 = _seed_person("Abbas Driver")
        p2 = _seed_person("Second Driver")
        rows = [_row(p1, code="1031"), _row(p2, code="1031", amount=50.0)]
        worker_index = [_MATCHING_WORKER]
        stage_results = [
            {"person_id": p1, "status": "staged", "paycheck_id": "PC-1", "error": None},
            {"person_id": p2, "status": "failed", "paycheck_id": None, "error": "HTTP 400: API-57"},
        ]
        fake = _FakeClient(workers=worker_index, periods=[_MATCHING_PERIOD], stage_results=stage_results)
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            with patch.object(api_routes, "_eligible_rows", return_value=rows):
                r = client.post(f"/api/data/paychex-api/push/{batch_id}", cookies=_cookie("admin"), headers=_JSON)

        assert r.status_code == 207
        body = r.json()
        assert body["staged"] == 1 and body["failed"] == 1

        with _SessionFactory() as s:
            checks = s.query(PaychexApiCheck).filter_by(payroll_batch_id=batch_id).order_by(PaychexApiCheck.person_id).all()
            statuses = {c.person_id: c.status for c in checks}
            assert statuses[p1] == "staged" and statuses[p2] == "failed"
            batch = s.query(PayrollBatch).filter_by(payroll_batch_id=batch_id).first()
            assert batch.paychex_exported_at is not None

    def test_full_success_sets_exported_at_and_returns_200(self):
        batch_id = _seed_batch()
        p1 = _seed_person()
        fake = _FakeClient(workers=[_MATCHING_WORKER], periods=[_MATCHING_PERIOD])
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            with patch.object(api_routes, "_eligible_rows", return_value=[_row(p1)]):
                r = client.post(f"/api/data/paychex-api/push/{batch_id}", cookies=_cookie("admin"), headers=_JSON)
        assert r.status_code == 200
        assert r.json()["failed"] == 0

    def test_no_open_pay_period_400(self):
        batch_id = _seed_batch()
        p1 = _seed_person()
        fake = _FakeClient(workers=[_MATCHING_WORKER], periods=[])
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            with patch.object(api_routes, "_eligible_rows", return_value=[_row(p1)]):
                r = client.post(f"/api/data/paychex-api/push/{batch_id}", cookies=_cookie("admin"), headers=_JSON)
        assert r.status_code == 400
        assert "open_pay_periods" in r.json()

    def test_no_eligible_rows_400(self):
        batch_id = _seed_batch()
        fake = _FakeClient(workers=[_MATCHING_WORKER], periods=[_MATCHING_PERIOD])
        with patch.object(api_routes, "PaychexApiClient", lambda bucket: fake):
            with patch.object(api_routes, "_eligible_rows", return_value=[]):
                r = client.post(f"/api/data/paychex-api/push/{batch_id}", cookies=_cookie("admin"), headers=_JSON)
        assert r.status_code == 400
