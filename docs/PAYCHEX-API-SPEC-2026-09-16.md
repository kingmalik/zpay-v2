# Paychex External API (1.0) — Spec for Z-Pay Contractor Pay Automation

Source: https://developer.paychex.com/documentation (spec: https://developer.paychex.com/sites/default/files/apidocument/openapi-merge-develop.210-public.json, OpenAPI 3.0.3, "External API 1.0", 68 paths) plus /client, /partner, /getting-started/*, /resources/*, /use_cases.

## 1. Access model

Two paths, per /client and /partner:

- **Client path (self-service, single company):** log into Flex, Company Settings → Connected Applications → "Create App" (needs Super Admin/Security Admin). Name it, pick data-access scopes, done — "up and running within minutes." Key/secret issued immediately (/resources/authentication: "for clients the API key will be generated automatically"). No formal approval step documented.
- **Partner/ISV path (multi-client):** (1) questionnaire, (2) Corporate Partnerships Team evaluates, (3) conditional approval + partner app created, (4) build/test in a Paychex-provided sandbox, (5) demo to Paychex, (6) production key/secret scoped to approved verbs/endpoints. No timeline given for any step.
- **Not documented:** whether a business that isn't itself the Flex client, but acts on behalf of other companies' Flex accounts (Z-Pay's situation — two client companies it doesn't own), can get production creds without full Partner review. Client-linking (`POST /management/requestclientaccess` with the client's 8-digit `displayId` → returns an `approvalLink` the client opens under Integrated Applications to approve) is described only under the Partner flow.
- **Sandbox:** per /getting-started/sandbox, granted "once your partnership with Paychex is approved" — tied to Partner. Not documented whether Client self-service also gets one.
- **Auth:** `POST /auth/oauth/v2/token`, form-urlencoded `grant_type=client_credentials`, `client_id`, `client_secret`. Returns `access_token`, `expires_in`, `scope` (spec says always `"oob"`), `token_type: Bearer`. No refresh token. Spec example shows `expires_in: 600`; /resources/authentication says the real default is 60 minutes — treat the doc page as authoritative.
- **Scopes:** not real OAuth scopes — access is gated by data-access permissions chosen at app creation (client path) or approved verbs/endpoints (partner path).
- **One key, multiple clients:** confirmed — "you can use the same key and secret between them" (/resources/authentication).

## 2. Payroll write path

- **List pay periods:** `GET /companies/{companyId}/payperiods` (`status[]`, `from`, `to`). Returns `payPeriodId`, `intervalCode`, `status` (`INITIAL|ENTRY|PROCESSING|COMPLETED|COMPLETED_BY_MEC|REISSUED|RELEASED|REVERSED`), `description`, `startDate`, `endDate`, `submitByDate`, `checkDate`, `checkCount`. Also `GET .../payperiods/{payperiodId}`.
- **Create checks, multiple workers at once:** `POST /companies/{companyId}/checks` ("Add a check for one or more worker within a company for an available pay period"), body = array of `CheckResource`:
  ```json
  [{"payPeriodId":"850002407928035","workerId":"00DCE1NVK4DFN01LEJE5",
    "checkCorrelationId":"1","blockAutoDistribution":false,
    "earnings":[{"componentId":"850001539952899","payAmount":"300.60"}]}]
  ```
  Fields: `workerId`, `paycheckId` (read-only), `payPeriodId`, `checkCorrelationId` (required when batching), `blockAutoDistribution`, `earnings[]`/`deductions[]`/`taxes[]`/`informational[]` (all `PayComponentResource`), `checkDate`. Each earnings line needs `componentId` + one of `payHours`(±`payRate`/`payRateId`) / `payUnits`(±rate) / **`payAmount`** — flat `payAmount` against a contractor-eligible component is the 1099-NEC pattern. Optional overrides: `jobId`, `laborAssignmentId`.
  Single-worker equivalent: `POST /workers/{workerId}/checks`; also `GET/DELETE /workers/{workerId}/checks/{externalCheckId}`.
- **Contractor worker type — confirmed:** `PayComponentResource.appliesToWorkerTypes` enumerates `EMPLOYEE` and `INDEPENDENT_CONTRACTOR`; error `API-57` on the checks POST = "pay component doesn't support the corresponding worker type," i.e. the API validates this. Find contractor-eligible components via `GET /companies/{companyId}/paycomponents` (filters `effectonpay`, `asof`, `classificationtype`, `name`) and inspect `appliesToWorkerTypes`.
- **Edit after creation:** `POST /checks/{checkId}/checkcomponents` (add line), `PATCH`/`DELETE /checks/{checkId}/checkcomponents/{checkComponentId}`, `DELETE /checks?payperiodid={id}&deletebyuserid=true` (bulk-delete, scoped to caller).
- **Submit/finalize — not an API action.** No endpoint anywhere to "process/submit/release" a pay period; `submitByDate` is informational only. Checks POSTed via API stage into the pay period; a human still opens Flex to run/submit payroll. Matches Z-Pay's stage-then-human-submit intent.

## 3. Worker read path

- `GET /companies/{companyId}/workers` — filters `givenname`, `familyname`, `legallastfour`, `employeeid`, `from`/`to`, `locationid`, `status`. **No `workerType` filter** — pull all and filter client-side. Returns `workerId`, `employeeId`, `workerType`, `exemptionType`, `workState`, `name`, `organization`, `currentStatus`, `communications[]`. Paginated.
- `GET /workers/{workerId}` — full profile (with `Accept: application/vnd.paychex.workers.v1+json`: DOB, sex, ethnicity, `legalId`, job, organization, supervisor).
- `workerType`: `EMPLOYEE` (W-2) vs `INDEPENDENT_CONTRACTOR` (1099) — the field to map drivers against.
- Create: `POST /companies/{companyId}/workers` with `workerType:"INDEPENDENT_CONTRACTOR"` supported, creates `IN_PROGRESS` worker (required: `givenName`, `familyName`, `workerType`; batch uses `workerCorrelationId`). Per /resources/worker: cannot create a Flex "CONTRACTOR" (company-level vendor) or "USER" via API — only individual 1099 workers.

## 4. Webhooks

- `GET /management/domains` (topics, Client vs Partner apps differ slightly) → `POST /management/hooks` with `uri`, `authentication` (`NO_AUTH`/`BASIC_AUTH`/`APIKEY`/`OAUTH2`/`OAUTH2_BASIC`), `domains[]`, optional `companyId` (omit = all linked clients). `GET /management/hooks`, `GET/DELETE .../{hookId}`.
- Relevant domains: `PAY_PERIOD`, `WRKR_EMPL`, `WRKR_CMP`, `CLT_ACCESS` (partner-only, fires on client approval), `NET_PAY_DSTRB`. Full field lists: /getting-started/paychex-webhooks.
- Delivery: non-2xx retried every 5 min until success; Paychex "may reach out to disable your queue" on repeated failure.

## 5. Rate limits, versioning, "contact your rep"

- `/resources/rate-limiting` is flagged **"Coming soon later this September!"** — treat as pending: 10,000 req/min per partner, 2,000 req/sec burst; `X-RateLimit-Limit/Remaining/Reset` headers, `Retry-After` on 429; no documented path to raise limits.
- **Versioning:** vendor media types (e.g. `application/vnd.paychex.payroll.checks.v1+json`), bumped only on breaking changes; additions are optional fields with defaults; `links` in responses indicate the next valid media type.
- **"Contact rep" moments:** bulk-linking many clients to one app; a client needing help linking; anything not covered above (production access without Partner review, sandbox for Client path, real rate-limit numbers once live).

## 6. Rep call questions

1. Z-Pay runs payroll writes for two Flex client companies it doesn't own — does that need full Partner/ISV onboarding, or can each client self-service "Create App" and hand Z-Pay the key/secret (docs say one key/secret can cover multiple client accounts)?
2. If Partner onboarding is required, what's the realistic end-to-end timeline, and does the Client self-service path get a sandbox too, or only Partner?
3. What data-access scopes do we grant at app creation to cover read workers, read pay periods, write checks/check components, read pay components — is that granular in the Client UI or all-or-nothing?
4. Real token TTL: spec example says 600 sec, your docs page says 60 min — which is correct, and confirm no refresh token exists.
5. For `POST /companies/{companyId}/checks`, is there any way to know staged checks passed Flex-side validation (tax setup, direct deposit, YTD limits) before a human opens Flex, beyond the documented 400 errors?
6. Confirm there's truly no API call to submit/release a pay period — intentionally excluded from v1.0, or staged for later?
7. `GET /companies/{companyId}/workers` has no `workerType` filter — any private/beta param, or must we page through all workers and filter client-side?
8. Are the rate-limit numbers live now, or only once "coming soon" ships — and do two client companies under one app share one bucket or get separate ones?

## 7. Verdict

Z-Pay can plausibly replace the browser bot: the API supports exactly the write shape needed — batch `POST /companies/{companyId}/checks` with `payAmount` earnings against `INDEPENDENT_CONTRACTOR`-eligible pay components, referencing `workerId`/`payPeriodId` pulled from the workers and pay-periods GETs — and it deliberately stops short of submitting payroll, preserving the human-review-and-submit-in-Flex step Z-Pay wants. The one thing most likely to block this is **access model, not API shape**: the docs only clearly describe self-service credentials for a company managing its own Flex account, or full Partner/ISV review for a business acting across client companies it doesn't own — and it's undocumented which bucket a small operator running payroll for two client companies it works with (but doesn't own) falls into, or how long that takes. That's question 1 and should be resolved on the call before any build starts.
