# Driver course — Arabic (ar) translation notes

Course: S7 driver certification (`backend/services/certification.py`,
`COURSE_VERSION = "2026-09"`), 13 modules + 18-question quiz. Arabic pass
done 2026-09-26, additively, as
`backend/services/course_content_ar.py` (see that file's docstring for the
overlay mechanism and why it doesn't touch `COURSE_MODULES`/`QUIZ_QUESTIONS`
directly — a parallel Amharic pass is editing those in place at the same
time).

Glossary and sourcing: `docs/training/glossary-ar.md` (18 domain terms, 2+
independent web sources each, plus a short list of adjacent terms used for
consistency that weren't in the original 18).

## What this pass did

- Translated all 13 module titles, the one module intro (m2), all 88
  content blocks (lead + text), and all 18 quiz questions + 72 options into
  Modern Standard Arabic, at a fifth-grade reading level, matching the
  English source sentence-for-sentence — no rules added, softened, or
  dropped.
- Kept company/app/form names in Latin script, wrapped in Unicode
  directional isolates (U+2066/U+2069) so they render correctly embedded in
  right-to-left paragraphs: Maz, Maz Services, FirstAlt, EverDriven,
  Acumen, Priority Solutions, Concentra, Contractor Compliance, Hallo,
  SafeRide, W-9, LLC, and the in-app button labels Start / End / At Pickup.
  "Z" (the person drivers ask pay questions) is also isolated since it's a
  single Latin letter used as a name.
- Left all numerals — clock times, dates, dollar amounts, "1099", "911",
  the dispatch phone number — as plain Western digits, matching the
  existing shipped 'ar' UI chrome in
  `frontend/app/(public)/training/[token]/page.tsx` (e.g. its
  `quizSubtitle.ar` already reads "...تحتاج إلى 15 إجابة صحيحة للنجاح").
- Did not touch quiz option order or `correct` indices — every question in
  the English source has `correct=0`, and the Arabic overlay preserves that
  by translating options in place without reordering.
- Did not touch the frontend page's own chrome translations (`T` object in
  `page.tsx`) — those already ship full 'ar' strings and were verified,
  not re-written.

## Reviewer guide

A native Arabic speaker (ideally someone familiar with school
transportation or ride-hailing operations, per the binder doc's own
translation-flow note for Amharic) should read
`backend/services/course_content_ar.py` end to end and confirm:

1. **Register** — every sentence should sound like plain, spoken-adjacent
   MSA a driver would actually read on a phone, not formal/literary Arabic.
   Flag anything that reads stiff or bureaucratic.
2. **Dialect neutrality** — the target audience is Sudanese, Somali-Arabic,
   Iraqi, and Syrian drivers. Flag any word that leans Gulf/Levant/Egyptian
   colloquial (the glossary in `glossary-ar.md` was chosen to avoid this,
   e.g. "تسجيل المركبة" over the informal "استمارة").
3. **The no-load / no-show distinction** — module 5, 6, 11 and quiz
   questions 4 and 10 hinge on the difference between "no-load" (student
   not present — driver still gets full pay) and a driver "no-show" (driver
   doesn't show up — zero pay + contract conversation). This pass renders
   no-load as "بدون راكب" / "رحلة بدون راكب" (a coined-but-clear phrase,
   since there is no single standard Arabic term for this app-specific
   status) and no-show as "غياب السائق". Confirm these read unambiguously
   as two different situations, not as synonyms.
4. **Bidi rendering** — open the `/training/{token}` page in a real browser
   with `person_language: "ar"` and confirm the isolated Latin tokens
   (FirstAlt, EverDriven, Start, End, At Pickup, phone number, etc.) don't
   visually reverse or collide with surrounding Arabic punctuation,
   especially the colon after "FirstAlt:" step labels and the parentheses
   in the phone number.
5. **Pay-delay math (module 10)** — the worked example ("تقود من الاثنين
   14 سبتمبر إلى الجمعة 18 سبتمبر. يصل ذلك المبلغ يوم الجمعة 2 أكتوبر")
   and quiz question 18 must stay numerically consistent with the English
   version if the binder doc's dates ever change — search for "14 سبتمبر"
   in `course_content_ar.py` if `docs/binder/05-driver-rules-certification.md`
   is updated.

## Five least-sure sentences (flag for reviewer priority)

1. **m7, lead "3. Straight there, straight home."** → "3. اذهب مباشرة، وعُد
   مباشرة." — literal ("go directly, and return directly"). Alternative:
   "٣. اذهب وعُد مباشرة دون توقف." (folds in "without stopping" up front).
   Kept the shorter form to match the terse English lead style.
2. **m5, lead "Why the exact spot matters."** → "لماذا يهم المكان بالضبط."
   Alternative: "أهمية الموقع الدقيق." (more noun-phrase, matches other
   leads' terseness slightly better). Kept the question-style form since
   it mirrors the English lead's rhythm more closely.
3. **m9, "Anything else." (lead)** → "أي شيء آخر." This is a very short,
   context-dependent lead (contrasts with "Someone is hurt or in danger.").
   Alternative: "في كل الحالات الأخرى." (more explicit "in all other
   cases"). Flagging since the terse literal version relies on the reader
   already having the 911-vs-dispatch contrast in mind from the previous
   block.
4. **Quiz Q3, "It's proof the ride happened — it's how you get paid."** →
   "إنه دليل على حدوث الرحلة — وهو ما يجعلك تحصل على أجرك." Alternative:
   "دليل يثبت أن الرحلة تمت، وهو أساس صرف أجرك." (slightly more formal
   "basis for your pay disbursement"). Kept the more literal/plainer
   version for fifth-grade-reading-level consistency with the rest of the
   quiz.
5. **m1, lead "Two people you talk to."** → "شخصان تتحدث معهما." Grammatically
   this uses the dual form ("معهما" = "with the two of them"), which is
   correct MSA but less commonly produced/recognized in everyday
   spoken-adjacent Arabic across all four target dialect backgrounds than
   the plural. Alternative: "الشخصان اللذان تتحدث معهما." (fuller relative
   clause) or simplifying to plural agreement throughout. Flagging the dual
   form specifically for a native-speaker read — it's correct but worth a
   fluency check with drivers from non-MSA-dominant backgrounds (e.g.
   Somali-Arabic speakers).

## Known non-issues (recorded so a reviewer doesn't re-flag them)

- Quiz question 9's option "911" and the m9 block referencing "911" are
  identical in English and Arabic by design — it's a numeral, not a word.
  The automated test suite (`backend/tests/test_certification_ar_translations.py`)
  explicitly allow-lists this so it doesn't get flagged as "untranslated."
- The frontend's welcome-screen language picker, quiz screen, and sign-off
  screen chrome (the `T` object in `page.tsx`) already shipped full Arabic
  strings before this pass and were left untouched, per the task's
  "do not reorder or rewrite" instruction for shared wiring.
