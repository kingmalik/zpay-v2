# ED GraphQL Introspection Result

Script: `backend/scripts/ed_introspect.py`
Date: not yet run against prod

The introspection script was written as part of Phase 4 of the driver scorecard build.
It could not be executed locally because the local `.env` has placeholder credentials
(`EVERDRIVEN_USERNAME=dev`, `EVERDRIVEN_PASSWORD=dev`) and no Railway CLI session is active.

**To run against prod:**
1. `railway login` (authenticate the CLI)
2. `railway link` (link to the zpay-v2 project)
3. `railway run python -m backend.scripts.ed_introspect`

The script will write `data/ed_schema_dump.json` (or update this file on failure).

**If timestamp fields are found** (`acceptedAt`, `arrivedAt`, `completedAt`, `startedAt`,
`lastUpdatedAt`, `statusHistory`, `events`), extend `_RUNS_QUERY` in
`backend/services/everdriven_service.py` and update `_normalise_run()` to surface them.

**If not found**, Phase 2 polling-based inference (Phase 2 commit `e4776e4`) is the
source of truth for all ED trip timestamps. No changes needed.
