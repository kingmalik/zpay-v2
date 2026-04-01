# Backend Audit Report

**Audited:** 2026-03-31
**Files reviewed:** app.py, db/models.py, db/crud.py, routes/upload.py, routes/rates.py, routes/people.py, routes/validate.py, routes/snapshot.py, routes/summary.py, routes/payroll_history.py, routes/batches.py, services/excell_reader.py, services/pdf_reader.py, services/build_rows.py, scripts/entrypoint.sh

---

## Critical Bugs (fix immediately)

### 1. `source_ref` assigned as a tuple expression, not a variable
**File:** `backend/services/excell_reader.py:211`

```python
source_ref=norm_str(row.source_ref) or f"{company_file}:{service_ref}:{person.person_id}",
```

The trailing comma makes this a discarded tuple expression (not a keyword argument inside Ride(...) — that call starts on line 237). The variable `source_ref` is never set by this line. The `Ride(...)` constructor below reads `source_ref` from an earlier scope (the value set by `norm_service_ref(row.trip_code)` two lines above), so every ride gets a trip code as its source_ref instead of the intended stable compound key. This silently breaks deduplication on re-import.

**Fix:** Remove the trailing comma and assign explicitly before the Ride constructor:
```python
source_ref = norm_str(row.source_ref) or f"{company_file}:{service_ref}:{person.person_id}"
```

---

### 2. `upload_maz` silently discards the injected DB session and creates a new unmanaged one
**File:** `backend/routes/upload.py:215`

```python
db: Session = SessionLocal()
```

The route already injects `db` via `Depends(get_db)`. At line 215 inside the handler body, `db` is reassigned to a brand-new raw session. The injected session (which FastAPI would clean up automatically via the dependency) is abandoned. The new session is closed in the `finally` block, but any exception raised before `bulk_insert_rides` (inside the debug loop, for example) leaves the injected session in an undefined state. FastAPI's transaction management and error handling no longer apply to the database work in this request.

**Fix:** Remove line 215. Pass the injected `db` directly to `bulk_insert_rides`. Remove the `try/finally` block wrapping the DB call.

---

### 3. `person_rides()` in crud.py crashes with KeyError on every call
**File:** `backend/db/crud.py:124-135`

`_ride_colmap()` returns a dict with keys: `ride_id`, `person_id`, `start_ts`, `date`, `distance_miles`, `base_fare`, `tips`, `adjustments`, `source_ref`, `service_key`, `code`.

`person_rides()` accesses: `cm["pk"]`, `cm["job_key"]`, `cm["job_name"]`, `cm["miles"]`, `cm["gross"]`, `cm["source_file"]`, `cm["source_page"]` — none of which exist in the dict. This is a `KeyError` crash on every invocation.

**Fix:** Align the column map keys with what `person_rides()` actually needs, or rewrite `person_rides()` to use the real column names (`ride_id`, `start_ts`, `code`).

---

### 4. `bulk_insert_rides()` in crud.py uses invalid `.in_()` on a Python tuple
**File:** `backend/db/crud.py:90`

```python
stmt = select(c_pid, c_key).where((c_pid, c_key).in_(pairs))  # type: ignore
```

A plain Python tuple of SQLAlchemy column objects has no `.in_()` method. This raises `AttributeError` at runtime whenever this deduplication path executes. The `# type: ignore` comment suppresses the type checker warning that would have caught this.

**Fix:** Use SQLAlchemy's `tuple_()` construct:
```python
from sqlalchemy import tuple_
stmt = select(c_pid, c_key).where(tuple_(c_pid, c_key).in_(pairs))
```

---

### 5. `get_service_default_rate()` queries a column that does not exist on the model
**File:** `backend/services/excell_reader.py:76`

```python
.filter(ZRateService.company == company)
```

`ZRateService` has `company_name`, not `company`. This raises `AttributeError` on any call. The function is currently dead (commented out in the import flow), but it will crash immediately if re-enabled.

**Fix:** Change to `ZRateService.company_name == company`.

---

### 6. `ensure_rate_services()` specifies a composite index that does not exist for on_conflict
**File:** `backend/db/crud.py:517-519`

```python
.on_conflict_do_nothing(
    index_elements=["source", "company_name", "service_key"]
)
```

