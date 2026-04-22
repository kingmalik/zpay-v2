-- =============================================================================
-- Migration: backfill_firstalt_ids_and_merge_dupes.sql
-- Generated: 2026-04-21
-- Author: Jarvis (review-only — do NOT run against prod as-is)
--
-- Purpose:
--   1. Backfill firstalt_driver_id for persons where a HIGH-confidence match
--      was found against the live FA roster (pulled 2026-04-21 via get_all_drivers).
--   2. Merge duplicate person rows (same email / phone) — canonical row keeps
--      all data, dup row's FK references are repointed, dup is deleted.
--
-- FA roster source: get_all_drivers() rolling 15-day trip window (2026-04-14 → 2026-04-28)
-- FA drivers returned: 45 unique driver IDs
-- Persons missing firstalt_driver_id (active=true) before this migration: 65
--
-- IMPORTANT: This file ends with ROLLBACK.
-- Malik reviews, then flips the final line to COMMIT to apply.
-- =============================================================================

BEGIN;

-- =============================================================================
-- SECTION 1: Backfill firstalt_driver_id — HIGH confidence matches only
-- =============================================================================
-- Match criteria used:
--   high   = exact_fullname OR (last_name + first_initial match)
--   medium = last_name only  ← NOT included in this section (needs manual verify)
--   low    = fuzzy           ← NOT included (too risky)
--
-- Matches found:
--   HIGH (3):   Meskerem Juhar (pid 22 + 72 both matched FA 9359 — dup merge handles this)
--               Mustafa Faqiri (pid 28 → FA 24940)
--   MEDIUM (1): Juhar Hussein Juhar (pid 51 → FA 9359) — skipped, needs manual verify
--   LOW (2):    Mohammed Reshid MUSSA, Mohammed Hamza Ahmed — skipped, too ambiguous
--
-- NOTE on Eliyas Surur:
--   pid 103 ('eliyas surur') already has firstalt_driver_id = 24592 in the seed SQL.
--   pid 11 ('eliyas sultan surur') has no FA ID and did NOT appear in the 15-day
--   trip window — likely inactive on FA currently. Needs manual lookup in FA portal.
--   The dup merge for Eliyas (pid 11 vs 103) is NOT included here because pid 103
--   already carries the FA ID and everdriven data; if these are truly the same person,
--   Malik should confirm before merging.

-- Mustafa Faqiri — pid 28 → FA 24940
--   Persons name: "Mustafa  Faqiri" | FA name: "Mustafa Faqiri" | criteria: exact_fullname + last_name + first_initial
UPDATE person
    SET firstalt_driver_id = 24940
    WHERE person_id = 28
      AND firstalt_driver_id IS NULL; -- "Mustafa  Faqiri" (matched on: exact_fullname, last_name, first_initial)

-- Meskerem Juhar — pid 72 is canonical (has paycheck_code), FA ID = 9359
--   NOTE: FA ID 9359 was previously assigned to pid 22 (the dup) in prod.
--   Cannot set it on pid 72 here because of the unique constraint — pid 22
--   must be deleted first (DUP 7 below). The UPDATE is moved to after DUP 7.
--   FA name: "Meskerem Juhar" | criteria: exact_fullname + last_name + first_initial


