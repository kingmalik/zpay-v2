"""
Tests for the Paychex bot MFA handoff + login-only run (S11).

- _wait_for_mfa_code: pure polling logic (fake provider / fake sleep)
- _answer_mfa_with_human_code: fake page — accepted code returns, rejected
  codes exhaust attempts → MfaCodeTimeout
- POST /api/data/paychex-bot/mfa/{job_id}: validation, 404, status gate, write
- POST /api/data/paychex-bot/login/{company}: role gate, creds gate, job row
  (mode=login) + background task scheduled with login_only=True

Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_paychex_mfa_login.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-key-for-paychex-mfa-tests-long-enough")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, PaychexJob  # noqa: E402

Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()
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
from backend.paychex_bot import paychex_entry  # noqa: E402
from backend.routes import paychex_bot as bot_routes  # noqa: E402


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app, raise_server_exceptions=True)
_JSON = {"Accept": "application/json"}  # CSRF middleware exempts JSON API calls


def _cookie(role: str) -> dict:
    token = create_session(username=f"t-{role}", display_name=role, color="#000", initials="T", role=role)
    return {COOKIE_NAME: token}


@pytest.fixture(autouse=True)
def _use_test_sessions():
    """Route helpers open their own SessionLocal — point them at SQLite."""
    with _SessionFactory() as s:
        s.query(PaychexJob).delete()
        s.commit()
    with patch.object(bot_routes, "SessionLocal", _SessionFactory):
        yield


def _seed_job(job_id: str = "job-1", status: str = "mfa_required", mode: str = "entry") -> None:
    with _SessionFactory() as s:
        s.add(PaychexJob(job_id=job_id, company="acumen", status=status, mode=mode,
                         progress_current=0, progress_total=0, debug_urls=[]))
        s.commit()


def _job(job_id: str = "job-1") -> PaychexJob | None:
    with _SessionFactory() as s:
        return s.query(PaychexJob).filter_by(job_id=job_id).first()


# ── _wait_for_mfa_code ────────────────────────────────────────────────────────

def test_wait_for_mfa_code_returns_code_once_provider_yields():
    calls = {"n": 0}

    async def provider():
        calls["n"] += 1
        return "123456" if calls["n"] >= 3 else None

    slept: list[float] = []

    async def sleep(secs):
        slept.append(secs)

    code = asyncio.run(paychex_entry._wait_for_mfa_code(provider, sleep, wait_seconds=10, poll_seconds=2))
    assert code == "123456"
    assert slept == [2, 2]


def test_wait_for_mfa_code_gives_up_after_deadline():
    async def provider():
        return None

    async def sleep(_):
        pass

    code = asyncio.run(paychex_entry._wait_for_mfa_code(provider, sleep, wait_seconds=6, poll_seconds=2))
    assert code is None


def test_wait_for_mfa_code_skips_codes_already_tried():
    async def provider():
        return "111111"

    async def sleep(_):
        pass

    code = asyncio.run(paychex_entry._wait_for_mfa_code(
        provider, sleep, ignore={"111111"}, wait_seconds=4, poll_seconds=2,
    ))
    assert code is None


# ── _answer_mfa_with_human_code with a fake page ─────────────────────────────

class _FakeLocator:
    def __init__(self, visible: bool):
        self._visible = visible
        self.first = self

    async def is_visible(self):
        return self._visible

    async def check(self):
        pass


class _FakePage:
    """Just enough of Playwright's Page for the OTP helpers."""

    def __init__(self, accept: set[str]):
        self.accept = accept
        self.filled: list[str] = []
        self.clicked: list[str] = []

    async def fill(self, selector, value):
        self.filled.append(value)

    def locator(self, selector):
        return _FakeLocator(visible=(selector == "#otp-submit-button"))

    async def click(self, selector):
        self.clicked.append(selector)

    async def press(self, selector, key):
        pass

    async def wait_for_selector(self, selector, timeout=0):
        if self.filled and self.filled[-1] in self.accept:
            return None
        raise TimeoutError("dashboard never appeared")

    async def wait_for_timeout(self, ms):
        pass


def test_answer_mfa_submits_accepted_code_and_returns():
    page = _FakePage(accept={"654321"})
    statuses: list[dict] = []

    async def provider():
        return "654321"

    async def snap(_):
        pass

    asyncio.run(paychex_entry._answer_mfa_with_human_code(page, statuses.append, provider, snap))
    assert page.filled == ["654321"]
    assert page.clicked == ["#otp-submit-button"]
    assert statuses[0]["status"] == "mfa_required"
    assert statuses[-1]["status"] == "running"


