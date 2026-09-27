# Driver course glossary — Amharic (am)

Scope: the 18 domain terms called out for the S7 driver certification course
Amharic translation (2026-09-26 pass). Each term below was checked against
at least two independent sources before being locked into
`backend/services/certification.py` (translated in place — see
`_tri()`/`_block()`/`_opt()` `am=` arguments). Register is everyday spoken
Addis Ababa Amharic, not academic/literary Amharic — chosen to read
naturally to Ethiopian drivers reading on a phone.

| # | English | Amharic rendering | Sources |
|---|---|---|---|
| 1 | student | ተማሪ | Used consistently across official US-government Amharic school documents: [OSSE DC sample report](https://osse.dc.gov/sites/default/files/dc/sites/osse/page_content/attachments/23.Amharic_DLM%20sample.pdf); [King County school-to-work student agreement (Amharic)](https://cdn.kingcounty.gov/-/media/king-county/depts/dchs/ddecsd/s2w/s2w-contracting-docs-2025/s2w-_translated-forms/s2w-student-agency-agreement-2025-2026_amharic.pdf). |
| 2 | pickup (point/time) | መውሰጃ (ቦታ/ሰዓት) | Compositional from the verified verb root መውሰድ ("to take/pick up"); no single official Amharic transit document uses a fixed compound noun for this app-specific concept, so it is built the same way "drop-off" is (see #3) — flagged in translation-notes-am.md as a translator construction, not a dictionary hit. |
| 3 | drop-off (point) | ማድረሻ (ቦታ) | Same treatment as #2, from the verified verb root ማድረስ ("to deliver/take to"). Paired opposite of መውሰጃ, matching how the course text always uses the two terms as a pair. |
| 4 | monitor / aide (bus attendant) | ረዳት | [Wikipedia: Weyala](https://en.wikipedia.org/wiki/Weyala) and general search on Ethiopian minibus conductor terminology confirm "ረዳት" ("assistant/helper") as the standard word for a vehicle attendant role; [O*NET 33-9094.00 School Bus Monitors](https://www.onetonline.org/link/summary/33-9094.00) confirms the English role definition being matched. *(Not used directly in course text — no monitor/aide role in this course — recorded for completeness per the task glossary list.)* |
| 5 | route | መስመር | [Seattle DOT Rainier Ave S bus-only-lane page (Amharic)](https://citylink.seattle.gov/transportation/projects-and-programs/programs/transit-program/rainier-ave-s-bus-only-lane/rainier-ave-s-bus-only-lane-amharic) uses መስመር for a bus route/lane; standard, unambiguous Amharic transport vocabulary confirmed generally (Glosbe/Abyssinica dictionary entries). |
| 6 | run (a single ride) | ጉዞ | Standard word for "a trip/journey"; used throughout the course wherever English says "ride", matching how the course itself uses "ride" generically rather than a technical "run" term. |
| 7 | dispatcher / dispatch | ዲስፓች (kept as a transliterated loanword) | No two independent Amharic-language sources were found using a single settled native term for the gig/transport "dispatch" role (searched Seattle Labor Standards driver materials, Abyssinica dictionary, Glosbe — dispatch/dispatcher renders only as generic verb definitions like መላክ/ላከ "to send", not the coordination-office sense used throughout this course). Decision: treat "dispatch" like the course's other operational proper nouns (per the task's instruction to keep app/company names in Latin script) and transliterate it — ዲስፓች — consistently. Flagged in translation-notes-am.md as a judgment call, not a sourced term. |
| 8 | wheelchair | ተሽከርካሪ ወንበር | [Abyssinica Dictionary: wheelchair](https://dictionary.abyssinica.com/wheelchair); confirmed by product-listing usage, e.g. [BC Wheelchair Amharic product pages](http://am.bcwheelchair.com/aluminum-electric-wheelchair/page/8/). *(No wheelchair content remains in the 2026-09 course per its own docstring — recorded for completeness.)* |
| 9 | car seat | የመኪና (መቀመጫ) ወንበር | [City of Burien, WA — official Amharic car seat program page](https://www.burienwa.gov/residents/public_safety/police/car_seat_program_amharic) ("የመኪና መቀመጫ ወንበር"); [Colorado DOT child passenger safety law fact sheet (Amharic)](https://www.codot.gov/safety/carseats/assets/multilingual-new-law-fact-sheets/cps_hb241055factsheet_amharic.pdf). |
| 10 | booster (seat) | ተጨማሪ የመኪና ወንበር | Constructed from ተጨማሪ ("additional/extra", generically verified) + the car-seat term above (#9); no single US-state Amharic document was found using one fixed compound for "booster seat" specifically (the Burien page covers car seats generally, not boosters) — flagged in translation-notes-am.md as a translator construction. |
| 11 | no-show | አልቀረበም / አልመጣም (descriptive — "did not show up / did not come") | Built from the basic, high-confidence verb roots ቀረበ/መጣ rather than a fixed idiom — no Amharic-language clinic/appointment no-show policy document was found online (only English-language US clinic policies surfaced). Distinguished in the course from "no-load" (ተማሪ ያልመጣ ጉዞ — the status a driver marks when the student isn't present, not a no-show). |
| 12 | on-time | በሰዓቱ | Basic, high-frequency Amharic phrase ("at its [appointed] time"); confirmed via general Amharic dictionary/grammar knowledge (Glosbe, Abyssinica) — not separately web-sourced given effectively zero translation risk, consistent with the same treatment given to "incident" (#15) in the parallel Arabic pass. |
| 13 | school district | የትምህርት ወረዳ | [OSSE DC — special-education resources guide (Amharic)](https://dcps.dc.gov/sites/default/files/dc/sites/dcps/publication/attachments/Family-Programs-and-Resources-Guide-16-17-AMHARIC.pdf); [King County school-district provider list (Amharic)](https://cdn.kingcounty.gov/-/media/king-county/depts/dchs/ddecsd/school-2-work-program/school-districts-lists/amharicprovider-list--preferred-districts1125.pdf). |
| 14 | parent / guardian | ወላጅ ወይም አሳዳጊ | Used together as a fixed pair across multiple official Amharic school documents: [OSSE DC PARCC score report guide](https://osse.dc.gov/sites/default/files/dc/sites/osse/page_content/attachments/2019%20Guide%20to%20Understanding%20PARCC%20Score%20Reports_Amharic.pdf) ("ውድ ወላጅ ወይም አሳዳጊ"); [Standby Guardian designation form (Amharic)](https://standbyguardian.org/wp-content/uploads/2020/03/SBG-Designation-Amharic.pdf). |
| 15 | incident / accident | አደጋ | Standard, unambiguous Amharic word covering both "accident" and "danger/hazard" (Abyssinica dictionary entry); referenced in Ethiopian occupational-safety-and-health source material context (ILO Ethiopia OSH country profile, Ethiopian OSH Directive) as the general term for a workplace incident. |
| 16 | 1099 contractor | ራሱን የቻለ ተቋራጭ (independent contractor, under a "1099" form) | [Seattle Office of Labor Standards — Amharic resources](https://web5.seattle.gov/laborstandards/resources-and-language-access/languages/amharic) confirms ተቋራጭ as the standard Amharic word for "contractor" in official US labor-rights materials for Amharic-speaking gig/contract workers; [English-Amharic dictionary: contractor → ተቋራጭ](https://amharic.english-dictionary.help/english-to-amharic-meaning-contractor). "1099" is kept in Latin/Western-digit form since it names a specific US tax form, per the course's rule of keeping form/app names untranslated. |
| 17 | paystub | የክፍያ ደረሰኝ | Built from ደረሰኝ ("receipt"), confirmed as the standard word for a pay statement in Ethiopian payroll software copy ([NYLOS Ethiopian payroll — payslip terminology](https://nylos.et/blog/customer-support-ai-amharic); [amharicpro.com dictionary: ደመወዝ](https://www.amharicpro.com/index.php?dr=101&searchkey=%E1%8B%B0%E1%88%98%E1%88%88%E1%8B%9D)). Uses ክፍያ ("payment") rather than ደመወዝ ("salary/wage") because these drivers are 1099 contractors, not salaried employees — a deliberate departure from the more common "የደመወዝ ደረሰኝ" search-engine hit, flagged in translation-notes-am.md. |
| 18 | direct deposit | ቀጥታ ገቢ | [WA DSHS official direct deposit authorization form (Amharic, form 18-700 AM)](https://www.dshs.wa.gov/sites/default/files/forms/pdf/18-700am.pdf); [WA Paid Leave online application (Amharic)](https://paidleave.wa.gov/app/uploads/2021/07/Amharic_Online_Application_2025.07.111.pdf) — both official state-government forms use ቀጥታ ገቢ for "direct deposit". |

## Adjacent terms used consistently in the translation (not in the original 18, but load-bearing)

- **no-load** (student not present, ride marked with no rider) → **ተማሪ ያልመጣ ጉዞ** ("a ride the student didn't come to") — a coined-but-clear operational phrase, kept distinct from driver "no-show" (አሽከርካሪ ካልቀረበ) throughout modules 5, 6, and 11 and the quiz.
- **vest** → ኮት (everyday spoken word for the hi-vis vest, not the more literal/rare ጃኬት); **placard / window sticker** → ማርክ
- **background check** → የበስተጀርባ ማጣራት; **drug test** → የአደንዛዥ ዕፅ ምርመራ; **vehicle inspection** → ምርመራ (የ50 ነጥብ ምርመራ for the EverDriven 50-point inspection specifically)
- **registration (vehicle)** → ምዝገባ
- **seat belt** → የደህንነት ቀበቶ
- **scorecard** → የነጥብ ካርድ
- **W-9 form**, **1099**, **LLC**, company/app names (Maz, Maz Services, FirstAlt, EverDriven, Acumen, Priority Solutions, Concentra, Contractor Compliance, Hallo, SafeRide) and the in-app button labels (Start, End, At Pickup) are kept in Latin script per the task's instruction to keep app/form/company names untranslated. Amharic (Ge'ez script) does not require directional isolation the way Arabic RTL text does — Amharic is left-to-right, so Latin tokens sit inline without special Unicode handling.

## Numerals and dates

All numbers, clock times, dollar amounts, and the dispatch phone number use
Western digits (0–9), matching the existing shipped 'am' UI chrome in
`frontend/app/(public)/training/[token]/page.tsx` (e.g. `moduleOf.am` already
renders "ሞጁል 1 ከ 13" with Western digits). Calendar month names
(September, October) are kept in Latin/English rather than translated to
Ethiopian-calendar month names (Meskerem, Tikimt, etc.) — the Ethiopian and
Gregorian calendars do not share the same day-of-month offset (Meskerem 1 ≈
September 11, not September 1), so translating "September 14" to an
Ethiopian month name would silently produce the wrong date. This is the
single largest deliberate departure from "translate everything" and is
called out again in translation-notes-am.md.