The `z_rate_service` table has two separate unique constraints: `service_key` (globally unique, models.py line 58) and `(source, company_name, service_name)` (the named index on line 70). There is no composite index on `(source, company_name, service_key)`. PostgreSQL raises `ProgrammingError: there is no unique or exclusion constraint matching the ON CONFLICT specification` on the first upsert call.

**Fix:** Use an existing unique constraint:
```python
.on_conflict_do_nothing(index_elements=["service_key"])
```

---

### 7. Both upload paths use the same static string as `service_key` for every service
**File:** `backend/services/excell_reader.py:148`, `backend/services/pdf_reader.py:296`

Every Acumen service row gets `service_key = "acumen"` and every Maz service row gets `service_key = "maz"`. Since `service_key` is globally unique, only the very first service inserted with key `"acumen"` succeeds; all subsequent `ensure_rate_services()` calls for different service names silently do nothing (conflict on `service_key`). This means most services are never registered, rate lookups return zero, and payroll numbers are wrong for the majority of rides.

**Fix:** Build a unique service_key per service name, e.g.:
```python
service_key = f"acumen:{service_name.lower().replace(' ', '-')[:200]}"
```
`build_service_key_for_acumen` is already imported in `excell_reader.py` — use it.

---

### 8. Maz upload sets `external_id` to the driver's name instead of their numeric code
**File:** `backend/services/pdf_reader.py:361-362`

```python
driver_ext = norm_str((str(driver_name or "").strip() or None))
person = upsert_person(db, external_id=driver_ext, full_name=driver_name)
```

`driver_ext` is set to the full name string (same as `driver_name`), not the numeric code from the PDF "Code" column. `upsert_person()` first looks up by `external_id` — if a person exists with external_id = their name string, it finds them; otherwise it creates a duplicate. The actual driver code is already captured in the local `code` variable two lines above.

**Fix:**
```python
driver_ext = norm_str(code)  # use the PDF Code column, not the name
```

---

### 9. Profitability formula is inverted in summary.py vs all other pages
**File:** `backend/routes/summary.py:78`

`CLAUDE.md` defines: `Profitability = net_pay - z_rate` (partner payout minus company driver cost).

The summary page query labels the z_rate sum as `net_pay`:
```python
func.coalesce(func.sum(Ride.z_rate), 0).label("net_pay"),
```

Every downstream calculation on the summary page (withholding threshold, "Pay This Period") uses company cost (`z_rate`) as if it were driver payout (`net_pay`). This makes the payroll summary financially wrong — drivers' displayed earnings are actually the company's cost to service them, not what they were paid.

**Fix:** Sum `Ride.net_pay` separately and use it for driver payout. Sum `Ride.z_rate` for company cost.

---

### 10. `people.py` group_by uses a string literal `"name"` which is non-portable
**File:** `backend/routes/people.py:302`

```python
.group_by(Person.person_id, "name", Person.email, Person.firstalt_driver_id, Person.everdriven_driver_id)
```

The string `"name"` in `group_by()` is a raw SQL identifier reference. The actual SELECT expression for that column is `getattr(Person, "full_name", None)` labelled as `name`. On some PostgreSQL versions this resolves correctly; on others it fails. It is also fragile across query rewrites.

**Fix:** Use the column directly:
```python
.group_by(Person.person_id, Person.full_name, Person.email, Person.firstalt_driver_id, Person.everdriven_driver_id)
```

---

## Performance Issues

### 11. `rates_set` loads and updates every ride for a service name in Python
**File:** `backend/routes/rates.py:185-191`

When scope is "permanent", the code runs:
```python
all_rides = db.query(Ride).filter(Ride.service_name == service_name).all()
for r in all_rides:
    r.z_rate = new_rate
    ...
db.add_all(all_rides)
```

With thousands of rides, this loads every matching ride object into Python memory and sends an individual UPDATE per row. This is a full scan + N individual updates when one bulk UPDATE would suffice.

**Fix:**
```python
db.query(Ride).filter(Ride.service_name == service_name).update(
    {"z_rate": new_rate, "z_rate_source": "service_default", "z_rate_service_id": svc.z_rate_service_id},
    synchronize_session=False
)
```

### 12. `rates_unmatched` runs two full join queries loading all rides into memory
**File:** `backend/routes/rates.py:32-83`

Two `db.query(Ride, Person, PayrollBatch)` calls execute on every page load with no limits, loading entire Ride+Person+Batch tuples into Python. The median deviation calculation then iterates them all again in Python. On 5,000+ rides this is a significant page load time.

