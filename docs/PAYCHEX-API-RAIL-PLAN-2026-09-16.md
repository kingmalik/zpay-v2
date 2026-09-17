# Paychex API rail — build plan (2026-09-16)

Replaces the Playwright pay-entry bot with the official Paychex Flex External API (docs/PAYCHEX-API-SPEC-2026-09-16.md).
Humans still review + submit in Flex — the API has no submit call, by design (law: automation types, humans move money).

## Config (per company bucket: ACUMEN, MAZ)
- PAYCHEX_API_CLIENT_ID_<CO>, PAYCHEX_API_CLIENT_SECRET_<CO> — from Flex → Company Settings → Connected Applications → Create App
- PAYCHEX_API_COMPANY_ID_<CO> — Paychex companyId (discover via GET /companies once; then pin)
- PAYCHEX_API_1099_COMPONENT_ID_<CO> — earnings pay component that applies to INDEPENDENT_CONTRACTOR (pick from GET paycomponents listing)
- PAYCHEX_API_ENABLED=0/1 — feature flag; admin-gated UI until Malik releases
- Base URL https://api.paychex.com ; token POST /auth/oauth/v2/token client_credentials (TTL per response expires_in)

## Flow (POST /api/data/paychex-api/push/{batch_id})
1. Resolve company bucket from batch (existing _resolve_company) → creds.
2. Preview (always computed first, returned by POST .../preview/{batch_id}):
   - rows = _build_summary(batch) rows with pay_this_period > 0 and not withheld (same filter as bot push)
   - workers = GET /companies/{companyId}/workers (paginate all) → map employeeId → (workerId, workerType, name)
   - each row: match row["code"] == employeeId; require workerType == INDEPENDENT_CONTRACTOR; unmatched/wrong-type rows listed
   - pay period = GET payperiods status INITIAL|ENTRY whose startDate/endDate equal batch.period_start/period_end (fallback: checkDate == batch check date if stored; else error listing open periods)
   - component = configured id; verify it exists and appliesToWorkerTypes includes INDEPENDENT_CONTRACTOR
   - total amount, count
3. Push: refuse if any unmatched rows (unless body {"skip_unmatched": true}), refuse if a paychex_api_check row already exists for (batch_id, person_id) (idempotency), else
   POST /companies/{companyId}/checks with one CheckResource per row: payPeriodId, workerId, checkCorrelationId=str(person_id), blockAutoDistribution=false, earnings=[{componentId, payAmount: "%.2f"}]
   Record each result in paychex_api_check (batch_id, person_id, worker_id, pay_period_id, paycheck_id, amount, status, error, created_at). Partial failure: record per-row errors, return 207-style summary.
   On ≥1 success stamp batch.paychex_exported_at (existing semantics) and write BatchWorkflowLog entry.
4. GET /api/data/paychex-api/{company}/health: token ok, company name, contractor count, open pay periods, candidate 1099 components (id, name, appliesToWorkerTypes) — used to pick PAYCHEX_API_1099_COMPONENT_ID.

## Roles
push/preview: admin + operator (mom runs payroll). health: admin.

## Tests (mock HTTP; no network)
token caching + refresh on expiry; worker map + pagination; period match + no-match error; component validation; preview unmatched; push idempotency; partial failure recording; flag off → 404/403.
