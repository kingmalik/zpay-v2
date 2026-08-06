# S10 — Season Assignment Board ("Corridor Board + Loop Builder")

> Planned 2026-08-06. Origin: mom's WhatsApp voice note 8/3 + Malik scope session.
> Mission: mom assigns ALL 2026-27 school-year rides to drivers this month. This tool makes that
> a review-and-approve job instead of a by-hand puzzle.

## Business rules (locked with Malik)

1. **Pool, then batch.** Rides arrive one-by-one (inbox auto-intake, already live) or via sheet
   upload. They pool as `season_ride` rows with status `unassigned`. Mom assigns in sittings on
   the board. Accept-the-offer (fast, existing S5 intake) and assign-a-driver (slow, batch) are
   decoupled decisions.
2. **Corridor grouping.** Rides grouped by (pickup_city → dropoff_city) per district, AM/PM,
   opposite corridors shown adjacent (Kirkland→Redmond next to Redmond→Kirkland).
3. **Student continuity.** FA routes are per-student: same (source, school, number) = same student.
   IB (morning) + OB (afternoon) legs pair into a "student day" — same driver both legs by
   default. Manual override allowed (one-offs happen).
4. **Chain rule.** Leg B chains after leg A iff drive(A.dropoff → B.pickup) + BUFFER fits before
   B.pickup_time, and the union of requirements stays satisfiable by one driver.
5. **Standing loops, not daily puzzles.** Output = each driver's standing weekly schedule.
   Per-weekday variants (day markers M/W/F etc., early-release later).
6. **Requirement walls.** Ride flags: wheelchair, car_seat, booster, harness, monitor.
   Driver capabilities on Person: car_seat, booster, harness, monitor_ok, wheelchair_vehicle.
   Monitor = FirstAlt provides the person; our side only needs driver monitor_ok. A ride's flags
   must be covered by the driver's capabilities (with manual override).
7. **School address book.** School extracted from route identity; address/city filled once by mom,
   inherited by every ride at that school forever.
8. **Law 7 unchanged** — nothing here sends anything to drivers.

## Schema (migration `s10_season_board`, down_revision = current alembic head — CHECK `alembic heads` first)

All additive, online-safe. JSON columns follow the `JSONB().with_variant(JSON, "sqlite")` pattern.

### school
| col | type | notes |
|---|---|---|
| school_id | serial PK | |
| name | text NOT NULL UNIQUE | normalized: lower, single-spaced |
| display_name | text NOT NULL | original casing |
| address | text NULL | mom fills |
| city | text NULL | mom fills or derived from address |
| district | text NULL | e.g. "Lake Washington" |
| notes | text NULL | |
| created_at / updated_at | timestamptz | server_default NOW() |

### season_ride
| col | type | notes |
|---|---|---|
| season_ride_id | serial PK | |
| season | text NOT NULL default '2026-27' | |
| source | text NOT NULL default 'firstalt' | firstalt/everdriven/sheet/manual |
| intake_id | int FK ride_intake NULL | link back to offer |
| route_school | text NOT NULL | identity, same conventions as Ride.route_* |
| route_direction | text NOT NULL | 'IB' or 'OB' |
| route_number | text NOT NULL | zero-padded |
| route_is_odt | bool NOT NULL default false | |
| school_id | int FK school NULL | |
| days | text NULL | subset of 'M,T,W,R,F'; NULL = Mon–Fri |
| pickup_address / dropoff_address | text NULL | |
| pickup_city / dropoff_city | text NULL | extracted (city_extract) or from school |
| pickup_time / dropoff_time | text NULL | 'HH:MM' 24h |
| miles | numeric(6,1) NULL | |
| net_pay | numeric(8,2) NULL | |
| requires | JSONB NOT NULL default '{}' | {wheelchair, car_seat, booster, harness, monitor} bools |
| status | text NOT NULL default 'unassigned' | unassigned/assigned/inactive |
| assigned_person_id | int FK person NULL | |
| loop_id | int FK driver_loop NULL | |
| loop_position | int NULL | order within loop |
| notes | text NULL | |
| created_at / updated_at | timestamptz | |

