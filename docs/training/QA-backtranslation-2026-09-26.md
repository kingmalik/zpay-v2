# Driver Training Course — Blind Back-Translation QA (2026-09-26)

Independent QA of the Amharic (am) and Arabic (ar) driver certification course
translations (`backend/services/certification.py` am= strings,
`backend/services/course_content_ar.py` ar overlay), via blind
back-translation.

**Method:** Two isolated agents (no prior context, never shown the English
source) each extracted only their target locale's strings from
`course_content_public()` (297 keys: 13 module titles/intros/blocks + 18 quiz
questions/options), then produced a literal English back-translation from
that locale text alone. Only after both blind back-translations existed was
the English source pulled and compared, key by key, for meaning drift. The 8
highest-stakes terms were then checked against 2 independent external
sources per language.

---

## Amharic (am)

### Flagged items

| Key(s) | English source | Back-translation (am) | Issue | Severity | Suggested fix |
|---|---|---|---|---|---|
| `m2.b12.text`, `m3.b1.lead`, `m3.b1.text`, `q10.question` | "...pick up your **vest** and window sticker." / "Wear your **vest**..." / "Vest and placard." / "...wear your **vest**..." | "...you get your **coat** and your window sticker." / "Wear your **coat**..." / "**Coat** and mark." / "...wear your **coat**..." | `ኮት` is the standard Amharic word for a **coat/jacket** (outerwear), not a hi-vis/ID **vest**. A driver reading only the Amharic would be told to wear a coat instead of the required safety/ID vest — a real gear-compliance error, not a style choice. Confirmed against 2 external sources (see term table: `ኮት`=coat; commercial Amharic safety-vest listings consistently use `ቬስት`). | **CRITICAL** | Replace `ኮት`/`ኮትህን` with `ቬስት`/`ቬስትህን` (loanword, matches attested commercial Amharic usage for "safety vest"). **Applied.** |
| `m2.b12.text` vs `m3.b1.lead`/`m3.b1.text`/`q10.question` | "window sticker" / "placard" (same object) | `ስቲከር` ("sticker") in m2 vs `ማርክ` ("mark") in m3/quiz | Two different Amharic words used for the same physical placard across modules — term used inconsistently. Doesn't change the required action (driver still puts something in the window), so not action-changing. | Non-critical | Standardize on one term for the window placard (recommend `ስቲከር`, already used once, or a dedicated "placard/sign" word). Not applied. |
| `m7.b1.text` | "Being right on time is **cutting it close**." (timing-margin idiom) | "...arriving exactly on time is **dangerous** (`አደገኛ`)." | Idiom over-translated into a literal safety-hazard word. Doesn't reverse the instruction (still implies "arrive early, not exactly on time") and isn't quiz-tested, but could read as a fabricated safety claim rather than a punctuality-margin point. | Non-critical | Consider `ጊዜው የተጠጋጋ ነው` / a phrase conveying "cutting it close" without "dangerous." Not applied. |
| `m8.b3.text` | "Never **grab**." | "Never hold/grab" (`አትያዝ`) — ambiguous between "don't hold at all" and "don't grab forcefully" | Amharic verb is more ambiguous than the Arabic parallel (which explicitly says "forcefully"). Core prohibition (no physical restraint) still intact. | Non-critical | Consider `በሃይል አትያዝ` ("don't grab/hold by force") to match the Arabic pass's precision. Not applied. |

### Verdict
**AM: 4 flags (4 critical)** — all 4 critical flags are the same vest→coat mistranslation across 4 keys; fixed in this pass.

---

## Arabic (ar)

### Flagged items

| Key(s) | English source | Back-translation (ar) | Issue | Severity | Suggested fix |
|---|---|---|---|---|---|
| `m2.b1.text`, `m2.b8.text`, `m13.b0.text` | "background check" (generic) | "criminal record check" (`فحص السجل الجنائي`), used consistently all 3 times | Narrows a generic "background check" to specifically a criminal-record check. Consistent across all 3 occurrences (not an inconsistency), and doesn't change any driver action or quiz answer — purely informational content about the onboarding pipeline. | Non-critical | Consider a broader phrase (`التحقق من الخلفية` / "background verification") if precision matters, or leave as-is since it's consistent and industry-appropriate. Not applied. |