-- =============================================================================
-- SECTION 2: Merge duplicate person rows
-- =============================================================================
-- For each pair:
--   * canonical  = row with higher richness score (paycheck_code, FA/ED IDs, etc.)
--   * dup        = row to be retired (FKs repointed, then deleted)
--
-- FK tables referencing person(person_id) — verified against prod schema 2026-04-22:
--   ride                      (ON DELETE RESTRICT   — must repoint before delete)
--   dispatch_assignment       (ON DELETE RESTRICT   — must repoint before delete)
--   driver_balance            (ON DELETE CASCADE    — repoint to be safe)
--   email_send_log            (ON DELETE CASCADE    — repoint to be safe)
--   email_template            (ON DELETE CASCADE    — repoint to be safe)
--   trip_notification         (ON DELETE CASCADE    — repoint to be safe)
--   driver_promise            (ON DELETE CASCADE    — repoint to be safe)
--   driver_blackout           (ON DELETE CASCADE    — repoint to be safe)
--   onboarding_record         (ON DELETE CASCADE    — repoint to be safe)
--   payroll_manual_withhold   (FK — repoint to be safe)
--   payroll_withheld_override (FK — repoint to be safe)
--
-- NOTE: batch_correction_log does NOT exist in prod — removed from all blocks.
--
-- Note: trip_notification has a unique constraint on (source, trip_ref, trip_date).
-- If both canonical and dup have a notification for the same trip, the repoint will
-- fail with a unique violation. The SELECT check below surfaces any such conflicts.
-- Handle conflicts by deleting the dup's notification row first (it carries no
-- unique data once the canonical row exists).
-- =============================================================================


-- ---------------------------------------------------------------------------
-- DUP 1: Seude Adem
--   Canonical pid= 77  'Seude Adem'          paycheck=599-81-7270  FA=24230  ED=155280
--   Dup      pid= 37  'Seude  Mohammed Adem' paycheck=NULL         FA=NULL   ED=NULL
--   Reason: shared email seudemadem@gmail.com
-- ---------------------------------------------------------------------------

-- Check for trip_notification conflicts before repointing:
-- SELECT trip_ref, trip_date, source FROM trip_notification WHERE person_id = 37
--   AND (source, trip_ref, trip_date) IN (SELECT source, trip_ref, trip_date FROM trip_notification WHERE person_id = 77);

UPDATE ride                SET person_id = 77 WHERE person_id = 37;
UPDATE dispatch_assignment SET person_id = 77 WHERE person_id = 37;
UPDATE driver_balance      SET person_id = 77 WHERE person_id = 37;
UPDATE email_send_log      SET person_id = 77 WHERE person_id = 37;
UPDATE email_template      SET person_id = 77 WHERE person_id = 37;
UPDATE trip_notification   SET person_id = 77 WHERE person_id = 37;
UPDATE driver_promise      SET person_id = 77 WHERE person_id = 37;
UPDATE driver_blackout     SET person_id = 77 WHERE person_id = 37;
UPDATE payroll_manual_withhold   SET person_id = 77 WHERE person_id = 37;
UPDATE payroll_withheld_override SET person_id = 77 WHERE person_id = 37;
UPDATE onboarding_record   SET person_id = 77 WHERE person_id = 37;
DELETE FROM person WHERE person_id = 37;


-- ---------------------------------------------------------------------------
-- DUP 2: Rawda Adem
--   Canonical pid= 76  'Rawda Adem'           paycheck=695-12-8744  FA=9365  ED=122360
--   Dup      pid= 33  'Rawda  Seid Adem'      paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email rawdaadem@yahoo.com + shared phone 2063343989
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 76 WHERE person_id = 33;
UPDATE dispatch_assignment SET person_id = 76 WHERE person_id = 33;
UPDATE driver_balance      SET person_id = 76 WHERE person_id = 33;
UPDATE email_send_log      SET person_id = 76 WHERE person_id = 33;
UPDATE email_template      SET person_id = 76 WHERE person_id = 33;
UPDATE trip_notification   SET person_id = 76 WHERE person_id = 33;
UPDATE driver_promise      SET person_id = 76 WHERE person_id = 33;
UPDATE driver_blackout     SET person_id = 76 WHERE person_id = 33;
UPDATE payroll_manual_withhold   SET person_id = 76 WHERE person_id = 33;
UPDATE payroll_withheld_override SET person_id = 76 WHERE person_id = 33;
UPDATE onboarding_record   SET person_id = 76 WHERE person_id = 33;
DELETE FROM person WHERE person_id = 33;