Indexes: UNIQUE (season, source, route_school, route_direction, route_number, route_is_odt) — the
dedupe key; plus (season, status).

### driver_loop
| col | type | notes |
|---|---|---|
| loop_id | serial PK | |
| season | text NOT NULL | |
| label | text NOT NULL | e.g. "AM 3 — Kirkland↔Redmond" |
| day_part | text NOT NULL | 'AM' / 'PM' / 'MID' |
| days | text NULL | same convention as season_ride.days |
| person_id | int FK person NULL | NULL until assigned |
| status | text NOT NULL default 'proposed' | proposed/confirmed/dismissed |
| origin | text NOT NULL default 'system' | system/manual |
| meta | JSONB default '{}' | slack minutes, builder version, requirement profile |
| created_at / updated_at | timestamptz | |

### person (alter)
+ `capabilities` JSONB NULL — {car_seat, booster, harness, monitor_ok, wheelchair_vehicle} bools.

## Services

### backend/services/city_extract.py
`extract_city(address: Optional[str]) -> Optional[str]`
- WA city whitelist (King/Snohomish/Pierce — full list in module constant, Title Case canonical).
- Strategy: regex the segment before ", WA"/" WA " (e.g. "… Kirkland, WA 98033") and validate
  against whitelist; fallback: scan whitelist for word-boundary membership anywhere in string,
  preferring the LAST match (city sits near the end of US addresses). Return canonical Title Case.
- Pure function, no I/O. Unit tests: full addresses, city-only strings ("Kirkland"), garbage, None,
  multi-city strings ("Kirkland Ave, Renton, WA" → Renton).

### backend/services/school_service.py
- `get_or_create_school(db, display_name) -> School` (normalize name = lower/single-space).
- `apply_school_address(db, school_id, address, city, district)` — also back-fills
  pickup/dropoff city+address onto season_rides at that school where NULL:
  IB rides: dropoff = school side. OB rides: pickup = school side.
- `schools_overview(db)` — list w/ ride_count + needs_address flag.

