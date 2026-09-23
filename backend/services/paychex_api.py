"""
backend/services/paychex_api.py
=================================
Paychex Flex External API client — replaces the Playwright pay-entry bot
(backend/routes/paychex_bot.py) with the official REST API. This client only
ever *stages* checks into an open pay period; there is no submit/release
endpoint in the Paychex API (by design — humans still open Flex and submit
payroll, per the "automation types, humans move money" law).

See docs/PAYCHEX-API-SPEC-2026-09-16.md for the spec notes this was built
from, and docs/PAYCHEX-API-RAIL-PLAN-2026-09-16.md for the build plan.

Config (per company bucket: ACUMEN, MAZ) — all read from env, never hardcoded:
    PAYCHEX_API_CLIENT_ID_<CO>
    PAYCHEX_API_CLIENT_SECRET_<CO>
    PAYCHEX_API_COMPANY_ID_<CO>          — Paychex companyId (pinned once, see plan)
    PAYCHEX_API_1099_COMPONENT_ID_<CO>   — earnings component used for 1099-NEC pay
    PAYCHEX_API_ENABLED=0/1              — feature flag (checked by the route layer)

Assumptions made where the spec was silent (flagged clearly so a real-API
smoke test can catch a wrong guess fast):
  - Token TTL: the spec's example payload says 600s but Paychex's own docs
    page says 60 minutes is the real default — we trust `expires_in` in the
    actual token response either way and only fall back to a 3600s default
    if that field is somehow missing.
  - Worker pagination: no response envelope example is given. We accept
    either a bare JSON list (single page) or a dict wrapping the list under
    "content"/"items"/"workers"/"results", optionally with a HAL-style
    `links: [{"rel": "next", "href": ...}]` array. We follow `rel=next`
    when present; otherwise we page via `offset`/`limit` until a short page
    comes back. This needs to be confirmed against the real API before the
    push endpoint is used live.
  - Check staging: the plan describes "one CheckResource per row" against
    `POST /companies/{companyId}/checks`. We submit ONE HTTP call per row
    (a single-element array body per call) rather than batching every row
    into one call, so one worker's failure never blocks or gets entangled
    with another's, and each row's staged/failed result records
    independently — this matches the plan's "record per-row errors" /
    "partial failure" requirements without guessing at a batched-response
    shape the spec never shows.
"""

from __future__ import annotations

import os
import time
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterable

import requests

# ── Constants ────────────────────────────────────────────────────────────────

PAYCHEX_API_BASE_URL = "https://api.paychex.com"
TOKEN_PATH = "/auth/oauth/v2/token"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_TOKEN_TTL_SECONDS = 3600  # /resources/authentication: real default is 60 min
TOKEN_REFRESH_SKEW_SECONDS = 30  # refresh slightly before the cached token actually expires
WORKERS_PAGE_SIZE = 50  # Paychex API-40 "The limit is not valid" above 50 (verified live 2026-09-22)
CONTRACTOR_WORKER_TYPE = "INDEPENDENT_CONTRACTOR"
OPEN_PAY_PERIOD_STATUSES: tuple[str, ...] = ("INITIAL", "ENTRY")

# Shared across PaychexApiClient instances within a process so a token fetched
# for one request is reused by the next, per company bucket. {bucket: (token, expires_at_epoch)}
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


class PaychexApiConfigError(RuntimeError):
    """Raised when required PAYCHEX_API_* env vars are missing for a company bucket."""