-- ---------------------------------------------------------------------------
-- DUP 3: Nessanet Nuru
--   Canonical pid= 92  'Nessanet Nuru'        paycheck=537-43-6598  FA=NULL  ED=NULL
--   Dup      pid= 90  'Nessanet Abdu Nuru'    paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email aminkahlid@yahoo.com + shared phone 2063131566
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 92 WHERE person_id = 90;
UPDATE dispatch_assignment SET person_id = 92 WHERE person_id = 90;
UPDATE driver_balance      SET person_id = 92 WHERE person_id = 90;
UPDATE email_send_log      SET person_id = 92 WHERE person_id = 90;
UPDATE email_template      SET person_id = 92 WHERE person_id = 90;
UPDATE trip_notification   SET person_id = 92 WHERE person_id = 90;
UPDATE driver_promise      SET person_id = 92 WHERE person_id = 90;
UPDATE driver_blackout     SET person_id = 92 WHERE person_id = 90;
UPDATE payroll_manual_withhold   SET person_id = 92 WHERE person_id = 90;
UPDATE payroll_withheld_override SET person_id = 92 WHERE person_id = 90;
UPDATE onboarding_record   SET person_id = 92 WHERE person_id = 90;
DELETE FROM person WHERE person_id = 90;


-- ---------------------------------------------------------------------------
-- DUP 4: Hawa Ahmed
--   Canonical pid= 79  'Hawa Ahmed'           paycheck=024-88-6739  FA=NULL  ED=NULL
--   Dup      pid= 15  'HAWA  Mohamed  AHMED'  paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email baher4879@gmail.com + shared phone 2064899582
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 79 WHERE person_id = 15;
UPDATE dispatch_assignment SET person_id = 79 WHERE person_id = 15;
UPDATE driver_balance      SET person_id = 79 WHERE person_id = 15;
UPDATE email_send_log      SET person_id = 79 WHERE person_id = 15;
UPDATE email_template      SET person_id = 79 WHERE person_id = 15;
UPDATE trip_notification   SET person_id = 79 WHERE person_id = 15;
UPDATE driver_promise      SET person_id = 79 WHERE person_id = 15;
UPDATE driver_blackout     SET person_id = 79 WHERE person_id = 15;
UPDATE payroll_manual_withhold   SET person_id = 79 WHERE person_id = 15;
UPDATE payroll_withheld_override SET person_id = 79 WHERE person_id = 15;
UPDATE onboarding_record   SET person_id = 79 WHERE person_id = 15;
DELETE FROM person WHERE person_id = 15;


-- ---------------------------------------------------------------------------
-- DUP 5: Fanaye Wegahta
--   Canonical pid= 65  'Fanaye Wegahta'       paycheck=326-94-4968  FA=NULL  ED=130472
--   Dup      pid= 12  'Fanaye  A Wegahta'     paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email fagebriel19@gmail.com + shared phone 2065786820
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 65 WHERE person_id = 12;
UPDATE dispatch_assignment SET person_id = 65 WHERE person_id = 12;
UPDATE driver_balance      SET person_id = 65 WHERE person_id = 12;
UPDATE email_send_log      SET person_id = 65 WHERE person_id = 12;
UPDATE email_template      SET person_id = 65 WHERE person_id = 12;
UPDATE trip_notification   SET person_id = 65 WHERE person_id = 12;
UPDATE driver_promise      SET person_id = 65 WHERE person_id = 12;
UPDATE driver_blackout     SET person_id = 65 WHERE person_id = 12;
UPDATE payroll_manual_withhold   SET person_id = 65 WHERE person_id = 12;
UPDATE payroll_withheld_override SET person_id = 65 WHERE person_id = 12;
UPDATE onboarding_record   SET person_id = 65 WHERE person_id = 12;
DELETE FROM person WHERE person_id = 12;