**Fix:** Use aggregated SQL queries instead of Python-side grouping. Compute median deviation in SQL using `PERCENTILE_CONT`.

### 13. `payroll_history` has N+1 query pattern per batch
**File:** `backend/routes/payroll_history.py:76-139`

All batches are loaded, then per-batch ride counts and balance queries are run separately in a loop. With 20+ batches this is 40+ additional queries per page render.

**Fix:** Fetch ride counts and z_rate sums in a single grouped subquery joined to the batch list.

### 14. `_reflect_ride()` issues a DB schema query on every call
**File:** `backend/db/crud.py:50-53`

`Table("ride", md, autoload_with=db.bind)` queries PostgreSQL's information_schema on every invocation. It is called by `people_rollup`, `person_rides`, and `person_summary`, each of which reflect independently. The schema never changes at runtime.

**Fix:** Cache the reflected table at module level (reflect once at import time).

### 15. Validate page re-parses every Excel and PDF file on every page load
**File:** `backend/routes/validate.py:256-316`

The `/validate` endpoint parses all files from disk, resolves rates, and computes aggregates synchronously on every GET request. With many weeks of files this can take seconds per request. There is no caching.

**Fix:** Cache results keyed by file mtime, or run validation asynchronously with results stored in DB/Redis.

---

## Code Quality / Dead Code

### 16. `KM_TO_MILES` constant defined twice in crud.py
**File:** `backend/db/crud.py:23` and `backend/db/crud.py:267`

The constant `KM_TO_MILES = 0.621371` is defined on line 23 and again on line 267 (with a comment "define once near top of file" — contradicting itself). Neither definition is used anywhere in the file.

### 17. `upload_home()` is dead code — its route decorator is commented out
**File:** `backend/routes/upload.py:70-130`

The `upload_home()` function at line 71 has its `@router.get("/")` decorator commented out. The function is 60 lines of inline HTML that can never be reached. It should be deleted.

### 18. Debug `print()` statements left active in production upload flow
**File:** `backend/routes/upload.py:47-50`, `backend/routes/upload.py:233-235`

Active debug prints in production:
- `_show_debug()` at lines 47-50 prints specific driver/date combos to stdout
- Lines 233-235 inside `upload_maz` prints "WANTED HITS" for hardcoded trip IDs `{"27117048", "27117069", "27117177"}`

These fire on every MAZ upload. The hardcoded trip IDs are specific to a past debugging session and have no operational value.

### 19. Large block of dead code inside the active ride-insertion loop
**File:** `backend/services/excell_reader.py:213-224`

A multi-line block is commented out using a triple-quoted string (docstring-style). This is evaluated as a string literal at runtime (just not assigned). It adds noise inside the per-row loop and is misleading.

### 20. `people.py` has ~130 lines of schema introspection for a fixed schema
**File:** `backend/routes/people.py:45-183`

Functions `_week_cols()`, `_source_col()`, `_company_source_cols()`, `_rate_col()`, `_miles_or_units_col()`, `_net_expr()`, `_ride_date_col()` all use `hasattr()`, `getattr()`, and try/except blocks to discover columns that have been fixed for months. `_net_expr()` at line 117 always returns `literal(0)` and is commented with "Temporary safe net expression." — meaning any caller gets zero for net pay. These functions exist from an earlier schema-agnostic design and should be replaced with direct model attribute access.

### 21. `person_summary()` silently queries a non-existent view every call
**File:** `backend/db/crud.py:211-231`

The function tries to reflect and query a `pay_summary` view, catching all exceptions silently. This view does not exist in the current schema. The result is `rad` and `wud` always return 0.0 with no warning or log entry.

### 22. `build_rows.py` is entirely unused
**File:** `backend/services/build_rows.py`

`details_to_rows()` and supporting helpers are defined here but nothing in the active codebase imports this module. The PDF reader has its own implementation of the same logic. This file should be reviewed and either integrated or deleted.

### 23. `_ride_column_map()` is a pointless wrapper
**File:** `backend/db/crud.py:25-26`

```python
def _ride_column_map(*a, **k):
    return _ride_colmap(*a, **k)
```

One function that does nothing but call another function with the same args. Not referenced anywhere. Delete it.

### 24. Duplicate `_templates` singleton pattern across 8+ route files
**Files:** routes/upload.py, rates.py, people.py, validate.py, payroll_history.py, summary.py, batches.py, insights.py, etc.

