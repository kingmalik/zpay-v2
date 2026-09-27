# Driver course — Amharic (am) translation notes

Course: S7 driver certification (`backend/services/certification.py`,
`COURSE_VERSION = "2026-09"`), 13 modules + 18-question quiz. Amharic pass
done 2026-09-26, in place, by supplying `am=`/`lead_am=` arguments to every
`_tri()`/`_block()`/`_opt()` call inside `COURSE_MODULES` and
`QUIZ_QUESTIONS` (see that file's updated helper docstrings). This is
different from the Arabic pass done the same day, which used a separate
additive overlay file (`backend/services/course_content_ar.py`) specifically
so the two passes could run concurrently without touching the same lines —
this Amharic pass is the one editing `COURSE_MODULES`/`QUIZ_QUESTIONS`
directly, exactly as that Arabic pass's own notes anticipated.

Glossary and sourcing: `docs/training/glossary-am.md` (18 domain terms, 2+
independent web sources each where a settled term exists, plus a short list
of adjacent terms used for consistency and two explicitly flagged
judgment-call terms — "dispatch" and "booster seat" — where no clean sourced
Amharic equivalent could be found).

## What this pass did

- Translated all 13 module titles, the one module intro (m2), all 88
  content blocks (lead + text), and all 18 quiz questions + 72 options into
  everyday spoken Amharic, at a fifth-grade reading level, matching the
  English source sentence-for-sentence — no rules added, softened, or
  dropped. Verified by a full automated parity check
  (`test_amharic_translation_pass_is_complete_no_leftover_english_mirrors`):
  279 of 279 translatable strings differ from their English source, the one
  exception being the numeral "911" (correctly identical in both languages).
- Kept company/app/form names in Latin script inline: Maz, Maz Services,
  FirstAlt, EverDriven, Acumen, Priority Solutions, Concentra, Contractor
  Compliance, Hallo, SafeRide, W-9, LLC, Z (the pay-questions contact), and
  the in-app button labels Start / End / At Pickup. Amharic is
  left-to-right, so — unlike the Arabic pass — no directional-isolate
  Unicode wrapping was needed for these tokens to render correctly.
- Left all numerals — clock times, dollar amounts, "1099", the dispatch
  phone number — as plain Western digits, matching the existing shipped
  'am' UI chrome in `frontend/app/(public)/training/[token]/page.tsx` (its
  `moduleOf.am` already renders "ሞጁል 1 ከ 13").
- Kept calendar month names (September, October) in Latin/English rather
  than converting to Ethiopian-calendar month names — see
  glossary-am.md's "Numerals and dates" section for why a literal
  Meskerem/Tikimt conversion would silently shift the actual date by ~10
  days and change the pay-delay math taught in module 10 and quiz question
  18.
- Did not touch quiz option order or `correct` indices — every question in
  the English source has `correct=0`, and the Amharic translation preserves
  that by translating options in place without reordering (verified by
  `test_quiz_correct_answer_indices_identical_across_languages`).
- Did not touch the frontend page's own chrome translations (`T` object in
  `page.tsx`) — those already ship full 'am' strings (welcome screen, quiz
  screen, sign-off screen) and were spot-checked against this pass's
  vocabulary (e.g. "ሞጁል"/"module", "ፈተና"/"quiz") for consistency, not
  rewritten.
- Left the 'ar' key untouched (still mirrors 'en' inside
  `COURSE_MODULES`/`QUIZ_QUESTIONS` — actual Arabic strings come from the
  separate `course_content_ar.py` overlay applied in
  `course_content_public()`).

## Reviewer guide