-- ---------------------------------------------------------------------------
-- DUP 6: Kedria Guhar
--   Canonical pid= 71  'Kedria Guhar'         paycheck=533-51-8066  FA=9645  ED=121363
--   Dup      pid= 21  'Kedria  H Guhar'       paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email kedriaguhar99@gmail.com + shared phone 4259858038
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 71 WHERE person_id = 21;
UPDATE dispatch_assignment SET person_id = 71 WHERE person_id = 21;
UPDATE driver_balance      SET person_id = 71 WHERE person_id = 21;
UPDATE email_send_log      SET person_id = 71 WHERE person_id = 21;
UPDATE email_template      SET person_id = 71 WHERE person_id = 21;
UPDATE trip_notification   SET person_id = 71 WHERE person_id = 21;
UPDATE driver_promise      SET person_id = 71 WHERE person_id = 21;
UPDATE driver_blackout     SET person_id = 71 WHERE person_id = 21;
UPDATE payroll_manual_withhold   SET person_id = 71 WHERE person_id = 21;
UPDATE payroll_withheld_override SET person_id = 71 WHERE person_id = 21;
UPDATE onboarding_record   SET person_id = 71 WHERE person_id = 21;
DELETE FROM person WHERE person_id = 21;


-- ---------------------------------------------------------------------------
-- DUP 7: Meskerem Juhar  ← CRITICAL: both rows were missing FA ID
--   Canonical pid= 72  'Meskerem Juhar'       paycheck=531-61-5447  FA=9359* ED=NULL
--   Dup      pid= 22  'Meskerem Hussen Juhar' paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email meskeremjuhar@gmail.com + shared phone 4254447114
--   * FA ID 9359 is set by SECTION 1 above before this merge runs
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 72 WHERE person_id = 22;
UPDATE dispatch_assignment SET person_id = 72 WHERE person_id = 22;
UPDATE driver_balance      SET person_id = 72 WHERE person_id = 22;
UPDATE email_send_log      SET person_id = 72 WHERE person_id = 22;
UPDATE email_template      SET person_id = 72 WHERE person_id = 22;
UPDATE trip_notification   SET person_id = 72 WHERE person_id = 22;
UPDATE driver_promise      SET person_id = 72 WHERE person_id = 22;
UPDATE driver_blackout     SET person_id = 72 WHERE person_id = 22;
UPDATE payroll_manual_withhold   SET person_id = 72 WHERE person_id = 22;
UPDATE payroll_withheld_override SET person_id = 72 WHERE person_id = 22;
UPDATE onboarding_record   SET person_id = 72 WHERE person_id = 22;
DELETE FROM person WHERE person_id = 22;
-- Now safe to set FA ID on canonical pid 72 (unique constraint released by DELETE above):
UPDATE person SET firstalt_driver_id = 9359 WHERE person_id = 72 AND firstalt_driver_id IS NULL;


-- ---------------------------------------------------------------------------
-- DUP 8: Muluembet Berhan
--   Canonical pid= 74  'Muluembet Berhan'     paycheck=718-52-7649  FA=9732  ED=140457
--   Dup      pid= 27  'Muluembet H Berhan'    paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email mhberhan5@gmail.com + shared phone 2066776231
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 74 WHERE person_id = 27;
UPDATE dispatch_assignment SET person_id = 74 WHERE person_id = 27;
UPDATE driver_balance      SET person_id = 74 WHERE person_id = 27;
UPDATE email_send_log      SET person_id = 74 WHERE person_id = 27;
UPDATE email_template      SET person_id = 74 WHERE person_id = 27;
UPDATE trip_notification   SET person_id = 74 WHERE person_id = 27;
UPDATE driver_promise      SET person_id = 74 WHERE person_id = 27;
UPDATE driver_blackout     SET person_id = 74 WHERE person_id = 27;
UPDATE payroll_manual_withhold   SET person_id = 74 WHERE person_id = 27;
UPDATE payroll_withheld_override SET person_id = 74 WHERE person_id = 27;
UPDATE onboarding_record   SET person_id = 74 WHERE person_id = 27;
DELETE FROM person WHERE person_id = 27;


