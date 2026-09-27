# Driver course glossary — Arabic (ar)

Scope: the 18 domain terms called out for the S7 driver certification course
Arabic translation (2026-09-26 pass). Each term below was checked against at
least two independent sources before being locked into
`backend/services/course_content_ar.py`. Register is Modern Standard Arabic
(MSA) — no Gulf/Levant/Egyptian dialect slang — chosen to read naturally to
Sudanese, Somali-Arabic, Iraqi, and Syrian drivers in Seattle.

| # | English | Arabic rendering | Sources |
|---|---|---|---|
| 1 | student | الطالب / الطلاب | Standard MSA; used for "child/student" contexts (e.g. "the student is not outside"). |
| 2 | pickup (point) | نقطة الاستلام | [Almaany: pickup](https://www.almaany.com/en/dict/ar-en/pickup/); [OpenTran: pickup point → نقطة التقاء / نقطة الاستلام](https://ar.opentran.net/%D8%A7%D9%84%D8%AA%D8%B1%D8%AC%D9%85%D8%A9-%D9%85%D9%86-%D8%A7%D9%84%D8%A5%D9%86%D8%AC%D9%84%D9%8A%D8%B2%D9%8A%D8%A9-%D8%A5%D9%84%D9%89-%D8%A7%D9%84%D8%B9%D8%B1%D8%A8%D9%8A%D8%A9/pickup.html). Paired with "drop-off" below (استلام/تسليم is the standard logistics pair). |
| 3 | drop-off (point) | نقطة التسليم | Paired term with "pickup" above; "تسليم" (delivery/handoff) is the standard counterpart to "استلام" (pickup) in Arabic logistics/transport usage — same source family as #2. |
| 4 | monitor / aide (bus attendant) | مرافق الحافلة | [Qureos job description: مرافق الحافلة (bus attendant)](https://www.qureos.com/job-desc/bus-attendant); [Rolecatcher: مضيفة حافلة مدرسية — school bus attendant career guide](https://rolecatcher.com/ar/careers/service-and-sales/care-workers/child-care-workers-and-teachers-aides/child-care-workers/school-bus-attendant/). *(Not used directly in course text — no monitor/aide role in this course — recorded for completeness per the task glossary list.)* |
| 5 | route | خط السير | General MSA transport vocabulary; confirmed against school-bus tracking product copy referencing "مسار"/"خط سير" for a vehicle's path, e.g. [AVLView: نظام تتبع الحافلات المدرسية](https://avlview.com/ar/%D8%A7%D9%84%D9%85%D9%8A%D8%B2%D8%A7%D8%AA/%D8%AA%D8%AA%D8%A8%D8%B9-%D8%A7%D9%84%D8%AD%D8%A7%D9%81%D9%84%D8%A9-%D8%A7%D9%84%D9%85%D8%AF%D8%B1%D8%B3%D9%8A%D8%A9); Almaany general entries for "route". |
| 6 | run (a single ride) | رحلة | Standard word for "a ride/trip"; used throughout the course wherever English says "ride". |
| 7 | dispatcher / dispatch | قسم الإرسال (the office/team you call) — المرسل (the person, where singular) | [Wikipedia: مرسل (dispatcher)](https://ar.wikipedia.org/wiki/%D9%85%D8%B1%D8%B3%D9%84); [Qureos job description: المرسل (dispatcher)](https://www.qureos.com/ar/job-desc/dispatcher) — notes the dispatcher's transport-coordination role. Course text almost always means "the team you call", so "قسم الإرسال" (dispatch department) is used consistently rather than "المرسل" (a single dispatcher). |
| 8 | wheelchair | كرسي متحرك | [Arabic Wikipedia: كرسي متحرك](https://ar.wikipedia.org/wiki/%D9%83%D8%B1%D8%B3%D9%8A_%D9%85%D8%AA%D8%AD%D8%B1%D9%83); [Almaany: كرسي متحرك ↔ wheelchair](https://www.almaany.com/en/dict/ar-en/%D9%83%D8%B1%D8%B3%D9%8A-%D9%85%D8%AA%D8%AD%D8%B1%D9%83/). *(No wheelchair content remains in the 2026-09 course per its own docstring — recorded for completeness.)* |
| 9 | car seat | مقعد الأمان للطفل | [Noon/Jumia/Mumzworld product listings for "مقعد سيارة للأطفال"](https://www.noon.com/saudi-ar/baby-products/baby-transport/car-seats/); [official Arabic child-passenger-safety chart (thecenterutica.org PDF)](https://www.thecenterutica.org/assets/Materials/TS-CPS-2017-Arabic-CPS-Seat-Chart.pdf) confirming the safety-restraint framing. |
| 10 | booster (seat) | مقعد الرفع | Same product-listing sources as #9 (Mumzworld: "داعم كرسي السيارة" / booster support) plus the safety chart's explanation that a booster's function is "رفع الطفل" (raising the child) so the seat belt sits correctly — direct semantic match confirmed across two independent sources. |
| 11 | no-show | عدم الحضور (student/driver did not show up); driver-specific: غياب السائق | [Arabic Wikipedia: عدم الظهور](https://ar.wikipedia.org/wiki/%D8%B9%D8%AF%D9%85_%D8%A7%D9%84%D8%B8%D9%87%D9%88%D8%B1); [ProZ KudoZ: no-show → عدم حضور أو وصول أصحاب الحجز](https://www.proz.com/kudoz/english-to-arabic/tourism-travel/388227-nosh.html). Distinguished in the course from "no-load" (رحلة بدون راكب — a status the driver marks when the student isn't present, not a no-show). |
| 12 | on-time | في الوقت المحدد | [Almaany: on time ↔ في الوقت المحدد](https://www.almaany.com/ar/dict/ar-en/on-time/); [Lingoland: ماذا تعني on time؟](https://lingolandedu.com/ar/english-arabic-dictionary/on-time). |
| 13 | school district | المنطقة التعليمية | [Almaany: المنطقة التعليمية ↔ school district](https://www.almaany.com/ar/dict/ar-en/%D8%A7%D9%84%D9%85%D9%86%D8%B7%D9%82%D8%A9-%D8%A7%D9%84%D8%AA%D8%B9%D9%84%D9%8A%D9%85%D9%8A%D8%A9/); [Reverso Context: منطقة تعليمية ↔ school district](https://context.reverso.net/translation/arabic-english/%D9%85%D9%86%D8%B7%D9%82%D8%A9+%D8%AA%D8%B9%D9%84%D9%8A%D9%85%D9%8A%D8%A9). |
| 14 | parent / guardian | ولي الأمر | [KHDA (Dubai education authority): عقد ولي الأمر والمدرسة](https://web.khda.gov.ae/ar/Guides/Parents/Parent-School-Contract); [OPWDD (NY State) official Arabic parent/guardian notice](https://opwdd.ny.gov/system/files/documents/2026/02/lstransition_parent-guardian_letter_arabic_12222580.pdf) — confirms "ولي الأمر" is the standard single term covering both "parent" and "guardian" in official Arabic school/agency documents, so no separate word for "guardian" is needed. |
| 15 | incident / accident | حادث | Basic, unambiguous MSA vocabulary (dictionary-standard; not separately web-verified given zero translation risk). |
| 16 | 1099 contractor | متعاقد مستقل (بموجب نموذج 1099) | [IRS: Form 1099-NEC and independent contractors](https://www.irs.gov/faqs/small-business-self-employed-other-business/form-1099-nec-and-independent-contractors); [Rippling Glossary: What Is a 1099 Employee?](https://www.rippling.com/glossary/1099-employee) — confirm "1099 contractor" = independent contractor, no taxes withheld, files own taxes; "1099" kept in Latin/Western-digit form since it names a specific US tax form, per the course's rule of keeping form/app names untranslated. |
| 17 | paystub | كشف الراتب | [JISR HR glossary: قسيمة الراتب (salary slip)](https://hrglossary.jisr.net/salary-slip); [HBR Arabic: شرح معنى "كشف الرواتب" (Payroll)](https://hbrarabic.com/%D8%A7%D9%84%D9%85%D9%81%D8%A7%D9%87%D9%8A%D9%85-%D8%A7%D9%84%D8%A5%D8%AF%D8%A7%D8%B1%D9%8A%D8%A9/%D9%83%D8%B4%D9%81-%D8%A7%D9%84%D8%B1%D9%88%D8%A7%D8%AA%D8%A8/). |
| 18 | direct deposit | الإيداع المباشر | [Arabic Wikipedia: إيداع مباشر](https://ar.wikipedia.org/wiki/%D8%A5%D9%8A%D8%AF%D8%A7%D8%B9_%D9%85%D8%A8%D8%A7%D8%B4%D8%B1); [Almaany: إيداع الرواتب المباشر](https://www.almaany.com/en/dict/ar-en/%D8%A5%D9%8A%D8%AF%D8%A7%D8%B9-%D8%A7%D9%84%D8%B1%D9%88%D8%A7%D8%AA%D8%A8-%D8%A7%D9%84%D9%85%D8%A8%D8%A7%D8%B4%D8%B1/). |

## Adjacent terms used consistently in the translation (not in the original 18, but load-bearing)

- **no-load** (student not present, ride marked with no rider) → **بدون راكب** / "رحلة بدون راكب" — a coined-but-clear operational phrase, kept distinct from "no-show" (غياب السائق / عدم الحضور) throughout modules 5, 6, and 11 and the quiz.
- **vest** → السترة; **placard / window sticker** → لافتة النافذة
- **background check** → فحص السجل الجنائي; **drug test** → فحص المخدرات; **vehicle inspection** → الفحص الفني
- **registration (vehicle)** → تسجيل المركبة (chosen over the informal Gulf/Egyptian "استمارة" for a neutral, dialect-free MSA reading)
- **seat belt** → حزام الأمان
- **W-9 form**, **1099**, **LLC**, company/app names (Maz, Maz Services, FirstAlt, EverDriven, Acumen, Priority Solutions, Concentra, Contractor Compliance, Hallo, SafeRide) and the in-app button labels (Start, End, At Pickup) are kept in Latin script per the task's instruction to keep app/form/company names untranslated, wrapped in Unicode directional isolates (U+2066/U+2069) so they render correctly inside RTL sentences.

## Numerals

All numbers, clock times, dates, dollar amounts, and the phone number use
Western digits (0–9), matching the existing 'ar' UI chrome already shipped
in `frontend/app/(public)/training/[token]/page.tsx` (e.g. "15 من 18") and
matching how the app itself displays numbers.