def test_answer_mfa_rejected_codes_exhaust_attempts():
    page = _FakePage(accept=set())
    codes = iter(["111111", "222222"])
    statuses: list[dict] = []
    snaps: list[str] = []

    async def provider():
        return next(codes)

    async def snap(label):
        snaps.append(label)

    with patch.object(paychex_entry, "MFA_CODE_WAIT_SECONDS", 4):
        with pytest.raises(paychex_entry.MfaCodeTimeout):
            asyncio.run(paychex_entry._answer_mfa_with_human_code(page, statuses.append, provider, snap))
    assert page.filled == ["111111", "222222"]
    assert snaps == ["otp_rejected_attempt1", "otp_rejected_attempt2"]
    assert "didn't work" in statuses[2]["message"]


# ── POST /mfa/{job_id} ────────────────────────────────────────────────────────

def test_mfa_requires_admin_or_operator():
    _seed_job()
    r = client.post("/api/data/paychex-bot/mfa/job-1", json={"code": "123456"}, cookies=_cookie("associate"))
    assert r.status_code == 403


def test_mfa_rejects_non_numeric_or_wrong_length():
    _seed_job()
    for bad in ("12ab56", "123", "123456789"):
        r = client.post("/api/data/paychex-bot/mfa/job-1", json={"code": bad}, cookies=_cookie("operator"))
        assert r.status_code == 400, bad
    assert _job().mfa_code is None


def test_mfa_unknown_job_404():
    r = client.post("/api/data/paychex-bot/mfa/nope", json={"code": "123456"}, cookies=_cookie("admin"))
    assert r.status_code == 404


def test_mfa_refuses_finished_job():
    _seed_job(status="done")
    r = client.post("/api/data/paychex-bot/mfa/job-1", json={"code": "123456"}, cookies=_cookie("admin"))
    assert r.status_code == 400
    assert "not waiting" in r.json()["error"]


def test_mfa_stores_code_for_waiting_job():
    _seed_job(status="mfa_required")
    r = client.post("/api/data/paychex-bot/mfa/job-1", json={"code": " 123 456 "}, cookies=_cookie("operator"))
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert _job().mfa_code == "123456"
    assert asyncio.run(bot_routes._make_mfa_code_provider("job-1")()) == "123456"


def test_job_update_stamps_mfa_requested_at_and_status_exposes_mode():
    _seed_job(status="running", mode="login")
    bot_routes._job_update("job-1", status="mfa_required", message="type it")
    row = _job()
    assert row.mfa_requested_at is not None
    r = client.get("/api/data/paychex-bot/status/job-1", cookies=_cookie("operator"))
    assert r.status_code == 200
    assert r.json()["mode"] == "login"
    assert r.json()["status"] == "mfa_required"


# ── POST /login/{company} ─────────────────────────────────────────────────────

def test_login_rejects_unknown_company_and_viewer_role():
    r = client.post("/api/data/paychex-bot/login/acme", headers=_JSON, cookies=_cookie("admin"))
    assert r.status_code == 400
    r = client.post("/api/data/paychex-bot/login/acumen", headers=_JSON, cookies=_cookie("associate"))
    assert r.status_code == 403


def test_login_without_credentials_is_a_clear_500():
    with patch.dict(os.environ, {"PAYCHEX_ACUMEN_USER": "", "PAYCHEX_ACUMEN_PASS": ""}):
        with patch.object(bot_routes, "_load_credentials", return_value=("", "")):
            r = client.post("/api/data/paychex-bot/login/acumen", headers=_JSON, cookies=_cookie("admin"))
    assert r.status_code == 500
    assert "PAYCHEX_ACUMEN_USER" in r.json()["error"]


def test_login_creates_login_mode_job_and_schedules_login_only_run():
    scheduled: list[tuple] = []

    async def fake_run_bot(*args):
        scheduled.append(args)

    with patch.object(bot_routes, "_load_credentials", return_value=("user", "pw")):
        with patch.object(bot_routes, "_run_bot", fake_run_bot):
            r = client.post("/api/data/paychex-bot/login/maz", headers=_JSON, cookies=_cookie("operator"))
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert r.json()["mode"] == "login"
    row = _job(job_id)
    assert row is not None and row.mode == "login" and row.payroll_batch_id is None
    assert len(scheduled) == 1
    args = scheduled[0]
    assert args[0] == job_id and args[1] == "maz" and args[4] == []
    assert args[-1] is True  # login_only