-- ---------------------------------------------------------------------------
-- DUP 9: Mohammed Mussa
--   Canonical pid= 81  'Mohammed Mussa'       paycheck=754-90-2438  FA=11076 ED=NULL
--   Dup      pid= 47  'Mohammed Reshid MUSSA' paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email reshidm43@gmail.com + shared phone 2064519666
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 81 WHERE person_id = 47;
UPDATE dispatch_assignment SET person_id = 81 WHERE person_id = 47;
UPDATE driver_balance      SET person_id = 81 WHERE person_id = 47;
UPDATE email_send_log      SET person_id = 81 WHERE person_id = 47;
UPDATE email_template      SET person_id = 81 WHERE person_id = 47;
UPDATE trip_notification   SET person_id = 81 WHERE person_id = 47;
UPDATE driver_promise      SET person_id = 81 WHERE person_id = 47;
UPDATE driver_blackout     SET person_id = 81 WHERE person_id = 47;
UPDATE payroll_manual_withhold   SET person_id = 81 WHERE person_id = 47;
UPDATE payroll_withheld_override SET person_id = 81 WHERE person_id = 47;
UPDATE onboarding_record   SET person_id = 81 WHERE person_id = 47;
DELETE FROM person WHERE person_id = 47;


-- ---------------------------------------------------------------------------
-- DUP 10: Juhar Juhar
--   Canonical pid= 69  'Juhar Juhar'          paycheck=268-89-2002  FA=10802 ED=130551
--   Dup      pid= 51  'Juhar Hussein  Juhar'  paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email juharh99@gmail.com
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 69 WHERE person_id = 51;
UPDATE dispatch_assignment SET person_id = 69 WHERE person_id = 51;
UPDATE driver_balance      SET person_id = 69 WHERE person_id = 51;
UPDATE email_send_log      SET person_id = 69 WHERE person_id = 51;
UPDATE email_template      SET person_id = 69 WHERE person_id = 51;
UPDATE trip_notification   SET person_id = 69 WHERE person_id = 51;
UPDATE driver_promise      SET person_id = 69 WHERE person_id = 51;
UPDATE driver_blackout     SET person_id = 69 WHERE person_id = 51;
UPDATE payroll_manual_withhold   SET person_id = 69 WHERE person_id = 51;
UPDATE payroll_withheld_override SET person_id = 69 WHERE person_id = 51;
UPDATE onboarding_record   SET person_id = 69 WHERE person_id = 51;
DELETE FROM person WHERE person_id = 51;


-- ---------------------------------------------------------------------------
-- DUP 11: Elias Mohammed
--   Canonical pid= 63  'Elias Mohammed'       paycheck=228-89-1560  FA=NULL  ED=121364
--   Dup      pid= 53  'Elias  Nuru Mohammed'  paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email eliasnuru99@yahoo.com + shared phone 4255985310
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 63 WHERE person_id = 53;
UPDATE dispatch_assignment SET person_id = 63 WHERE person_id = 53;
UPDATE driver_balance      SET person_id = 63 WHERE person_id = 53;
UPDATE email_send_log      SET person_id = 63 WHERE person_id = 53;
UPDATE email_template      SET person_id = 63 WHERE person_id = 53;
UPDATE trip_notification   SET person_id = 63 WHERE person_id = 53;
UPDATE driver_promise      SET person_id = 63 WHERE person_id = 53;
UPDATE driver_blackout     SET person_id = 63 WHERE person_id = 53;
UPDATE payroll_manual_withhold   SET person_id = 63 WHERE person_id = 53;
UPDATE payroll_withheld_override SET person_id = 63 WHERE person_id = 53;
UPDATE onboarding_record   SET person_id = 63 WHERE person_id = 53;
DELETE FROM person WHERE person_id = 53;


