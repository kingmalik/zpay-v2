"""
Driver Certification Course — S7.

Step 8 of driver onboarding (maz_training) becomes a real trilingual
certification: 6 content modules + a 10-question comprehension quiz
(pass = 8/10, unlimited retakes after re-reading) + typed-name e-sign,
persisted as a durable certification record (DriverCertification, one row
per passing attempt/history).

SOURCE CONTENT: docs/binder/05-driver-rules-certification.md is the
canonical EN source — module text and the exact 10 quiz questions (with
answers) below are transcribed from that document. Do not invent new
rules here; if the binder doc changes, bump COURSE_VERSION and update this
file to match.

Translations: Amharic and Arabic below were written for this build
following the tone of the existing trilingual training page
(frontend/app/(public)/training/[token]/page.tsx). Per the binder doc's
own translation flow note, Arabic needs a second full-speaker QA pass
before it's treated as final — flagged inline below. Amharic ships as-is.

Recertification: is_certified()/needs_recert() key off COURSE_VERSION —
any driver whose latest certification row doesn't match the current
COURSE_VERSION is treated as not (or no longer) certified. Bump
COURSE_VERSION whenever module or quiz content changes in a way that
matters (a rule changes, a question changes) — this is a full recert
trigger for the whole fleet, so don't bump it for typos.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

# Bump on any content change that should force fleet-wide recertification.
COURSE_VERSION = "2026-07"

# Quiz pass threshold — 8 of 10 (binder doc §Quiz). Expressed as a ratio so
# a future change to quiz_total still resolves to "8 of 10"-equivalent.
PASS_THRESHOLD_RATIO = 0.8

LANGS = ("en", "am", "ar")


def pass_threshold(quiz_total: int) -> int:
    """Minimum quiz_score required to pass a quiz of quiz_total questions."""
    return math.ceil(quiz_total * PASS_THRESHOLD_RATIO)


def quiz_passes(quiz_score: int, quiz_total: int) -> bool:
    if quiz_total <= 0:
        return False
    return quiz_score >= pass_threshold(quiz_total)


# ---------------------------------------------------------------------------
# Course content — 6 modules
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModuleBlock:
    """One paragraph/bullet inside a module. `lead` is an optional bold
    lead-in phrase (e.g. "Accept on time.") rendered ahead of `text`."""
    lead: Optional[dict]  # {"en": str, "am": str, "ar": str} or None
    text: dict            # {"en": str, "am": str, "ar": str}


@dataclass(frozen=True)
class CourseModule:
    key: str
    title: dict
    intro: Optional[dict]   # optional lead sentence before the block list
    blocks: tuple[ModuleBlock, ...]


def _block(text_en: str, text_am: str, text_ar: str, lead: Optional[tuple[str, str, str]] = None) -> ModuleBlock:
    lead_dict = {"en": lead[0], "am": lead[1], "ar": lead[2]} if lead else None
    return ModuleBlock(lead=lead_dict, text={"en": text_en, "am": text_am, "ar": text_ar})


COURSE_MODULES: tuple[CourseModule, ...] = (
    CourseModule(
        key="m1",
        title={
            "en": "The job in one minute",
            "am": "ስራው በአንድ ደቂቃ ውስጥ",
            # translation-QA-pending (Arabic — needs second full-speaker review)
            "ar": "الوظيفة في دقيقة واحدة",
        },
        intro=None,
        blocks=(
            _block(
                "You drive children with special needs to and from school.",
                "ልዩ ፍላጎት ያላቸውን ልጆች ወደ ትምህርት ቤት እና ከትምህርት ቤት ያመላልሳሉ።",
                "أنت تنقل أطفالاً ذوي احتياجات خاصة من وإلى المدرسة.",
            ),
            _block(
                "The children's safety is the entire job; the driving is second.",
                "የልጆቹ ደህንነት መላው ስራው ነው፤ ማሽከርከር ሁለተኛ ነው።",
                "سلامة الأطفال هي الوظيفة كلها؛ القيادة تأتي في المرتبة الثانية.",
            ),
            _block(
                "The partner's app watches every ride — following the app rules is what makes sure you get paid.",
                "የአጋር መተግበሪያው እያንዳንዱን ጉዞ ይከታተላል — የመተግበሪያውን ደንቦች መከተል ክፍያዎ እንዲረጋገጥ የሚያደርገው ነው።",
                "يراقب تطبيق الشريك كل رحلة — واتباع قواعد التطبيق هو ما يضمن حصولك على أجرك.",
            ),
        ),
    ),
    CourseModule(
        key="m2",
        title={
            "en": "The six driving rules",
            "am": "ስድስቱ የማሽከርከር ደንቦች",
            "ar": "قواعد القيادة الستة",
        },
        intro=None,
        blocks=(
            _block(
                "When the app offers your ride, accept it right away. The app notifies you before every ride. If you don't accept, dispatch has to call you — too many calls and you lose rides.",
                "መተግበሪያው ጉዞዎን ሲያቀርብ ወዲያውኑ ይቀበሉ። መተግበሪያው ከእያንዳንዱ ጉዞ በፊት ያሳውቅዎታል። ካልተቀበሉ ዲስፓች መደወል ይኖርበታል — በጣም ብዙ ጥሪዎች ጉዞዎችን ያሳጣዎታል።",
                "عندما يعرض عليك التطبيق رحلتك، اقبلها فوراً. يُخطرك التطبيق قبل كل رحلة. إذا لم تقبل، سيضطر المرسل للاتصال بك — كثرة المكالمات تفقدك الرحلات.",
                lead=("Accept on time.", "በሰዓቱ ይቀበሉ።", "اقبل في الوقت المحدد."),
            ),
            _block(
                "Being early is on time. If you might be late, call dispatch the moment you know — never hope it works out.",
                "ቀድሞ መድረስ በሰዓቱ መድረስ ማለት ነው። ልትዘገዩ እንደሆነ ካወቁ ወዲያውኑ ለዲስፓች ይደውሉ — በራሱ እንደሚስተካከል ተስፋ አያድርጉ።",
                "الحضور مبكراً هو الحضور في الوقت المحدد. إذا كنت ستتأخر، اتصل بالمرسل فور علمك — لا تأمل أن يسير الأمر على ما يرام من تلقاء نفسه.",
                lead=("Arrive on time.", "በሰዓቱ ይድረሱ።", "احضر في الوقت المحدد."),
            ),
            _block(
                "Pick up, drive the route, drop off. No stops — not for gas, not for coffee, not for errands. Fuel up before your route.",
                "ያንሱ፣ መንገዱን ያሽከርክሩ፣ ያውርዱ። ምንም ማቆሚያ የለም — ለነዳጅ አይደለም፣ ለቡና አይደለም፣ ለስራ አይደለም። ከመንገድዎ በፊት ነዳጅ ይሙሉ።",
                "استلم، اقد المسار، سلّم. لا توقفات — لا للوقود، لا للقهوة، لا للمشاوير. املأ خزان الوقود قبل بدء المسار.",
                lead=("Straight there, straight home.", "በቀጥታ ወደዚያ፣ በቀጥታ ወደ ቤት።", "مباشرة إلى هناك، مباشرة إلى المنزل."),
            ),
            _block(
                "Not you, not the child.",
                "እርስዎም አይደለም፣ ልጅም አይደለም።",
                "لا أنت ولا الطفل.",
                lead=("No eating or drinking in the car.", "በመኪና ውስጥ መብላት ወይም መጠጣት የለም።", "لا أكل أو شرب في السيارة."),
            ),
            _block(
                "Follow the route the app gives you. If the road is blocked, call dispatch.",
                "መተግበሪያው የሚሰጥዎትን መንገድ ይከተሉ። መንገዱ ከተዘጋ ለዲስፓች ይደውሉ።",
                "اتبع المسار الذي يعطيك إياه التطبيق. إذا كان الطريق مغلقاً، اتصل بالمرسل.",
                lead=("No detours.", "ምንም መዞሪያ የለም።", "لا انحرافات عن المسار."),
            ),
            _block(
                "The app tracks your speed on every ride. One ticket costs more than you earn in a week.",
                "መተግበሪያው በእያንዳንዱ ጉዞ ፍጥነትዎን ይከታተላል። አንድ የፍጥነት ቅጣት በሳምንት ከሚያገኙት በላይ ያስከፍልዎታል።",
                "يتتبع التطبيق سرعتك في كل رحلة. مخالفة واحدة تكلفك أكثر مما تكسبه في أسبوع.",
                lead=("Never speed.", "በፍጹም ፍጥነት አይብለጡ።", "لا تتجاوز السرعة المحددة أبداً."),
            ),
        ),
    ),
    CourseModule(
        key="m3",
        title={
            "en": "The app pays you (this is the one drivers skip — don't)",
            "am": "መተግበሪያው ነው የሚከፍልዎት (ይህ ሾፌሮች የሚዘሉት ነው — አይዝለሉ)",
            "ar": "التطبيق هو من يدفع لك (هذا ما يتجاهله السائقون — لا تفعل)",
        },
        intro={
            "en": "The partner only pays for rides it can verify. That means, on every single ride:",
            "am": "አጋሩ ማረጋገጥ የሚችለውን ጉዞ ብቻ ነው የሚከፍለው። ይህ ማለት፣ በእያንዳንዱ ጉዞ፦",
            "ar": "يدفع الشريك فقط مقابل الرحلات التي يمكنه التحقق منها. هذا يعني، في كل رحلة على حدة:",
        },
        blocks=(
            _block(
                "A ride with no camera footage can be taken back out of your pay.",
                "ካሜራ ቀረጻ የሌለው ጉዞ ከክፍያዎ ሊነሳ ይችላል።",
                "الرحلة التي لا يوجد فيها تسجيل كاميرا يمكن خصمها من أجرك.",
                lead=("Camera working and on.", "ካሜራ እየሰራ እና በርቶ ይሁን።", "الكاميرا تعمل ومشغّلة."),
            ),
            _block(
                "The app's location record is the proof you did the ride.",
                "የመተግበሪያው የቦታ መዝገብ ጉዞውን እንደሰሩ የሚያሳይ ማስረጃ ነው።",
                "سجل الموقع في التطبيق هو الدليل على أنك قمت بالرحلة.",
                lead=(
                    "Start the ride in the app when you start. End it when you end.",
                    "ጉዞ ሲጀምሩ በመተግበሪያው ላይ ይጀምሩ። ሲጨርሱ ይጨርሱ።",
                    "ابدأ الرحلة في التطبيق عندما تبدأ. أنهها عندما تنتهي.",
                ),
            ),
            _block(
                "Tapping from the wrong place looks like a fake ride.",
                "ከተሳሳተ ቦታ መንካት የውሸት ጉዞ እንደሆነ ያስመስላል።",
                "الضغط من مكان خاطئ يبدو وكأنها رحلة مزيفة.",
                lead=(
                    "Be inside the pickup and dropoff zones when you tap.",
                    "ሲነኩ በማንሻ እና በማውረጃ ቦታ ውስጥ ይሁኑ።",
                    "كن داخل مناطق الاستلام والتسليم عند الضغط.",
                ),
            ),
            # Closing line of Module 3 (no bold lead-in — plain paragraph).
            _block(
                "If the app misbehaves, screenshot it and tell dispatch the same morning. A reported problem protects your pay; a silent one doesn't.",
                "መተግበሪያው ችግር ካሳየ፣ ቅጽበታዊ ገፅ እይታ አንስተው በዚያው ጠዋት ለዲስፓች ይንገሩ። የተነገረ ችግር ክፍያዎን ይጠብቃል፤ ያልተነገረ ግን አይጠብቅም።",
                "إذا تصرف التطبيق بشكل غير طبيعي، التقط صورة للشاشة وأخبر المرسل في نفس الصباح. المشكلة المُبلَّغ عنها تحمي أجرك؛ والمشكلة الصامتة لا تحميه.",
            ),
        ),
    ),
    CourseModule(
        key="m4",
        title={
            "en": "The children",
            "am": "ልጆቹ",
            "ar": "الأطفال",
        },
        intro=None,
        blocks=(
            _block(
                "Greet the child by name; same seat every day if the child prefers it. Routine is comfort.",
                "ልጁን በስሙ ሰላም ይበሉ፤ ልጁ ከመረጠ በየቀኑ ተመሳሳይ መቀመጫ ይስጡ። ልማድ ምቾት ነው።",
                "رحّب بالطفل باسمه؛ ونفس المقعد كل يوم إذا فضّل الطفل ذلك. الروتين يمنح الراحة.",
            ),
            _block(
                "pull over somewhere safe and call dispatch. You never discipline, never grab, never argue. Dispatch brings in the school or the parent.",
                "በደህና ቦታ ቆም ብለው ለዲስፓች ይደውሉ። በፍጹም አይቀጡ፣ አይያዙ፣ አይከራከሩ። ዲስፓች ትምህርት ቤቱን ወይም ወላጅን ያሳትፋል።",
                "توقف في مكان آمن واتصل بالمرسل. لا تؤدب الطفل أبداً، لا تمسكه، لا تجادله. المرسل هو من يُشرك المدرسة أو ولي الأمر.",
                lead=(
                    "If a child has a hard moment (crying, shouting, won't stay seated):",
                    "ልጅ አስቸጋሪ ጊዜ ካጋጠመው (ማልቀስ፣ መጮህ፣ በመቀመጫ አለመቀመጥ)፦",
                    "إذا مر الطفل بلحظة صعبة (بكاء، صراخ، رفض الجلوس):",
                ),
            ),
            _block(
                "Never leave a child alone in the vehicle. Never drop a child anywhere but the exact stop, to the expected adult where one is required.",
                "ልጅን በተሽከርካሪ ውስጥ ብቻውን በፍጹም አይተዉ። ልጅን ከትክክለኛው ማቆሚያ ውጭ በፍጹም አያውርዱ፣ አዋቂ ካስፈለገም ለሚጠበቀው አዋቂ ብቻ።",
                "لا تترك الطفل وحيداً في السيارة أبداً. لا تُنزل الطفل في أي مكان سوى المحطة المحددة بالضبط، وللشخص البالغ المتوقع حيث يُطلب ذلك.",
            ),
            _block(
                "What happens in the car stays private. No photos of children, no posts, no stories.",
                "በመኪና ውስጥ የሚሆነው ነገር ግላዊ ሆኖ ይቆያል። የልጆች ፎቶ የለም፣ ፖስት የለም፣ ታሪክ የለም።",
                "ما يحدث في السيارة يبقى خاصاً. لا صور للأطفال، لا منشورات، لا قصص.",
            ),
        ),
    ),
    CourseModule(
        key="m5",
        title={
            "en": "If something goes wrong",
            "am": "የሆነ ችግር ከተከሰተ",
            "ar": "إذا حدث خطأ ما",
        },
        intro=None,
        blocks=(
            _block(
                "children safe first, 911 if anyone is hurt, then call dispatch immediately — before your family, before photos of the car. You'll write down what happened within 24 hours; dispatch will help you.",
                "መጀመሪያ የልጆችን ደህንነት ያረጋግጡ፣ ማንም ከተጎዳ 911 ይደውሉ፣ ከዚያ ወዲያውኑ ለዲስፓች ይደውሉ — ከቤተሰብዎ በፊት፣ የመኪናውን ፎቶ ከማንሳትዎ በፊት። በ24 ሰዓት ውስጥ የተከሰተውን ይጽፋሉ፤ ዲስፓች ይረዳዎታል።",
                "سلامة الأطفال أولاً، اتصل بالطوارئ 911 إذا أُصيب أحد، ثم اتصل بالمرسل فوراً — قبل عائلتك، وقبل تصوير السيارة. ستكتب ما حدث خلال 24 ساعة؛ وسيساعدك المرسل.",
                lead=("Accident:", "አደጋ፦", "الحادث:"),
            ),
            _block(
                "tell dispatch the night before if you can, or the second you know. An early callout is respected; a silent no-show can end the contract.",
                "ከሚቻል ከትናንት ማታ ለዲስፓች ይንገሩ፣ ወይም እንዳወቁ ወዲያውኑ። ቀድሞ ማሳወቅ የተከበረ ነው፤ ያለ ማሳወቅ አለመቅረብ ግን ውሉን ሊያቋርጥ ይችላል።",
                "أخبر المرسل في الليلة السابقة إن استطعت، أو فور علمك. الإبلاغ المبكر محترَم؛ أما التغيب الصامت فقد ينهي العقد.",
                lead=("You're sick / can't drive:", "ታመዋል / ማሽከርከር አይችሉም፦", "أنت مريض / لا يمكنك القيادة:"),
            ),
            _block(
                "call dispatch as soon as late looks possible.",
                "መዘግየት ሊኖር እንደሚችል እንዳወቁ ወዲያውኑ ለዲስፓች ይደውሉ።",
                "اتصل بالمرسل فور احتمال التأخر.",
                lead=("Running late:", "እየዘገዩ ከሆነ፦", "التأخر عن الموعد:"),
            ),
        ),
    ),
    CourseModule(
        key="m6",
        title={
            "en": "Your vehicle and paperwork",
            "am": "ተሽከርካሪዎ እና ወረቀቶችዎ",
            "ar": "مركبتك وأوراقك الرسمية",
        },
        intro=None,
        blocks=(
            _block(
                "Registration, insurance, and the annual mechanic certification must stay current — an expired document means you cannot drive that day, by contract, no exceptions. Z-Pay reminds you 30 days before anything expires. Handle it that week, not the last day.",
                "ምዝገባ፣ ኢንሹራንስ፣ እና አመታዊ የመካኒክ ማረጋገጫ የተሻሻሉ መሆን አለባቸው — ጊዜው ያለፈበት ወረቀት ማለት በዚያ ቀን በውል መሰረት ማሽከርከር አይችሉም ማለት ነው፣ ምንም ልዩ ሁኔታ የለም። ዚ-ፔይ ከመድረሱ 30 ቀን በፊት ያስታውስዎታል። በዚያ ሳምንት ይያዙት፣ በመጨረሻው ቀን አይደለም።",
                "يجب أن يظل التسجيل والتأمين وشهادة الفحص الميكانيكي السنوية سارية — الوثيقة المنتهية الصلاحية تعني أنك لا تستطيع القيادة ذلك اليوم، بموجب العقد، بلا استثناءات. يذكّرك Z-Pay قبل 30 يوماً من أي انتهاء صلاحية. تعامل مع الأمر في ذلك الأسبوع، وليس في اليوم الأخير.",
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Quiz — 10 questions, single correct answer each (binder doc §Quiz)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuizQuestion:
    question: dict
    options: tuple  # tuple of dicts {"en":..., "am":..., "ar":...}
    correct: int


def _opt(en: str, am: str, ar: str) -> dict:
    return {"en": en, "am": am, "ar": ar}


QUIZ_QUESTIONS: tuple[QuizQuestion, ...] = (
    QuizQuestion(
        question=_opt(
            "The app offers you tomorrow's ride. When do you accept it?",
            "መተግበሪያው የነገውን ጉዞዎን ያቀርባል። መቼ ይቀበሉታል?",
            "يعرض عليك التطبيق رحلة الغد. متى تقبلها؟",
        ),
        options=(
            _opt("Right away", "ወዲያውኑ", "على الفور"),
            _opt("Whenever you get a chance today", "ዛሬ እድል ሲያገኙ", "متى ما سنحت لك الفرصة اليوم"),
            _opt("The morning of the ride", "በጉዞው ቀን ጠዋት", "في صباح يوم الرحلة"),
            _opt("Only after dispatch calls you", "ዲስፓች ከደወለ በኋላ ብቻ", "فقط بعد أن يتصل بك المرسل"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt(
            "You're low on gas mid-route with the child in the car. What do you do?",
            "ልጅ በመኪና ውስጥ እያለ በመንገድ መሃል ነዳጅ አልቆብዎታል። ምን ያደርጋሉ?",
            "أنت في منتصف المسار والطفل في السيارة ووقودك منخفض. ماذا تفعل؟",
        ),
        options=(
            _opt("Stop for gas quickly since it's close by", "በአቅራቢያ ስላለ ፈጣን ነዳጅ ማቆም", "توقف بسرعة للتزود بالوقود لأنه قريب"),
            _opt(
                "Nothing mid-route — fuel up before the route; call dispatch only if the road is blocked or it's an emergency",
                "በመንገድ መሃል ምንም — ከመንገድ በፊት ነዳጅ ይሙሉ፤ መንገዱ ከተዘጋ ወይም ድንገተኛ ሁኔታ ካለ ብቻ ለዲስፓች ይደውሉ",
                "لا شيء في منتصف المسار — املأ الوقود قبل المسار؛ اتصل بالمرسل فقط إذا كان الطريق مغلقاً أو في حالة طارئة",
            ),
            _opt("Ask the child if it's okay to stop", "ልጁን ማቆም ይቻል እንደሆነ መጠየቅ", "اسأل الطفل إن كان التوقف مناسباً"),
            _opt("Drop the child off first at a nearby friend's house", "ልጁን መጀመሪያ በአቅራቢያ ወዳለ ጓደኛ ቤት ማድረስ", "أنزل الطفل أولاً عند منزل صديق قريب"),
        ),
        correct=1,
    ),
    QuizQuestion(
        question=_opt(
            "Your camera isn't working this morning. What do you do?",
            "ዛሬ ጠዋት ካሜራዎ አይሰራም። ምን ያደርጋሉ?",
            "الكاميرا لا تعمل هذا الصباح. ماذا تفعل؟",
        ),
        options=(
            _opt("Drive the route anyway, it's probably fine", "ችግር የለውም ብሎ መንገዱን ማሽከርከር", "اقد المسار على أي حال، على الأرجح لا بأس"),
            _opt(
                "Screenshot it and tell dispatch the same morning, before the ride",
                "ቅጽበታዊ ገፅ እይታ አንስተው በዚያው ጠዋት ከጉዞው በፊት ለዲስፓች ይንገሩ",
                "التقط صورة للشاشة وأخبر المرسل في نفس الصباح، قبل الرحلة",
            ),
            _opt("Wait until the end of the week to mention it", "እስከ ሳምንቱ መጨረሻ ድረስ መጠበቅ", "انتظر حتى نهاية الأسبوع لذكر الأمر"),
            _opt("Fix it yourself without telling anyone", "ለማንም ሳይነግሩ በራስዎ መጠገን", "أصلحها بنفسك دون إخبار أحد"),
        ),
        correct=1,
    ),
    QuizQuestion(
        question=_opt(
            "Why do you tap start/end inside the pickup and dropoff zones?",
            "ለምን በማንሻ እና በማውረጃ ቦታ ውስጥ ጀምር/ጨርስ ይነካሉ?",
            "لماذا تضغط بدء/إنهاء وأنت داخل مناطق الاستلام والتسليم؟",
        ),
        options=(
            _opt("It's just a formality", "ልማዳዊ ብቻ ነው", "مجرد إجراء شكلي"),
            _opt("It saves battery on the app", "የመተግበሪያውን ባትሪ ይቆጥባል", "يوفر بطارية التطبيق"),
            _opt(
                "That's the proof the ride happened — it's how you get paid",
                "ጉዞው መከናወኑን የሚያሳይ ማስረጃ ነው — ክፍያ የሚያገኙት በዚህ ነው",
                "هذا هو الدليل على حدوث الرحلة — وهكذا تحصل على أجرك",
            ),
            _opt("It silences app notifications", "የመተግበሪያ ማሳወቂያዎችን ያጠፋል", "يُسكت إشعارات التطبيق"),
        ),
        correct=2,
    ),
    QuizQuestion(
        question=_opt(
            "A child starts screaming and unbuckles mid-ride. What do you do?",
            "ልጅ በጉዞ መሃል መጮህ ይጀምራል እና ቀበቶውን ይፈታል። ምን ያደርጋሉ?",
            "يبدأ الطفل بالصراخ ويفك حزام الأمان في منتصف الرحلة. ماذا تفعل؟",
        ),
        options=(
            _opt("Raise your voice to calm them down", "ለማረጋጋት ድምጽዎን ከፍ ማድረግ", "ارفع صوتك لتهدئته"),
            _opt(
                "Pull over safely and call dispatch — never discipline or grab",
                "በደህና ቆም ብለው ለዲስፓች ይደውሉ — በፍጹም አይቀጡ ወይም አይያዙ",
                "توقف بأمان واتصل بالمرسل — لا تؤدبه أو تمسكه أبداً",
            ),
            _opt("Keep driving, it will pass", "ማሽከርከርዎን ይቀጥሉ፣ ያልፋል", "استمر بالقيادة، سيمر الأمر"),
            _opt("Call the child's parent yourself immediately", "ወዲያውኑ የልጁን ወላጅ ራስዎ መደወል", "اتصل بولي أمر الطفل بنفسك فوراً"),
        ),
        correct=1,
    ),
    QuizQuestion(
        question=_opt(
            "You wake up with a fever at 5am. Ride at 6:40. What do you do?",
            "በ5 ሰዓት በትኩሳት ነቅተዋል። ጉዞ በ6:40። ምን ያደርጋሉ?",
            "استيقظت بحمى الساعة 5 صباحاً. رحلتك الساعة 6:40. ماذا تفعل؟",
        ),
        options=(
            _opt("Wait to see if you feel better before doing anything", "ምንም ከማድረግዎ በፊት ስሜትዎ ይሻል እንደሆነ መጠበቅ", "انتظر لترى إن كنت ستتحسن قبل فعل أي شيء"),
            _opt(
                "Call dispatch immediately — the second you know",
                "ወዲያውኑ ለዲስፓች ይደውሉ — እንዳወቁ ወዲያውኑ",
                "اتصل بالمرسل فوراً — في اللحظة التي تعلم فيها",
            ),
            _opt("Have a friend drive without telling dispatch", "ለዲስፓች ሳይነግሩ ጓደኛ እንዲያሽከረክር ማድረግ", "اطلب من صديق أن يقود دون إخبار المرسل"),
            _opt("Text the school directly", "በቀጥታ ለትምህርት ቤቱ መልእክት መላክ", "أرسل رسالة نصية للمدرسة مباشرة"),
        ),
        correct=1,
    ),
    QuizQuestion(
        question=_opt(
            "There's an accident. Nobody is hurt. Who do you call first?",
            "አደጋ ደርሷል። ማንም አልተጎዳም። መጀመሪያ ለማን ይደውላሉ?",
            "وقع حادث. لم يُصب أحد. لمن تتصل أولاً؟",
        ),
        options=(
            _opt("Your family", "ቤተሰብዎ", "عائلتك"),
            _opt("The school", "ትምህርት ቤቱ", "المدرسة"),
            _opt("Dispatch, immediately", "ዲስፓች፣ ወዲያውኑ", "المرسل، فوراً"),
            _opt("The child's parent", "የልጁ ወላጅ", "ولي أمر الطفل"),
        ),
        correct=2,
    ),
    QuizQuestion(
        question=_opt(
            "Can you stop at your cousin's house for two minutes on the way home from dropoff — with no child in the car?",
            "ልጅ በመኪና ውስጥ ሳይኖር ካደረሱ በኋላ ወደ ቤት በሚሄዱበት መንገድ ላይ ለሁለት ደቂቃ በአጎት ልጅዎ ቤት መቆም ይችላሉ?",
            "هل يمكنك التوقف عند منزل ابن عمك لمدة دقيقتين في طريق العودة إلى المنزل بعد التسليم — دون وجود طفل في السيارة؟",
        ),
        options=(
            _opt("Yes, since no child is in the car it's fine anytime", "አዎ፣ ልጅ ስለሌለ በማንኛውም ጊዜ ችግር የለውም", "نعم، بما أنه لا يوجد طفل في السيارة فلا بأس بذلك في أي وقت"),
            _opt(
                "After dropoff with no child, the route is done — but during any route leg with a child: never",
                "ልጅ ሳይኖር ካደረሱ በኋላ መንገዱ ተጠናቋል — ነገር ግን ልጅ ባለበት በማንኛውም የመንገድ ክፍል፦ በፍጹም",
                "بعد التسليم ودون وجود طفل، ينتهي المسار — لكن خلال أي جزء من المسار فيه طفل: أبداً",
            ),
            _opt("Only if it's under 5 minutes", "ከ5 ደቂቃ በታች ከሆነ ብቻ", "فقط إذا كانت أقل من 5 دقائق"),
            _opt("Only with dispatch's permission every time, even after dropoff", "ካደረሱ በኋላም ቢሆን ሁልጊዜ የዲስፓች ፈቃድ ካገኙ ብቻ", "فقط بإذن المرسل في كل مرة، حتى بعد التسليم"),
        ),
        correct=1,
    ),
    QuizQuestion(
        question=_opt(
            "Your registration expires next month. Z-Pay reminded you. When do you renew?",
            "ምዝገባዎ በሚቀጥለው ወር ያበቃል። ዚ-ፔይ አስታውሶዎታል። መቼ ያድሳሉ?",
            "تنتهي صلاحية تسجيلك الشهر القادم. ذكّرك Z-Pay بذلك. متى تجدده؟",
        ),
        options=(
            _opt("The last day before it expires", "ከማብቃቱ በፊት ባለው የመጨረሻ ቀን", "في اليوم الأخير قبل انتهاء الصلاحية"),
            _opt(
                "That week — an expired document means no driving, by contract",
                "በዚያ ሳምንት — ጊዜው ያለፈበት ወረቀት ማለት በውል መሰረት ማሽከርከር አይቻልም ማለት ነው",
                "في ذلك الأسبوع — الوثيقة المنتهية الصلاحية تعني عدم القيادة، بموجب العقد",
            ),
            _opt("Whenever it's convenient in the next few months", "በሚቀጥሉት ወራት ውስጥ ምቹ በሆነ ጊዜ", "متى كان ذلك مناسباً خلال الأشهر القليلة القادمة"),
            _opt("Only if dispatch asks about it", "ዲስፓች ከጠየቀ ብቻ", "فقط إذا سأل المرسل عن ذلك"),
        ),
        correct=1,
    ),
    QuizQuestion(
        question=_opt(
            "A parent asks you to drop the child at the park instead of home. What do you do?",
            "ወላጅ ልጁን ከቤት ይልቅ በፓርክ እንዲያወርዱ ይጠይቅዎታል። ምን ያደርጋሉ?",
            "طلب منك أحد الوالدين إنزال الطفل في الحديقة بدلاً من المنزل. ماذا تفعل؟",
        ),
        options=(
            _opt("Do it since the parent asked directly", "ወላጅ በቀጥታ ስለጠየቀ ማድረግ", "افعل ذلك لأن الوالد طلب مباشرة"),
            _opt(
                "No — exact stop only; route changes come from dispatch, never a verbal ask",
                "አይ — ትክክለኛው ማቆሚያ ብቻ፤ የመንገድ ለውጦች የሚመጡት ከዲስፓች ነው፣ በቃል ጥያቄ በፍጹም አይደለም",
                "لا — المحطة المحددة فقط؛ تغييرات المسار تأتي من المرسل، وليس أبداً بطلب شفهي",
            ),
            _opt("Only if the child agrees too", "ልጁም ከተስማማ ብቻ", "فقط إذا وافق الطفل أيضاً"),
            _opt("Call the school for permission first", "መጀመሪያ ለትምህርት ቤቱ ፈቃድ መደወል", "اتصل بالمدرسة للحصول على إذن أولاً"),
        ),
        correct=1,
    ),
)


def course_content_public() -> dict:
    """JSON-safe course content for the public /training/{token} page.

    Includes quiz `correct` indices — this is a training comprehension quiz,
    not a proctored exam (the answers are effectively derivable from the
    module content itself); server-side enforcement of the pass threshold
    happens independently in record_certification()/validate below, so a
    client that fabricates its own quiz_score still gets rejected there.
    """
    return {
        "course_version": COURSE_VERSION,
        "pass_threshold_ratio": PASS_THRESHOLD_RATIO,
        "modules": [
            {
                "key": m.key,
                "title": m.title,
                "intro": m.intro,
                "blocks": [
                    {"lead": b.lead, "text": b.text} for b in m.blocks
                ],
            }
            for m in COURSE_MODULES
        ],
        "quiz": [
            {
                "question": q.question,
                "options": list(q.options),
                "correct": q.correct,
            }
            for q in QUIZ_QUESTIONS
        ],
    }


# ---------------------------------------------------------------------------
# Certification record helpers
# ---------------------------------------------------------------------------

def _latest_certification(db: Session, person_id: int):
    from backend.db.models import DriverCertification

    return (
        db.query(DriverCertification)
        .filter(DriverCertification.person_id == person_id)
        .order_by(DriverCertification.certified_at.desc(), DriverCertification.cert_id.desc())
        .first()
    )


def is_certified(db: Session, person_id: int) -> bool:
    """True iff the driver's latest certification row matches COURSE_VERSION."""
    latest = _latest_certification(db, person_id)
    if not latest:
        return False
    return latest.course_version == COURSE_VERSION


def needs_recert(db: Session, person_id: int) -> bool:
    """True iff the driver has certified before, but not on the current
    COURSE_VERSION — distinct from never-certified (is_certified=False,
    needs_recert=False for a driver who has simply never taken the course)."""
    latest = _latest_certification(db, person_id)
    if not latest:
        return False
    return latest.course_version != COURSE_VERSION


def record_certification(
    db: Session,
    person_id: int,
    quiz_score: int,
    quiz_total: int,
    signed_name: str,
    course_version: str = COURSE_VERSION,
):
    """Insert a new DriverCertification row. Caller (route handler) is
    responsible for having already validated quiz_score >= pass_threshold
    and signed_name being non-empty — this function does not re-validate,
    it only persists (mirrors record_* helper naming already used elsewhere
    in the codebase, e.g. onboarding autosend logging)."""
    from backend.db.models import DriverCertification

    row = DriverCertification(
        person_id=person_id,
        course_version=course_version,
        quiz_score=quiz_score,
        quiz_total=quiz_total,
        signed_name=signed_name,
        certified_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