Every route file independently implements the same lazy-init singleton pattern for `Jinja2Templates`. Meanwhile `app.py` already creates a single shared templates instance and stores it at `app.state.templates`. Most routes ignore the shared instance and create their own.

**Fix:** Use `request.app.state.templates` everywhere (as `upload_acumen` already does correctly on line 155) and delete the per-file singleton boilerplate.

---

## Security

### 25. Default database password hardcoded in source code
**File:** `backend/routes/snapshot.py:58`, `backend/routes/snapshot.py:117`

```python
url = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://app:secret@db:5432/appdb"
)
```

The password `"secret"` is the actual production database password embedded in committed source code. Even if it's "only a default," it documents the credential and will end up in git history.

**Fix:** Remove the default password. Raise if `DATABASE_URL` is unset:
```python
url = os.environ["DATABASE_URL"]
```

### 26. File upload does not sanitize the filename before writing to disk
**File:** `backend/routes/upload.py:32-35`

```python
path = UPLOAD_DIR / file.filename
```

`file.filename` is user-controlled. A crafted filename like `../../etc/cron.d/pwned` would write outside `/tmp/payroll_uploads/`. `shutil.copyfileobj` follows the path without validation.

**Fix:** Use only the basename:
```python
path = UPLOAD_DIR / Path(file.filename).name
```

### 27. No CSRF protection on state-mutating POST routes
**Files:** `backend/routes/rates.py`, `backend/routes/people.py`, `backend/routes/batches.py`

Routes `/rates/set`, `/people/set-everdriven-id`, `/people/set-firstalt-id`, `/batches/{id}/delete` accept plain form POSTs with no CSRF token. A page on any origin can trigger payroll rate changes or batch deletions.

**Fix:** Add CSRF middleware or signed form tokens to all state-mutating POST routes.

### 28. `validate.py` hardcodes the developer's personal home directory path
**File:** `backend/routes/validate.py:26-27`

```python
ACUMEN_DIR = Path("/Users/malikmilion/Downloads/Acumen")
MAZ_DIR    = Path("/Users/malikmilion/Downloads/Maz")
```

This path only works on Malik's development machine. On any other deployment (Docker, mom's Mac) the validation page silently shows no data. The path also exposes the developer's username.

**Fix:**
```python
import os
ACUMEN_DIR = Path(os.environ.get("ACUMEN_VALIDATE_DIR", "/data/in/acumen"))
MAZ_DIR    = Path(os.environ.get("MAZ_VALIDATE_DIR", "/data/in/maz"))
```

---

## Recommendations (ordered by impact)

**Fix first — payroll numbers are wrong:**
1. `[excell_reader.py:211]` Fix `source_ref` tuple bug — Acumen rides get wrong source ref, breaking deduplication.
2. `[excell_reader.py:148, pdf_reader.py:296]` Fix `service_key` to be unique per service — root cause of mass zero-rate rides.
3. `[pdf_reader.py:361]` Fix Maz `driver_ext` to use code, not name — breaks person matching.
4. `[summary.py:78]` Fix `net_pay` label that actually sums `z_rate` — payroll summary shows wrong earnings.
5. `[crud.py:517]` Fix `on_conflict_do_nothing` to reference an existing index — upserts may crash.

**Fix next — runtime crashes:**
6. `[crud.py:124]` Fix `person_rides()` KeyErrors.
7. `[crud.py:90]` Fix `bulk_insert_rides()` tuple `.in_()` crash.
8. `[upload.py:215]` Remove double-session bug in `upload_maz`.

**Fix next — security:**
9. `[upload.py:32]` Sanitize upload filename (path traversal).
10. `[snapshot.py:58]` Remove hardcoded database credentials.
11. `[rates.py, people.py, batches.py]` Add CSRF tokens.
12. `[validate.py:26]` Move hardcoded local paths to environment variables.

**Fix when time allows — cleanup:**
13. Remove dead `upload_home()`, `_show_debug()`, `build_rows.py`, `_ride_column_map()`.
14. Remove duplicate `KM_TO_MILES` constant.
15. Centralize Jinja2Templates to use `request.app.state.templates` everywhere.
16. Replace `_net_expr()` (always returns 0) with real net pay logic.
17. Fix typos in `entrypoint.sh`: `ACCUMEN`, `ACUMMEN`, `accument` → `ACUMEN`, `acumen`.
18. Replace `rates_set` Python-loop update with a single bulk SQL UPDATE.