A native Amharic speaker — Malik's family, per the task brief — should read
through the module and quiz text (e.g. via the `/training/{token}` page
with `person_language: "am"`, or by reading `backend/services/
certification.py`'s `am=` strings directly) and confirm:

1. **Register** — every sentence should sound like plain, spoken Addis
   Ababa Amharic a driver would actually read on a phone, not
   formal/literary or translated-sounding Amharic. Flag anything that reads
   stiff, over-formal, or like a direct word-for-word English calque.
2. **"ዲስፓች" (dispatch)** — this pass transliterates "dispatch" as a
   loanword throughout (see glossary-am.md item 7) because no sourced
   native Amharic term was found for the gig-economy coordination-office
   sense. Confirm this reads naturally to a driver, or suggest a better
   native alternative if one exists in real usage (e.g. a term used by
   Ethiopian rideshare/delivery drivers in Seattle specifically).
3. **The no-load / no-show distinction** — modules 5, 6, 11 and quiz
   questions 4 and 10 hinge on the difference between "no-load" (student
   not present — driver still gets full pay, rendered as "ተማሪ ያልመጣ ጉዞ")
   and a driver "no-show" (driver doesn't show up — zero pay + contract
   conversation, rendered as "አሽከርካሪ ካልቀረበ"). Confirm these read
   unambiguously as two different situations, not as synonyms.
4. **Booster seat ("ተጨማሪ የመኪና ወንበር")** — this is a translator
   construction (glossary item 10), not a term pulled from a single sourced
   document. Confirm it's clearly understood as "the smaller/extra seat
   that goes on top of the car seat", distinct from the car seat itself
   ("የመኪና ወንበር").
5. **Pay-delay math (module 10)** — the worked example ("ከሰኞ September 14
   እስከ አርብ September 18 ትነዳለህ እንበል። ያ ገንዘብ አርብ October 2 ይደርስሃል።") and
   quiz question 18 must stay numerically consistent with the English
   version if the binder doc's dates ever change — search for "September
   14" in `certification.py` if
   `docs/binder/05-driver-rules-certification.md` is updated.

## Five least-sure sentences (flag for reviewer priority)

1. **m1, block 7, "Call dispatch at {phone}." lead "Need dispatch?"** →
   "ዲስፓችን በ{phone} ደውል።" / "ዲስፓች ትፈልጋለህ?" — the entire "dispatch"
   terminology choice (transliteration vs. a native phrase like "ማዘዣ ማዕከል"
   / "የላኪ ቢሮ") is the single biggest judgment call in this pass. Flagging
   the whole ዲስፓች choice for a native-speaker gut check, not just this one
   sentence.
2. **m2, block 14, "You are your own business." → "የራስህ ንግድ ነህ።"** —
   literal ("you are your own business/trade"), matches the terse English
   lead style. Alternative: "የራስህ አለቃ ነህ።" ("you are your own boss") reads
   more natural in spoken Amharic but drifts slightly from "business" toward
   "boss". Kept the more literal rendering to stay closer to the English
   meaning.
3. **m10, block 3, "There is a delay." lead → "መዘግየት አለ።"** — short and
   literal. Alternative: "ክፍያው ይዘገያል።" ("the pay is delayed") is more
   explicit about what's delayed, since the bare lead alone doesn't name
   "pay". Kept the shorter form to match the terse English lead, since the
   following block text immediately clarifies it's about pay timing.
4. **Quiz Q3, "It's proof the ride happened — it's how you get paid."** →
   "ጉዞው መከናወኑን የሚያረጋግጥ ማስረጃ ነው — በዚህ መንገድ ትከፈላለህ።" Alternative: "ክፍያ
   ለማግኘት የሚያስፈልግ ማስረጃ ነው።" (more compact, "it's the proof needed to get
   paid"). Kept the two-clause version for closer sentence-for-sentence
   parity with the English (which also has two clauses joined by a dash).
5. **m8, block 3, "If a child has a hard moment." lead → "ልጁ ችግር
   ካጋጠመው።"** — literal ("if the child encounters a problem"), deliberately
   softer/vaguer to match the English lead's own vagueness ("a hard
   moment"). Alternative: "ልጁ ከተረበሸ።" ("if the child gets upset/agitated")
   is more specific to the crying/shouting behavior described in the block
   text. Flagging since Amharic tends to prefer more concrete verbs here
   than English's deliberately soft phrasing.

## Known non-issues (recorded so a reviewer doesn't re-flag them)

- Quiz question 9's option "911" is identical in English and Amharic by
  design — it's a numeral/emergency-number, not a word. The automated test
  suite (`backend/tests/test_certification_service.py`,
  `test_amharic_translation_pass_is_complete_no_leftover_english_mirrors`)
  explicitly allow-lists this so it doesn't get flagged as "untranslated."
- "September 14" / "September 18" / "October 2" / "September 25" appearing
  in Latin script inside otherwise-Amharic sentences (module 10, quiz
  question 18) is intentional — see "Pay-delay math" above and
  glossary-am.md's "Numerals and dates" section.
- The frontend's welcome-screen language picker, quiz screen, and sign-off
  screen chrome (the `T` object in `page.tsx`) already shipped full Amharic
  strings before this pass and were left untouched.