No other meaning drift, polarity flips, actor swaps, ambiguous quiz questions, or newly-plausible wrong options were found in the Arabic pass. Numbers, times, dollar amounts, pay-day examples (Sept 14→Oct 2, etc.), the no-load (student absent, full pay) vs. no-show (driver absent, no pay) actor distinction, the 911-vs-dispatch order, and the EverDriven-then-Maz call sequence all back-translated cleanly and match the English source.

### Verdict
**AR: 1 flag (0 critical)**

---

## Term verification (8 highest-stakes terms, 2 sources each)

| Term | Amharic rendering | Match? | Arabic rendering | Match? |
|---|---|---|---|---|
| student | `ተማሪ` (temari) | Yes — standard dictionary term (amharicteacher.com, abyssinica.com) | `طالب` (ṭālib) | Yes — standard dictionary term (almaany.com, Cambridge Arabic dict) |
| pickup | `መውሰጃ` ("taking place," compound from ወሰደ "to take") | Plausible but unattested in general dictionaries — a transparent domain coinage, not confirmed by outside sources. Flag for native review (non-critical). | `استلام` / `نقطة الاستلام` | Yes — attested as "pick-up point" in logistics usage (almaany.com, Reverso Context) |
| drop-off | `ማድረሻ` (from ደረሰ "to arrive," parallel construction to pickup term) | Consistent with attested `መድረሻ`/destination form (amharicpro.com, translate.com) | `تسليم` / `نقطة التسليم` | Yes — attested as "drop-off/delivery point" (Reverso Context, almaany.com) |
| wheelchair | — | **Not present** — wheelchair content was deliberately removed from the course in the 2026-09-10 Round 4 rewrite (all wheelchair rides are pre-assigned to approved drivers). Nothing to verify. | — | Same — not present |
| no-show | `አለመቅረብ` (title) / `ካልቀረበ` (block, "if [driver] doesn't appear") | Logically sound compound (negation + "to appear/come"), not a dictionary headword itself but transparent. Correctly distinct from the no-load ("student absent") term throughout. | `عدم الحضور` / `غياب السائق` | Yes — standard term for "no-show" in appointment/booking contexts (proz.com KudoZ, almaany.com) |
| dispatcher | `ዲስፓች` (transliteration/loanword) | General dictionaries translate "dispatch" as `መላክ`; the course instead uses the English loanword. Likely intelligible (drivers already use "dispatch" as a job-vocabulary term) but not confirmed by a dictionary source — flag for native-speaker sign-off (non-critical). | `قسم إرسال` ("sending department") | Yes — matches attested "dispatch department" phrasing (almaany.com, ProZ KudoZ) |
| parent/guardian | `ወላጅ` (welaj = "parent") | Yes — standard dictionary term for parent (abyssinica.com, preply.com) | `ولي الأمر` (wali al-amr) | Yes — the standard formal MSA term for parent/legal guardian in school/legal contexts (almaany.com, Wikipedia "Wali (Islamic legal guardian)") — matches the course's stated MSA register |
| incident | Course uses "**accident**," not "incident," throughout — `አደጋ` (adega) / `حادث` (ḥādith) | Yes — `አደጋ` = accident/hazard (amharicteacher.com, translate.com) | Yes — `حادث` = accident, also used for "incident" generically (almaany.com, WordHippo) |

---

## Summary

**AM: 4 flags (4 critical) / AR: 1 flag (0 critical)**

The 4 AM critical flags are one root cause — the vest→coat (`ኮት`) mistranslation across 4 keys (`m2.b12.text`, `m3.b1.lead`, `m3.b1.text`, `q10.question`) — and have been fixed directly in `backend/services/certification.py`, replacing `ኮት`/`ኮትህን` with `ቬስት`/`ቬስትህን`. All other flags (AM: placard-term inconsistency, one idiom over-translation, one minor verb ambiguity; AR: one narrowed-but-consistent "background check" term) are non-critical — informational or stylistic, none change a driver's required action or a quiz answer — and are listed only, not applied.

Test suite after the fix: `PYTHONPATH=. pytest backend/tests/test_certification_service.py backend/tests/test_certification_ar_translations.py -q` → **33 passed**.