### backend/services/season_pool.py
- `upsert_from_intake(db, intake: RideIntake) -> list[SeasonRide]` — map parsed JSON
  (school/direction/number/is_odt/wheelchair/days/start_time/miles/net_pay/origin/destination/
  requirements text) → season_ride row(s); dedupe on the unique key (update, don't dup).
  Requirements text → flags via keyword match (car seat, booster, harness/vest/safety belt,
  monitor/attendant/aide, wheelchair/wc/hcv). Also `route_identity` markers: HCV → wheelchair.
- `import_sheet(db, file_bytes, filename) -> ImportReport` — xlsx/csv via pandas. Column mapping
  tolerant/fuzzy (case-insensitive contains): school, direction, route/number, days, pickup
  address, dropoff address, pickup time, dropoff time, miles, pay, requirements/needs, district.
  Unknown columns ignored; per-row errors collected, never abort the batch. Creates schools.
- `backfill_from_intakes(db, season)` — one-shot: all `taken` intakes → pool.

### backend/services/loop_builder.py  (WRITTEN BY FABLE INLINE — do not touch)
Pure engine, injected drive-time fn. See module docstring for algorithm.

## API (new router `backend/routes/season_board.py`, prefix `/api/data/season` + schools/capabilities; register in app.py like other routers; same auth deps as dispatch routes)

- `GET  /api/data/season/board?season&district&day_part&weekday`
  → `{stats:{total,assigned,unassigned,needs_info}, corridors:[{pickup_city,dropoff_city,rides:[RideOut]}], unplaced:[RideOut], districts:[str]}`
  Corridor sort: by pickup_city; opposite pairs adjacent (A→B immediately followed by B→A).
  `RideOut = {season_ride_id, school_display, direction, number, is_odt, days, pickup_city,
  dropoff_city, pickup_time, dropoff_time, requires, status, assigned_person:{person_id,name}|null,
  loop_id, needs:{address:bool, time:bool}}`
- `POST /api/data/season/import` — multipart file OR `{"from_intake": true}` → ImportReport JSON.
- `POST /api/data/season/loops/propose` `{season, day_part?, weekday?}` — runs builder, persists
  `proposed` loops (clears previous unconfirmed system proposals for that scope first).
- `GET  /api/data/season/loops?season` → loops w/ nested rides + slack + requirement profile.
- `POST /api/data/season/loops/{id}/assign` `{person_id}` — sets loop.person_id +
  status=confirmed + every ride in loop: assigned_person_id, status=assigned. Validates
  capabilities vs loop requirement profile → 409 with reason unless `{"override": true}`.
- `POST /api/data/season/loops/{id}/dismiss`
- `PATCH /api/data/season/rides/{id}` — partial: times/addresses/cities/requires/days/notes/
  loop_id/loop_position/assigned_person_id/status. City re-extracted when address changes.
- `POST /api/data/season/rides/{id}/unassign`
- `GET  /api/data/schools` / `PATCH /api/data/schools/{id}`
- `GET  /api/data/people/capabilities` / `PATCH /api/data/people/{id}/capabilities`

## Frontend (Next.js App Router, follow `(app)/dispatch/page.tsx` conventions: 'use client', api client, Tailwind + Radix + existing Badge/LoadingSpinner components, dark: variants)

1. `/season` — the workbench. Header: season stats progress bar ("42 of 87 assigned"), district
   tabs, AM/PM toggle, weekday chips (M T W R F), Import button (file upload + "pull from inbox"),
   "Propose loops" button. Body: corridor columns (city-pair headers, opposite pairs adjacent),
   ride cards (school, #, IB/OB, time, requirement icons, status color), loop panel (proposed
   loops w/ slack + driver picker w/ capability-filtered dropdown + assign/dismiss). Unplaced
   bucket ("needs address/time") at bottom. Optimistic refresh after actions, sonner toasts.
2. `/schools` — table: school, district, address (inline edit), city, ride count; rows needing
   address surfaced first. PATCH on save.
3. `/drivers/capabilities` — grid: driver rows × 5 capability toggle columns, saves per-row.
   Same pattern as the language page.
4. Nav: add "Season" link to the sidebar/nav where other (app) pages register.

## Wiring
- inbox_intake: after an intake flips to `taken` (and on auto-parse of recurring offers), call
  `season_pool.upsert_from_intake` behind env flag `SEASON_POOL_AUTOFILL` (default "1").
  Never raises into the intake flow (wrap, log).

## Tests (per-file isolation, inline fixtures, sqlite StaticPool pattern from test_assignment_service.py)
- test_city_extract.py — ≥12 cases.
- test_school_service.py — get_or_create normalize; address backfill IB/OB sidedness.
- test_season_pool.py — intake mapping, requirement keyword flags, dedupe upsert, sheet import
  happy path + junk rows + missing columns.
- test_loop_builder.py — written by Fable with the engine.
- test_season_board_api.py — board grouping/adjacent corridors, propose→assign flow,
  capability 409 + override, PATCH re-extract city, unassign.

## Ship gates (Law 6)
1. `./run_tests.sh` green (new files; pre-existing combined-run contamination is known, ignore).
2. `cd frontend && npm run build` — real prod build.
3. Backend: docker/uvicorn import check `python3 -c "import backend.app"` + alembic upgrade on a
   scratch sqlite/postgres to prove migration runs.
4. Fable diff review of every file before commit.
5. Commit main + tag `pre-s10` before push; Railway deploy + `npx vercel --prod --yes`; smoke
   prod endpoints.