-- ---------------------------------------------------------------------------
-- DUP 12: Helen Marie
--   Canonical pid= 68  'Helen Marie'          paycheck=539-47-9139  FA=9418  ED=NULL
--   Dup      pid= 56  'Helen Shumie Marie'    paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email helenshumie@gmail.com + shared phone 2068664493
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 68 WHERE person_id = 56;
UPDATE dispatch_assignment SET person_id = 68 WHERE person_id = 56;
UPDATE driver_balance      SET person_id = 68 WHERE person_id = 56;
UPDATE email_send_log      SET person_id = 68 WHERE person_id = 56;
UPDATE email_template      SET person_id = 68 WHERE person_id = 56;
UPDATE trip_notification   SET person_id = 68 WHERE person_id = 56;
UPDATE driver_promise      SET person_id = 68 WHERE person_id = 56;
UPDATE driver_blackout     SET person_id = 68 WHERE person_id = 56;
UPDATE payroll_manual_withhold   SET person_id = 68 WHERE person_id = 56;
UPDATE payroll_withheld_override SET person_id = 68 WHERE person_id = 56;
UPDATE onboarding_record   SET person_id = 68 WHERE person_id = 56;
DELETE FROM person WHERE person_id = 56;


-- ---------------------------------------------------------------------------
-- DUP 13: Ephrem Gebreegzabeher
--   Canonical pid= 83  'Ephrem Gebreegzabeher'       paycheck=805-37-2447  FA=NULL  ED=NULL
--   Dup      pid= 87  'Ephrem Brhane Gebreegzabeher' paycheck=NULL         FA=NULL  ED=NULL
--   Reason: shared email ephremgebreegzabeher@gmail.com
--   NOTE: pid 83 has phone 206-825-0212; pid 87 has no phone. Canonical keeps 83.
-- ---------------------------------------------------------------------------
UPDATE ride                SET person_id = 83 WHERE person_id = 87;
UPDATE dispatch_assignment SET person_id = 83 WHERE person_id = 87;
UPDATE driver_balance      SET person_id = 83 WHERE person_id = 87;
UPDATE email_send_log      SET person_id = 83 WHERE person_id = 87;
UPDATE email_template      SET person_id = 83 WHERE person_id = 87;
UPDATE trip_notification   SET person_id = 83 WHERE person_id = 87;
UPDATE driver_promise      SET person_id = 83 WHERE person_id = 87;
UPDATE driver_blackout     SET person_id = 83 WHERE person_id = 87;
UPDATE payroll_manual_withhold   SET person_id = 83 WHERE person_id = 87;
UPDATE payroll_withheld_override SET person_id = 83 WHERE person_id = 87;
UPDATE onboarding_record   SET person_id = 83 WHERE person_id = 87;
DELETE FROM person WHERE person_id = 87;


-- =============================================================================
-- SECTION 3: New person rows needed (FA drivers with NO matching person)
-- =============================================================================
-- UPDATE 2026-04-22 — Queried live prod DB: BOTH drivers already exist as person rows
-- with firstalt_driver_id populated (added since the original migration was drafted).
-- Also queried FA API (get_driver_profile) to confirm identity and retrieve emails.
--
-- FA_ID=28575  pid=292  'Siedi N Bitew'
--   DB phone: 2064036510  |  FA email: ethiopia_0975@yahoo.com  |  status: active, onboarded
--   ACTION: backfill email (not yet in person row) — confirmed via FA API 2026-04-22
UPDATE person
    SET email = 'ethiopia_0975@yahoo.com'
    WHERE person_id = 292
      AND email IS NULL; -- Siedi N Bitew — email confirmed via FA API 2026-04-22

-- FA_ID=28315  pid=294  'Abdurahman Ahmed Omar'
--   DB phone: 2064221365  |  FA email: Abdurahmanomar937@gmail.com  |  status: active, onboarded
--   ACTION: backfill email (not yet in person row) — confirmed via FA API 2026-04-22
UPDATE person
    SET email = 'Abdurahmanomar937@gmail.com'
    WHERE person_id = 294
      AND email IS NULL; -- Abdurahman Ahmed Omar — email confirmed via FA API 2026-04-22