class PaychexApiError(RuntimeError):
    """Raised when Paychex returns an HTTP error or an unusable response body."""

    def __init__(self, message: str, status_code: int | None = None, payload: object = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


# ── Small stateless helpers (HTTP-body shape handling) ──────────────────────

def _env(company_bucket: str, suffix: str) -> str:
    return os.environ.get(f"PAYCHEX_API_{suffix}_{company_bucket.upper()}", "")


def _safe_json(resp: requests.Response) -> object:
    try:
        return resp.json()
    except ValueError:
        return None


def _extract_items(body: object) -> list[dict]:
    """Pull the list of records out of either a bare list or a wrapped envelope."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("content", "items", "workers", "results"):
            value = body.get(key)
            if isinstance(value, list):
                return value
    return []


def _next_link(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    links = body.get("links")
    if not isinstance(links, list):
        return None
    for link in links:
        if isinstance(link, dict) and link.get("rel") == "next" and link.get("href"):
            return str(link["href"])
    return None


def _error_message(resp: requests.Response) -> str:
    body = _safe_json(resp)
    if isinstance(body, dict):
        for key in ("message", "error", "error_description", "errors"):
            if body.get(key):
                return f"HTTP {resp.status_code}: {body[key]}"
    text = (resp.text or "").strip()
    return f"HTTP {resp.status_code}: {text[:300] or 'no response body'}"


def _extract_paycheck_id(body: object) -> str | None:
    if isinstance(body, list) and body and isinstance(body[0], dict):
        pid = body[0].get("paycheckId")
        return str(pid) if pid is not None else None
    if isinstance(body, dict):
        pid = body.get("paycheckId")
        return str(pid) if pid is not None else None
    return None


def _to_iso_date(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return str(value)[:10]


# ── Client ───────────────────────────────────────────────────────────────────

class PaychexApiClient:
    """Talks to the Paychex Flex External API for one company bucket ("acumen"|"maz").

    `transport` is an optional injection point for tests: a callable with the
    same signature as `requests.Session.request` (method, url, **kwargs) ->
    Response-like object. When omitted, a real `requests.Session` is used, so
    tests may also patch `requests.Session.request` globally instead.
    """

    def __init__(self, company_bucket: str, transport: Callable[..., "requests.Response"] | None = None):
        if not company_bucket:
            raise PaychexApiConfigError("company_bucket is required")
        self.company_bucket = company_bucket.strip().lower()
        self.client_id = _env(self.company_bucket, "CLIENT_ID")
        self.client_secret = _env(self.company_bucket, "CLIENT_SECRET")
        self.company_id = _env(self.company_bucket, "COMPANY_ID")
        self.component_id = _env(self.company_bucket, "1099_COMPONENT_ID")
        self._session = requests.Session()
        self._transport = transport or self._session.request

    def _require_config(self) -> None:
        missing = [
            name for name, value in (
                ("CLIENT_ID", self.client_id),
                ("CLIENT_SECRET", self.client_secret),
                ("COMPANY_ID", self.company_id),
            ) if not value
        ]
        if missing:
            envs = ", ".join(f"PAYCHEX_API_{m}_{self.company_bucket.upper()}" for m in missing)
            raise PaychexApiConfigError(
                f"Paychex API not configured for '{self.company_bucket}': missing {envs}"
            )

    def _get_token(self) -> str:
        cached = _TOKEN_CACHE.get(self.company_bucket)
        now = time.time()
        if cached and cached[1] - TOKEN_REFRESH_SKEW_SECONDS > now:
            return cached[0]

        self._require_config()
        resp = self._transport(
            "POST",
            f"{PAYCHEX_API_BASE_URL}{TOKEN_PATH}",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        if resp.status_code >= 400:
            raise PaychexApiError("Paychex token request failed", status_code=resp.status_code, payload=_safe_json(resp))

        body = _safe_json(resp)
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            raise PaychexApiError("Paychex token response missing access_token", payload=body)

        expires_in = (isinstance(body, dict) and body.get("expires_in")) or DEFAULT_TOKEN_TTL_SECONDS
        _TOKEN_CACHE[self.company_bucket] = (token, now + float(expires_in))
        return token

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        token = self._get_token()
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {token}", "Accept": "application/json"}
        url = path if path.startswith("http") else f"{PAYCHEX_API_BASE_URL}{path}"
        return self._transport(method, url, headers=headers, timeout=DEFAULT_TIMEOUT_SECONDS, **kwargs)

    def _paginate(self, path: str) -> list[dict]:
        items: list[dict] = []
        offset = 0
        next_url: str | None = None
        while True:
            resp = self._request("GET", next_url) if next_url else self._request(
                "GET", path, params={"limit": WORKERS_PAGE_SIZE, "offset": offset}
            )
            if resp.status_code >= 400:
                raise PaychexApiError(f"Paychex GET {path} failed", status_code=resp.status_code, payload=_safe_json(resp))
            body = _safe_json(resp)
            page_items = _extract_items(body)
            items = items + page_items
            next_url = _next_link(body)
            if next_url:
                continue
            if len(page_items) < WORKERS_PAGE_SIZE:
                break
            offset += WORKERS_PAGE_SIZE
        return items

    def get_access_token(self) -> str:
        """Public wrapper around the cached token fetch — used by the /health route
        to prove credentials work without needing a full data call."""
        return self._get_token()

    def get_workers(self) -> list[dict]:
        """GET /companies/{companyId}/workers, paginated (see module docstring for the pagination assumption)."""
        self._require_config()
        return self._paginate(f"/companies/{self.company_id}/workers")

    def get_pay_periods(self, statuses: Iterable[str]) -> list[dict]:
        """GET /companies/{companyId}/payperiods?status=...&status=..."""
        self._require_config()
        resp = self._request(
            "GET", f"/companies/{self.company_id}/payperiods", params={"status": list(statuses)}
        )
        if resp.status_code >= 400:
            raise PaychexApiError("Failed to list Paychex pay periods", status_code=resp.status_code, payload=_safe_json(resp))
        return _extract_items(_safe_json(resp))

    def get_open_pay_periods(self) -> list[dict]:
        return self.get_pay_periods(OPEN_PAY_PERIOD_STATUSES)

    def get_pay_components(self) -> list[dict]:
        """GET /companies/{companyId}/paycomponents."""
        self._require_config()
        resp = self._request("GET", f"/companies/{self.company_id}/paycomponents")
        if resp.status_code >= 400:
            raise PaychexApiError("Failed to list Paychex pay components", status_code=resp.status_code, payload=_safe_json(resp))
        return _extract_items(_safe_json(resp))

    def get_company_name(self) -> str | None:
        """Best-effort company display name via GET /companies. Returns None on any failure —
        supplementary info for the health endpoint, never worth failing the whole call over."""
        try:
            self._require_config()
            resp = self._request("GET", "/companies")
            if resp.status_code >= 400:
                return None
            for company in _extract_items(_safe_json(resp)):
                if str(company.get("companyId")) == str(self.company_id):
                    return company.get("name") or company.get("companyName")
        except (PaychexApiConfigError, PaychexApiError, requests.RequestException):
            return None
        return None

    def stage_checks(self, checks: list[dict]) -> list[dict]:
        """Stage one check per row via POST /companies/{companyId}/checks.

        Each item in `checks` needs: person_id, worker_id, pay_period_id,
        component_id, amount. Returns a new list of result dicts (never
        mutates `checks`): {person_id, status: "staged"|"failed",
        paycheck_id, error}. One row's failure never stops the rest.
        """
        self._require_config()
        return [self._stage_one_check(check) for check in checks]

    def _stage_one_check(self, check: dict) -> dict:
        person_id = check["person_id"]
        try:
            pay_amount = f"{Decimal(str(check['amount'])):.2f}"
        except (InvalidOperation, KeyError, TypeError) as exc:
            return {"person_id": person_id, "status": "failed", "paycheck_id": None, "error": f"invalid amount: {exc}"}

        payload = [{
            "payPeriodId": check["pay_period_id"],
            "workerId": check["worker_id"],
            "checkCorrelationId": str(person_id),
            # No blockAutoDistribution key at all. Paychex documents it as optional
            # ("used optionally for blocking the auto distribution ... if they are
            # setup for auto distribution") and neither company has the Job Costing /
            # Labor Distribution product. Sending it with either value came back
            # API-13 "client does not contain required products" on every check
            # (2026-09-23, both companies). A human in Pay Entry types only the
            # 1099-NEC amount, so the check carries only worker, period, and amount.
            "earnings": [{"componentId": check["component_id"], "payAmount": pay_amount}],
        }]
        try:
            resp = self._request("POST", f"/companies/{self.company_id}/checks", json=payload)
        except requests.RequestException as exc:
            return {"person_id": person_id, "status": "failed", "paycheck_id": None, "error": f"network error: {exc}"}

        if resp.status_code >= 400:
            return {"person_id": person_id, "status": "failed", "paycheck_id": None, "error": _error_message(resp)}

        return {
            "person_id": person_id,
            "status": "staged",
            "paycheck_id": _extract_paycheck_id(_safe_json(resp)),
            "error": None,
        }
