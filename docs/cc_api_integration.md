# Contractor Compliance API Integration

## What We Know

**Platform:** app.contractorcompliance.io — third-party SaaS used by EverDriven as the
central document hub for subcontractor compliance.

**API exists** but access requires a direct account/partnership with Contractor Compliance Inc.
It is not publicly accessible without credentials from your account manager.

### Confirmed endpoint pattern (from platform inspection)

```
GET {base_url}/contractors/{cc_id}/documents
Authorization: X-Api-Key {api_key}
Accept: application/json
```

Response is either a JSON array of document objects, or:
```json
{ "data": [...] }
```
or
```json
{ "documents": [...] }
```

### Document object fields (best-effort — confirm with CC support)

| Field           | Observed values          | Notes                        |
|-----------------|--------------------------|------------------------------|
| `documentName`  | string                   | Also seen as `name`          |
| `status`        | `APPROVED`, `DECLINED`, `PENDING` | Also `documentStatus`  |
| `expirationDate`| `YYYY-MM-DD` or `MM/DD/YYYY` | Also `expiry`           |

These field names are NOT confirmed by CC documentation. They were inferred from
integration behavior. Before enabling in production, run a test call against a known
driver and log the raw response to confirm field names.

## What Malik Needs to Provide

To wire the real CC API:

1. **`CONTRACTOR_COMPLIANCE_API_KEY`** — API key from your Contractor Compliance account.
   Set this in Railway env vars for the zpay-v2 backend service.

2. **`CONTRACTOR_COMPLIANCE_BASE_URL`** — if different from the default
   `https://app.contractorcompliance.io/api`. Confirm with CC support.

3. **Confirm field names** — the document field names above need to be validated.
   Once you have a key, hit `GET /contractors/{any_known_cc_id}/documents` and
   log the raw JSON. Then update `_parse_cc_document` in `everdriven_compliance.py`
   if field names differ.

4. **Webhook** (optional but recommended) — CC may support webhooks when a document
   is approved/declined. Ask CC support. If available, this removes the need for
   6-hour polling and gives real-time alerts.

## Current State in Z-Pay

The sync runs in `backend/services/everdriven_compliance.py`:

- `CONTRACTOR_COMPLIANCE_API_KEY` absent → sync skips silently with a warning log
- `CONTRACTOR_COMPLIANCE_API_KEY` present → sync polls every 6 hours, alerts on
  declined docs and expiring docs (14-day window)

No changes to this file are needed once the env var is set. The code is already wired.

## Driver Account Creation (Step 1)

**CC does NOT expose an API for creating driver accounts.** Drivers must self-register
at `https://app.contractorcompliance.io`. The Z-Pay "Send CC Invite" button
(`POST /onboarding/{id}/send-cc-invite`) emails the driver the registration URL.

After the driver registers, the admin enters their CC ID manually in the Z-Pay detail
page (`POST /onboarding/{id}/mark-cc-registered`). Once `cc_id` is set, the compliance
sync uses it for document monitoring.

## Env Vars Summary

| Var | Required for | Default |
|-----|-------------|---------|
| `CONTRACTOR_COMPLIANCE_API_KEY` | Document monitoring | (none — sync skips if absent) |
| `CONTRACTOR_COMPLIANCE_BASE_URL` | API base URL | `https://app.contractorcompliance.io/api` |