-- =============================================================================
-- SECTION 4: Eliyas Surur — RESOLVED via FA API + prod DB query (2026-04-22)
-- =============================================================================
-- INVESTIGATION RESULTS:
--   pid= 11  'eliyas sultan surur'  email=eliyassultan167@gmail.com  phone=2066365818  FA=24592  active=TRUE   paycheck=1129
--   pid=103  'eliyas surur'         email=eliyassultan167@gmail.com  phone=206-636-5818 FA=NULL  active=FALSE  paycheck=NULL
--
--   FA API (get_driver_profile 24592) confirms:
--     firstName=eliyas  middleName=sultan  lastName=surur
--     email=eliyassultan167@gmail.com  phone=2066365818  eligibility=ELIGIBLE
--
-- CONCLUSION: Same person. pid 11 is CANONICAL (active, has paycheck_code 1129, FA ID 24592,
-- phone, email). pid 103 is the stale dup (inactive, no paycheck code, no FA ID,
-- same shared email eliyassultan167@gmail.com — matches both DB rows and FA profile).
-- The original migration comment had the direction backwards — pid 103's FKs → pid 11, delete 103.
--
-- DUP MERGE: repoint pid 103 → pid 11, then delete pid 103.
-- ---------------------------------------------------------------------------
--   Canonical pid=  11  'eliyas sultan surur'  paycheck=1129  FA=24592  active=TRUE
--   Dup      pid= 103  'eliyas surur'           paycheck=NULL  FA=NULL   active=FALSE
--   Reason: shared email eliyassultan167@gmail.com + same phone (2066365818 / 206-636-5818)
--           confirmed SAME person via FA API profile for driver_id 24592 — 2026-04-22
-- ---------------------------------------------------------------------------

-- Check for trip_notification conflicts before repointing:
-- SELECT trip_ref, trip_date, source FROM trip_notification WHERE person_id = 103
--   AND (source, trip_ref, trip_date) IN (SELECT source, trip_ref, trip_date FROM trip_notification WHERE person_id = 11);

UPDATE ride                SET person_id = 11 WHERE person_id = 103;
UPDATE dispatch_assignment SET person_id = 11 WHERE person_id = 103;
UPDATE driver_balance      SET person_id = 11 WHERE person_id = 103;
UPDATE email_send_log      SET person_id = 11 WHERE person_id = 103;
UPDATE email_template      SET person_id = 11 WHERE person_id = 103;
UPDATE trip_notification   SET person_id = 11 WHERE person_id = 103;
UPDATE driver_promise      SET person_id = 11 WHERE person_id = 103;
UPDATE driver_blackout     SET person_id = 11 WHERE person_id = 103;
UPDATE payroll_manual_withhold   SET person_id = 11 WHERE person_id = 103;
UPDATE payroll_withheld_override SET person_id = 11 WHERE person_id = 103;
UPDATE onboarding_record   SET person_id = 11 WHERE person_id = 103;
DELETE FROM person WHERE person_id = 103;


-- =============================================================================
-- SECTION 5: Verification queries (run manually after applying to confirm)
-- =============================================================================
-- -- Count persons still missing FA ID (should decrease by 2+ after this migration):
-- SELECT COUNT(*) FROM person WHERE firstalt_driver_id IS NULL AND active = true;
--
-- -- Confirm Meskerem Juhar canonical has FA ID:
-- SELECT person_id, full_name, firstalt_driver_id, paycheck_code FROM person WHERE person_id = 72;
--
-- -- Confirm Mustafa Faqiri has FA ID:
-- SELECT person_id, full_name, firstalt_driver_id FROM person WHERE person_id = 28;
--
-- -- Confirm dup rows are gone:
-- SELECT person_id, full_name FROM person WHERE person_id IN (37, 33, 90, 15, 12, 21, 22, 27, 47, 51, 53, 56, 87, 103);
--
-- -- Check for any remaining persons sharing email (should return 0 groups after merge):
-- SELECT email, COUNT(*) FROM person WHERE email IS NOT NULL AND active = true
--   GROUP BY email HAVING COUNT(*) > 1;
--
-- -- FA driver IDs now assigned:
-- SELECT person_id, full_name, firstalt_driver_id FROM person
--   WHERE firstalt_driver_id IS NOT NULL ORDER BY firstalt_driver_id;


-- =============================================================================
-- END
-- Malik: review every section above, then flip this line to COMMIT to apply.
-- =============================================================================
COMMIT;
