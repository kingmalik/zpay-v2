# Migration Report: backfill_firstalt_ids_and_merge_dupes
**Generated:** 2026-04-21  
**Status:** REVIEW-ONLY — migration ends with `ROLLBACK`

---

## Source Data

| Source | Detail |
|--------|--------|
| FA API | `get_all_drivers()` — 15-day rolling trip window (2026-04-14 → 2026-04-28) |
| Credentials | Pulled live from Railway prod env via GraphQL API |
| FA drivers returned | **45 unique driver IDs** |
| Persons in DB (seed) | **111 total** |

---

## Step 1: Persons Missing `firstalt_driver_id`

| Status | Count |
|--------|-------|
| Active persons with `firstalt_driver_id IS NULL` **before** this migration | **65** |
| Already have FA ID | 46 |

---

## Step 2: Match Results

| Confidence | Count | Action |
|------------|-------|--------|
| HIGH | **3 matches** (2 unique FA IDs) | Included in migration SQL |
| MEDIUM | 1 match | Skipped — needs manual verify |
| LOW | 2 matches | Skipped — too ambiguous |
| Unmatched (no FA driver found) | **59 persons** | Remain at FA NULL |

### HIGH-confidence matches included in SQL:
| Person ID | Person Name | FA Driver ID | FA Name | Match Criteria |
|-----------|-------------|-------------|---------|---------------|
| pid=28 | Mustafa Faqiri | 24940 | Mustafa Faqiri | exact_fullname + last_name + first_initial |
| pid=72 | Meskerem Juhar | 9359 | Meskerem Juhar | exact_fullname + last_name + first_initial |
| pid=22 | Meskerem Hussen Juhar | 9359 | Meskerem Juhar | last_name + first_initial (dup of pid=72 — merged) |

### MEDIUM match NOT included (needs manual verify):
- **pid=51** 'Juhar Hussein Juhar' → FA 9359 'Meskerem Juhar' — last name only, different first name

### LOW matches NOT included:
- **pid=47** 'Mohammed Reshid MUSSA' → FA 28388 'Mohammedtahir Hussen' — partial first name only
- **pid=26** 'Mohammed Hamza Ahmed' → FA 28388 'Mohammedtahir Hussen' — partial first name only

---

## Step 3: Duplicate Person Pairs Detected

**13 duplicate pairs** identified by shared email or phone. All 13 are included in the migration SQL.

| Canonical PID | Canonical Name | Dup PID | Dup Name | Match Basis |
|-------------|----------------|---------|----------|-------------|
| 77 | Seude Adem | 37 | Seude Mohammed Adem | email |
| 76 | Rawda Adem | 33 | Rawda Seid Adem | email + phone |
| 92 | Nessanet Nuru | 90 | Nessanet Abdu Nuru | email + phone |
| 79 | Hawa Ahmed | 15 | HAWA Mohamed AHMED | email + phone |
| 65 | Fanaye Wegahta | 12 | Fanaye A Wegahta | email + phone |
| 71 | Kedria Guhar | 21 | Kedria H Guhar | email + phone |
| 72 | Meskerem Juhar | 22 | Meskerem Hussen Juhar | email + phone |
| 74 | Muluembet Berhan | 27 | Muluembet H Berhan | email + phone |
| 81 | Mohammed Mussa | 47 | Mohammed Reshid MUSSA | email + phone |
| 69 | Juhar Juhar | 51 | Juhar Hussein Juhar | email |
| 63 | Elias Mohammed | 53 | Elias Nuru Mohammed | email + phone |
| 68 | Helen Marie | 56 | Helen Shumie Marie | email + phone |
| 83 | Ephrem Gebreegzabeher | 87 | Ephrem Brhane Gebreegzabeher | email |

After merging all 13 pairs: **13 person rows deleted**, persons table goes from 111 → 98.

---

## Step 4: FA Drivers With No Matching Person Row

**2 FA drivers** appear in the live trip roster but have no person row at all. They are currently invisible to `trip_monitor`. Commented-out INSERT statements are in the SQL file.

| FA Driver ID | FA Name | Action Needed |
|-------------|---------|---------------|
| 28575 | Siedi Bitew | Create new person row |
| 28315 | Abdurahman Omar | Create new person row |

---

## Top 3 Open Questions / Manual Lookups

### 1. Eliyas Surur — two rows, cannot confirm merge without FA portal check
- **pid=11** `eliyas sultan surur` (email: `eliyassultan167@gmail.com`, no phone, no FA ID)
- **pid=103** `eliyas surur` (no email, no phone, FA ID=24592, ED ID=24592)
- No shared email or phone to confirm identity. pid=11 did NOT appear in the 15-day trip window (may be inactive or a different person named Eliyas).
- **Action:** Look up FA driver ID 24592 in the FA portal and compare photo/contact against pid=11's email. If confirmed same person, run the commented-out merge block in Section 4 of the SQL.

### 2. 59 persons still unmatched after HIGH-confidence pass
The FA trip roster only covers a 15-day window — drivers who haven't had trips in that window won't appear. Many of the 59 unmatched persons are likely:
- ED-only drivers (have `everdriven_driver_id` but no `firstalt_driver_id` — correct)
- Former FA drivers who no longer receive rides
- Persons who are actually only on EverDriven
- **Action:** Cross-reference the 59 against the EverDriven roster. Anyone with `everdriven_driver_id` already set and no FA activity is probably correctly NULL on FA. The ones with neither ID and no ED ID are the real data gaps.

### 3. 2 new FA drivers need person rows (`Siedi Bitew`, `Abdurahman Omar`)
These are actively receiving trips in the FA system right now and have no person row, so `trip_monitor` is silently skipping their late-start alerts.
- **Action:** Uncomment the INSERT statements in Section 3 of the SQL, or create via the Z-Pay People UI. Add phone numbers from the FA portal so they can receive SMS alerts.

---

## Post-Migration Expected State

| Metric | Before | After (if COMMIT) |
|--------|--------|-------------------|
| Total person rows | 111 | ~98 (13 dups deleted) |
| Persons with FA ID | 46 | 48 (+2 new backfills) |
| Persons still missing FA ID (active) | 65 | ~52 (dup merges + backfills) |
| Duplicate pairs by email/phone | 13 | 0 |
| FA drivers with no person row | 2 | 0 (if INSERTs uncommented) |

---

## Surprises Found

1. **Mustafa Faqiri** had a different `firstalt_driver_id` (24940 from live FA) vs `person_id=28` which previously had NULL. The seed SQL already has a different person `person_id=54` with the name `Safiullah Faqiri` (FA=26268) — both are valid separate people.

2. **pid=51 Juhar Hussein Juhar** was matched by the name matcher to FA ID 9359 (Meskerem Juhar) because they share the last name "Juhar" — but this is clearly wrong (different first name). It's flagged as MEDIUM and excluded from the SQL. The canonical "Juhar" is pid=69 (Juhar Juhar) with FA=10802.

3. **Persons table has 4 rows (pid 7, 8, 100, 108) where the phone field contains an email address** (pid=7: `phone = alarusi.ahmed@gmail.com`). These won't break the merge but should be cleaned up in a separate pass.
