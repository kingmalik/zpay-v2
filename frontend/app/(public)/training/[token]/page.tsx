'use client'

import React, { use, useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence, PanInfo } from 'framer-motion'
import {
  Smartphone,
  ShirtIcon,
  BadgeDollarSign,
  ChevronRight,
  ChevronLeft,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Clock,
  Car,
  Phone,
  X,
  Check,
  FileText,
  BookOpen,
} from 'lucide-react'
import { api } from '@/lib/api'

/* ─── Types ──────────────────────────────────────────────────────────── */

type Lang = 'en' | 'ar' | 'am'
type Screen = 'welcome' | 'slides' | 'quiz' | 'complete'

interface OnboardingRecord {
  person_name?: string
  person_language?: string
  maz_training_status?: string
  [key: string]: unknown
}

/* ─── Translations ───────────────────────────────────────────────────── */

const T = {
  welcome: {
    en: 'Welcome to Acumen',
    ar: 'مرحباً بك في أكيومن',
    am: 'ወደ አኩመን እንኳን ደህና መጡ',
  },
  welcomeSub: {
    en: 'Driver Training Program',
    ar: 'برنامج تدريب السائقين',
    am: 'የሾፌር ሥልጠና ፕሮግራም',
  },
  welcomeBody: {
    en: 'Complete these 9 training modules to learn everything you need to know before your first ride. Takes about 15 minutes.',
    ar: 'أكمل هذه الوحدات التدريبية التسع لتتعلم كل ما تحتاج معرفته قبل أول رحلة لك. يستغرق حوالي 15 دقيقة.',
    am: 'ከመጀመሪያ ጉዞዎ በፊት ማወቅ ያለብዎትን ሁሉ ለመማር እነዚህን 9 የሥልጠና ሞጁሎች ይጨርሱ። ወደ 15 ደቂቃ ይወስዳል።',
  },
  startTraining: { en: 'Start Training', ar: 'ابدأ التدريب', am: 'ሥልጠና ጀምር' },
  next: { en: 'Next', ar: 'التالي', am: 'ቀጣይ' },
  back: { en: 'Back', ar: 'السابق', am: 'ተመለስ' },
  moduleOf: {
    en: (c: number, total: number) => `${c} of ${total}`,
    ar: (c: number, total: number) => `${c} من ${total}`,
    am: (c: number, total: number) => `${c} ከ ${total}`,
  },
  ackTitle: { en: 'Training Complete', ar: 'التدريب مكتمل', am: 'ሥልጠና ተጠናቋል' },
  ackCheck: {
    en: 'I have read and understood all training materials',
    ar: 'لقد قرأت وفهمت جميع مواد التدريب',
    am: 'ሁሉንም የሥልጠና ቁሳቁሶች አንብቤ ተረድቻለሁ',
  },
  ackName: {
    en: 'Type your full name to confirm',
    ar: 'اكتب اسمك الكامل للتأكيد',
    am: 'ለማረጋገጥ ሙሉ ስምዎን ይጻፉ',
  },
  completeBtn: { en: 'Complete Training', ar: 'إكمال التدريب', am: 'ሥልጠና ጨርስ' },
  completing: { en: 'Submitting...', ar: 'جاري التقديم...', am: 'በማስገባት ላይ...' },
  done: { en: "You're all set!", ar: 'أنت جاهز!', am: 'ሁሉም ተዘጋጅቷል!' },
  doneBody: {
    en: 'Your training is complete. Your dispatcher will contact you with your first route assignment.',
    ar: 'تدريبك مكتمل. سيتصل بك المرسل بأول مهمة.',
    am: 'ሥልጠናዎ ተጠናቋል። መላኪያዎ በመጀመሪያ የመንገድ ምደባ ያገኙዎታል።',
  },
  alreadyDone: { en: 'Training already completed', ar: 'التدريب مكتمل بالفعل', am: 'ሥልጠና ቀድሞውኑ ተጠናቋል' },
  error: {
    en: 'Something went wrong. Please try again.',
    ar: 'حدث خطأ. يرجى المحاولة مرة أخرى.',
    am: 'ስህተት ተፈጥሯል። እባክዎ እንደገና ይሞክሩ።',
  },
  loading: { en: 'Loading training...', ar: 'جاري تحميل التدريب...', am: 'ሥልጠና በመጫን ላይ...' },
  selectLang: { en: 'Choose your language', ar: 'اختر لغتك', am: 'ቋንቋዎን ይምረጡ' },

  /* ── Module titles ── */
  m1_title: { en: 'The FirstAlt App: Step by Step', ar: 'تطبيق FirstAlt: خطوة بخطوة', am: 'FirstAlt መተግበሪያ: ደረጃ በደረጃ' },
  m2_title: { en: 'Pickup Rules', ar: 'قواعد الالتقاء', am: 'የማንሻ ደንቦች' },
  m3_title: { en: 'On the Road', ar: 'على الطريق', am: 'በመንገድ ላይ' },
  m4_title: { en: 'Required Gear', ar: 'المعدات المطلوبة', am: 'አስፈላጊ ዕቃዎች' },
  m5_title: { en: 'Your Pay', ar: 'راتبك', am: 'ክፍያዎ' },
  m6_title: { en: 'Who to Call & When', ar: 'لمن تتصل ومتى', am: 'ለማን መደወል እና መቼ' },

  /* ── Module 1: Steps ── */
  m1_steps: {
    en: [
      ['ACCEPT YOUR RIDE EARLY', 'You must accept your ride AT LEAST 1 hour before pickup time. When a notification comes in, open the app and tap Accept immediately. Do not wait.'],
      ['READ THE STUDENT NOTES', 'Before you leave, open the ride details and read every note. Know the student\'s name, any special needs or behavioral notes, and the exact pickup address.'],
      ['LEAVE ON TIME', 'The app tracks your GPS location and speed at all times. Dispatch can see exactly where you are. Plan your route before you leave. There is no excuse for being late.'],
      ['MARK ARRIVAL', 'When you get to the pickup location, the GPS tracking in the app may mark your arrival automatically — or you may need to mark it yourself. Either way, this starts your 10-minute wait timer.'],
      ['WAIT 10 FULL MINUTES', 'If the student does not come out, wait the FULL 10 minutes. Do not leave early. After 10 minutes, call dispatch to confirm whether the student is at school or not. Once dispatch gives you confirmation, you can mark No-Load and leave.'],
      ['START THE RIDE', 'Once the student is safely in the vehicle, tap Start Ride.'],
      ['COMPLETE & CLOSE', 'After drop-off, tap Complete. Never leave a ride open in the app.'],
    ],
    ar: [
      ['اقبل رحلتك مبكراً', 'يجب أن تقبل رحلتك قبل ساعة واحدة على الأقل من وقت الالتقاء. عندما يأتي إشعار، افتح التطبيق واضغط قبول فوراً. لا تنتظر.'],
      ['اقرأ ملاحظات الطالب', 'قبل أن تغادر، افتح تفاصيل الرحلة واقرأ كل ملاحظة. اعرف اسم الطالب وأي احتياجات خاصة أو ملاحظات سلوكية والعنوان الدقيق.'],
      ['غادر في الوقت المحدد', 'التطبيق يتتبع موقعك وسرعتك في جميع الأوقات. المرسل يمكنه رؤية مكانك بالضبط. خطط لمسارك قبل المغادرة. لا عذر للتأخر.'],
      ['سجّل الوصول', 'عند وصولك لموقع الالتقاء، قد يسجّل تتبع GPS وصولك تلقائياً — أو قد تحتاج إلى تسجيله بنفسك. في كلتا الحالتين، هذا يبدأ مؤقت الانتظار 10 دقائق.'],
      ['انتظر 10 دقائق كاملة', 'إذا لم يخرج الطالب، انتظر 10 دقائق كاملة. لا تغادر مبكراً. بعد 10 دقائق، اتصل بالمرسل للتأكد من وجود الطالب في المدرسة أم لا. بمجرد حصولك على تأكيد من المرسل، يمكنك تسجيل بدون حمولة والمغادرة.'],
      ['ابدأ الرحلة', 'بمجرد أن يكون الطالب بأمان في السيارة، اضغط بدء الرحلة.'],
      ['أكمل وأغلق', 'بعد التوصيل، اضغط إكمال. لا تترك رحلة مفتوحة في التطبيق أبداً.'],
    ],
    am: [
      ['ጉዞዎን ቀድመው ተቀበሉ', 'ጉዞዎን ቢያንስ ከማንሻ ጊዜ 1 ሰዓት ቀደም ብለው መቀበል አለብዎት። ማሳወቂያ ሲመጣ መተግበሪያውን ከፍተው ወዲያው ተቀበሉ ይጫኑ። አይጠብቁ።'],
      ['የተማሪ ማስታወሻዎችን ያንብቡ', 'ከመውጣትዎ በፊት የጉዞ ዝርዝሮችን ከፍተው ሁሉንም ማስታወሻ ያንብቡ። የተማሪውን ስም፣ ልዩ ፍላጎቶች ወይም የባህሪ ማስታወሻዎች፣ እና ትክክለኛውን አድራሻ ይወቁ።'],
      ['በሰዓቱ ይውጡ', 'መተግበሪያው GPS ቦታዎን እና ፍጥነትዎን ሁልጊዜ ይከታተላል። ዲስፓች ያሉበትን ቦታ በትክክል ማየት ይችላል። ከመውጣትዎ በፊት መንገድዎን ያቅዱ። ለመዘግየት ምክንያት የለም።'],
      ['መድረስዎን ያመልክቱ', 'ወደ ማንሻ ቦታ ሲደርሱ፣ የመተግበሪያው GPS 추적 መድረስዎን ራሱ ሊያስመዘግብ ይችላል — ወይም እርስዎ ራስዎ ማስመዝገብ ሊያስፈልግዎ ይችላል። ሁለቱም ሁኔታ የ10 ደቂቃ የጠበቃ ቆጣሪዎን ያስጀምራሉ።'],
      ['10 ደቂቃ ሙሉ ይጠብቁ', 'ተማሪው ካልወጣ 10 ደቂቃ ሙሉ ይጠብቁ። ቀድሞ አይውጡ። ከ10 ደቂቃ በኋላ ተማሪው ትምህርት ቤት እንዳለ አይደለምን ለማረጋገጥ ለዲስፓች ይደውሉ። ዲስፓች ማረጋገጫ ከሰጠዎ፣ ባዶ ጉዞ ምልክት አድርገው መሄድ ይችላሉ።'],
      ['ጉዞውን ይጀምሩ', 'ተማሪው በደህና በተሽከርካሪው ውስጥ ከገባ በኋላ ጉዞ ጀምር ን ይጫኑ።'],
      ['ያጠናቅቁ እና ይዝጉ', 'ካወረዱ በኋላ ያጠናቅቁ ን ይጫኑ። ጉዞን በመተግበሪያ ውስጥ ክፍት አይተዉ።'],
    ],
  },
  m1_screenshotPlaceholder: {
    en: 'App screenshot coming soon',
    ar: 'لقطة شاشة التطبيق قريباً',
    am: 'የመተግበሪያ ቅጽበታዊ ገፅ እይታ በቅርቡ',
  },

  /* ── Module 2: Pickup Rules ── */
  m2_never_label: { en: 'NEVER', ar: 'ممنوع تماماً', am: 'በፍጹም' },
  m2_always_label: { en: 'ALWAYS', ar: 'دائماً', am: 'ሁልጊዜ' },
  m2_never: {
    en: [
      'Never be late to a pickup. The app and school both track your arrival time.',
      'Never mark No-Load before waiting the full 10 minutes.',
      'Never let anyone other than the assigned student into your vehicle. Not family, not friends, nobody.',
      'Never do a No-Load without calling dispatch first and getting confirmation.',
    ],
    ar: [
      'لا تتأخر أبداً عن الالتقاء. التطبيق والمدرسة كلاهما يتتبعان وقت وصولك.',
      'لا تسجل بدون حمولة أبداً قبل الانتظار 10 دقائق كاملة.',
      'لا تسمح لأي شخص غير الطالب المخصص بركوب سيارتك. لا عائلة، لا أصدقاء، لا أحد.',
      'لا تسجل بدون حمولة أبداً دون الاتصال بالمرسل أولاً والحصول على تأكيد.',
    ],
    am: [
      'ማንሻ ጊዜ በፍጹም አይዘግዩ። መተግበሪያው እና ትምህርት ቤቱ ሁለቱም የመድረሻ ጊዜዎን ይከታተላሉ።',
      '10 ደቂቃ ሙሉ ከመጠበቅዎ በፊት በፍጹም ባዶ ጉዞ አያስመዝግቡ።',
      'ከተመደበው ተማሪ ውጪ ማንንም ወደ መኪናዎ አይፍቀዱ። ቤተሰብ አይደለም፣ ጓደኛ አይደለም፣ ማንም።',
      'ለዲስፓች ሳይደውሉ እና ማረጋገጫ ሳያገኙ በፍጹም ባዶ ጉዞ አያድርጉ።',
    ],
  },
  m2_always: {
    en: [
      'Always accept your ride at least 1 hour early.',
      'Always read the student notes before leaving — know who you\'re picking up.',
      'Always have your Acumen plaque visible on the dashboard before you arrive at the school.',
      'Always call dispatch if you are going to be late — not Malik, not the school directly. Dispatch handles it.',
    ],
    ar: [
      'اقبل رحلتك دائماً قبل ساعة على الأقل.',
      'اقرأ ملاحظات الطالب دائماً قبل المغادرة — اعرف من تلتقط.',
      'ضع لوحة أكيومن دائماً بشكل مرئي على لوحة القيادة قبل الوصول للمدرسة.',
      'اتصل بالمرسل دائماً إذا كنت ستتأخر — ليس مالك، ليس المدرسة مباشرة. المرسل يتولى الأمر.',
    ],
    am: [
      'ጉዞዎን ሁልጊዜ ቢያንስ 1 ሰዓት ቀደም ብለው ይቀበሉ።',
      'ከመውጣትዎ በፊት ሁልጊዜ የተማሪ ማስታወሻዎችን ያንብቡ — ማንን እንደሚያነሱ ይወቁ።',
      'ትምህርት ቤት ከመድረስዎ በፊት ሁልጊዜ የአኩመን ሰሌዳዎ በዳሽቦርድ ላይ እንዲታይ ያድርጉ።',
      'ሊዘገዩ ከሆነ ሁልጊዜ ለዲስፓች ይደውሉ — ለማሊክ አይደለም፣ ለትምህርት ቤቱ በቀጥታ አይደለም። ዲስፓች ያስተናግዳል።',
    ],
  },

  /* ── Module 3: On the Road ── */
  m3_never_label: { en: 'NEVER', ar: 'ممنوع تماماً', am: 'በፍጹም' },
  m3_never: {
    en: [
      'Never use your phone while driving with a student in the vehicle. Not texting, not calls, nothing.',
      'Never make food stops, detours, or any side trips. Drive directly to the destination.',
      'Never play loud music or have inappropriate content playing.',
      'Never bring personal passengers (family, friends) when you have a student route.',
    ],
    ar: [
      'لا تستخدم هاتفك أبداً أثناء القيادة مع طالب في السيارة. لا رسائل، لا مكالمات، لا شيء.',
      'لا تتوقف لشراء طعام أو تأخذ منعطفات أو أي رحلات جانبية. اقد مباشرة إلى الوجهة.',
      'لا تشغل موسيقى عالية أو محتوى غير مناسب.',
      'لا تحضر ركاب شخصيين (عائلة، أصدقاء) عندما يكون لديك مسار طالب.',
    ],
    am: [
      'ተማሪ በተሽከርካሪው ውስጥ ሳለ ስልክዎን በፍጹም አይጠቀሙ። መልእክት አይደለም፣ ጥሪ አይደለም፣ ምንም።',
      'ለምግብ አይቁሙ፣ አይዞሩ፣ ወይም ምንም ተጨማሪ ጉዞ አያድርጉ። በቀጥታ ወደ መድረሻ ያሽከርክሩ።',
      'ጮኸ ሙዚቃ ወይም ተገቢ ያልሆነ ይዘት አያጫውቱ።',
      'የተማሪ መንገድ ሲኖርዎት የግል ተሳፋሪዎችን (ቤተሰብ፣ ጓደኞች) አያምጡ።',
    ],
  },
  m3_special_label: { en: 'IMPORTANT — Special Needs Transport', ar: 'مهم — نقل ذوي الاحتياجات الخاصة', am: 'አስፈላጊ — ልዩ ፍላጎት ትራንስፖርት' },
  m3_special: {
    en: 'You are transporting children with special needs. Some students may have physical or behavioral disabilities. Be patient, calm, and professional at all times. Never raise your voice. Never react with frustration. If a situation is escalating, pull over safely and call dispatch.',
    ar: 'أنت تنقل أطفالاً ذوي احتياجات خاصة. بعض الطلاب قد يعانون من إعاقات جسدية أو سلوكية. كن صبوراً وهادئاً ومحترفاً في جميع الأوقات. لا ترفع صوتك أبداً. لا تتفاعل بإحباط. إذا تصاعد الموقف، توقف بأمان واتصل بالمرسل.',
    am: 'ልዩ ፍላጎት ያላቸውን ልጆች እያጓጓዙ ነው። አንዳንድ ተማሪዎች የአካል ወይም የባህሪ እክሎች ሊኖራቸው ይችላል። ሁልጊዜ ታጋሽ፣ ረጋ ያለ እና ሙያዊ ይሁኑ። ድምጽዎን በፍጹም አያሰሙ። በብስጭት አይሰሩ። ሁኔታው እየተባባሰ ከሆነ፣ በደህና ቆም ብለው ለዲስፓች ይደውሉ።',
  },
  m3_pro_label: { en: 'PROFESSIONALISM', ar: 'الاحترافية', am: 'ሙያዊነት' },
  m3_pro: {
    en: [
      'Clean vehicle, professional appearance for every shift.',
      'If you are going to be late: call dispatch immediately. Dispatch will contact the school. Do NOT call the school yourself. Do NOT call Malik for operational issues — dispatch handles everything.',
    ],
    ar: [
      'سيارة نظيفة، مظهر محترف لكل وردية.',
      'إذا كنت ستتأخر: اتصل بالمرسل فوراً. المرسل سيتصل بالمدرسة. لا تتصل بالمدرسة بنفسك. لا تتصل بمالك للمشاكل التشغيلية — المرسل يتولى كل شيء.',
    ],
    am: [
      'ንጹህ ተሽከርካሪ፣ ለእያንዳንዱ ፈረቃ ሙያዊ ገጽታ።',
      'ሊዘገዩ ከሆነ: ወዲያው ለዲስፓች ይደውሉ። ዲስፓች ትምህርት ቤቱን ያገኛል። ራስዎ ለትምህርት ቤቱ አይደውሉ። ለማሊክ ለአሰራር ጉዳዮች አይደውሉ — ዲስፓች ሁሉንም ያስተናግዳል።',
    ],
  },

  /* ── Module 4: Required Gear ── */
  m4_vest_title: { en: 'Safety Vest', ar: 'سترة السلامة', am: 'የደህንነት ቀሚስ' },
  m4_vest_required: { en: 'Every single pickup and drop-off, no exceptions.', ar: 'كل التقاء وتوصيل بدون استثناء.', am: 'ሁሉም ማንሻ እና ማውረድ፣ ምንም ልዩ ሁኔታ የለም።' },
  m4_vest_why: {
    en: 'At school zones, staff and parents need to identify you as a professional transport driver — not a random car.',
    ar: 'في مناطق المدارس، يحتاج الموظفون وأولياء الأمور لتحديدك كسائق نقل محترف — وليس سيارة عشوائية.',
    am: 'በትምህርት ቤት ዞኖች፣ ሰራተኞች እና ወላጆች እርስዎን ሙያዊ ትራንስፖርት ሾፌር ሆነው ማወቅ ያስፈልጋቸዋል — የዘፈቀደ መኪና አይደለም።',
  },
  m4_vest_rule: {
    en: 'If you show up without your vest, you may be turned away. This is a contract requirement.',
    ar: 'إذا حضرت بدون سترتك، قد يتم إرجاعك. هذا متطلب عقدي.',
    am: 'ያለ ቀሚስዎ ከመጡ ሊመለሱ ይችላሉ። ይህ የውል ግዴታ ነው።',
  },
  m4_plaque_title: { en: 'Acumen Plaque', ar: 'لوحة أكيومن', am: 'የአኩመን ሰሌዳ' },
  m4_plaque_required: { en: 'On your dashboard, visible from outside the windshield, for every shift.', ar: 'على لوحة القيادة، مرئية من خارج الزجاج الأمامي، لكل وردية.', am: 'በዳሽቦርድዎ ላይ፣ ከመስታወት ውጭ የሚታይ፣ ለእያንዳንዱ ፈረቃ።' },
  m4_plaque_why: {
    en: 'Schools will not release a student to a vehicle they cannot identify. Your plaque is how they know you are authorized.',
    ar: 'لن تسلم المدارس طالباً لسيارة لا يمكنهم تحديدها. لوحتك هي كيف يعرفون أنك مخوّل.',
    am: 'ትምህርት ቤቶች ሊለዩት ለማይችሉት ተሽከርካሪ ተማሪ አይለቁም። ሰሌዳዎ እርስዎ የተፈቀደልዎ መሆንዎን የሚያውቁበት መንገድ ነው።',
  },
  m4_plaque_how: {
    en: 'Set it on the dashboard facing outward. It must be readable from outside the car.',
    ar: 'ضعها على لوحة القيادة باتجاه الخارج. يجب أن تكون قابلة للقراءة من خارج السيارة.',
    am: 'ወደ ውጭ እንዲመለከት በዳሽቦርድ ላይ ያስቀምጡት። ከመኪናው ውጭ ሆኖ ሊነበብ የሚችል መሆን አለበት።',
  },
  m4_plaque_rule: {
    en: 'No plaque = no pickup. Schools will turn you away.',
    ar: 'بدون لوحة = بدون التقاء. المدارس سترفضك.',
    am: 'ሰሌዳ ከሌለ = ማንሻ የለም። ትምህርት ቤቶች ይመልሱዎታል።',
  },
  m4_photo_vest: { en: 'Photo: correct vest placement — coming soon', ar: 'صورة: وضع السترة الصحيح — قريباً', am: 'ፎቶ: ትክክለኛ የቀሚስ አቀማመጥ — በቅርቡ' },
  m4_photo_plaque: { en: 'Photo: correct plaque placement — coming soon', ar: 'صورة: وضع اللوحة الصحيح — قريباً', am: 'ፎቶ: ትክክለኛ የሰሌዳ አቀማመጥ — በቅርቡ' },

  /* ── Module 5: Pay ── */
  m5_header: {
    en: 'Read this carefully. Most new driver questions are about pay timing.',
    ar: 'اقرأ هذا بعناية. معظم أسئلة السائقين الجدد عن توقيت الدفع.',
    am: 'ይህንን በጥንቃቄ ያንብቡ። አብዛኛዎቹ አዲስ ሾፌሮች ጥያቄዎች ስለ ክፍያ ጊዜ ናቸው።',
  },
  m5_items: {
    en: [
      'You are paid WEEKLY.',
      'Pay is always 2 WEEKS behind your work dates.',
      'Week 1: You drive. Week 2: Acumen processes. Week 3: You get paid.',
      'Your rate is set. It is not negotiable. You agreed to it when you signed.',
    ],
    ar: [
      'يتم الدفع لك أسبوعياً.',
      'الراتب دائماً متأخر أسبوعين عن تواريخ عملك.',
      'الأسبوع 1: تقود. الأسبوع 2: أكيومن يعالج. الأسبوع 3: تحصل على راتبك.',
      'معدلك محدد. غير قابل للتفاوض. وافقت عليه عند التوقيع.',
    ],
    am: [
      'በሳምንት ይከፈልዎታል።',
      'ክፍያ ሁልጊዜ ከሥራ ቀናትዎ 2 ሳምንት ወደ ኋላ ነው።',
      'ሳምንት 1: ያሽከረክራሉ። ሳምንት 2: አኩመን ያስፈጽማል። ሳምንት 3: ይከፈልዎታል።',
      'ዋጋዎ ተወስኗል። ለድርድር አይቀርብም። ሲፈርሙ ተስማምተዋል።',
    ],
  },
  m5_example_label: { en: 'Example', ar: 'مثال', am: 'ምሳሌ' },
  m5_example: {
    en: 'Start Monday Jan 6 → First paycheck Friday Jan 24.',
    ar: 'تبدأ الاثنين 6 يناير ← أول راتب الجمعة 24 يناير.',
    am: 'ሰኞ ጥር 6 ይጀምሩ → የመጀመሪያ ደመወዝ አርብ ጥር 24።',
  },
  m5_timeline: {
    en: ['Week 1', 'You drive', 'Week 2', 'Acumen processes', 'Week 3', 'You get paid!'],
    ar: ['الأسبوع 1', 'أنت تقود', 'الأسبوع 2', 'أكيومن يعالج', 'الأسبوع 3', 'تحصل على راتبك!'],
    am: ['ሳምንት 1', 'ያሽከረክራሉ', 'ሳምንት 2', 'አኩመን ያስፈጽማል', 'ሳምንት 3', 'ይከፈልዎታል!'],
  },
  m5_pay_questions: {
    en: 'Pay questions? Contact the Acumen office. Do NOT call dispatch about pay. Do NOT call Malik about pay.',
    ar: 'أسئلة عن الراتب؟ اتصل بمكتب أكيومن. لا تتصل بالمرسل عن الراتب. لا تتصل بمالك عن الراتب.',
    am: 'የክፍያ ጥያቄዎች? የአኩመን ቢሮን ያግኙ። ስለ ክፍያ ለዲስፓች አይደውሉ። ስለ ክፍያ ለማሊክ አይደውሉ።',
  },
  m5_pay_missing: {
    en: 'If pay is missing or wrong: Contact the office, wait 24 hours for correction, then escalate if needed.',
    ar: 'إذا كان الراتب مفقوداً أو خاطئاً: اتصل بالمكتب، انتظر 24 ساعة للتصحيح، ثم صعّد إذا لزم الأمر.',
    am: 'ክፍያ ከጠፋ ወይም ከተሳሳተ: ቢሮውን ያግኙ፣ ለማስተካከል 24 ሰዓት ይጠብቁ፣ ከዚያ አስፈላጊ ከሆነ ያሳድጉ።',
  },

  /* ── Module 6: Contacts ── */
  m6_dispatch_title: { en: 'Dispatch (call first for anything ride-related)', ar: 'المرسل (اتصل أولاً لأي شيء متعلق بالرحلة)', am: 'ዲስፓች (ከጉዞ ጋር ለተያያዘ ማንኛውም ነገር መጀመሪያ ይደውሉ)' },
  m6_dispatch_sub: { en: 'Dispatch is your #1 contact.', ar: 'المرسل هو جهة اتصالك الأولى.', am: 'ዲስፓች ቁጥር 1 ግንኙነትዎ ነው።' },
  m6_dispatch_items: {
    en: ['Running late', 'Student no-show after 10 minutes', "Can't find the pickup address", 'Any question about your ride or route'],
    ar: ['تأخير', 'عدم حضور الطالب بعد 10 دقائق', 'لا يمكن إيجاد عنوان الالتقاء', 'أي سؤال عن رحلتك أو مسارك'],
    am: ['ሲዘገዩ', 'ተማሪ ከ10 ደቂቃ በኋላ ያልመጣ', 'የማንሻ አድራሻ ማግኘት ያልቻሉ', 'ስለ ጉዞዎ ወይም መንገድዎ ማንኛውም ጥያቄ'],
  },
  m6_office_title: { en: 'Acumen', ar: 'أكيومن', am: 'አኩመን' },
  m6_office_items: {
    en: ['Student behavioral issue — Acumen must file an incident report', 'Vehicle breakdown on a route — Acumen must file an incident report', 'Pay questions or missing payment', 'Route assignment changes', 'Contract questions', 'Anything that requires official documentation or paperwork'],
    ar: ['مشكلة سلوكية للطالب — أكيومن يجب أن يقدم تقرير حادث', 'عطل في السيارة أثناء المسار — أكيومن يجب أن يقدم تقرير حادث', 'أسئلة عن الراتب أو دفعة مفقودة', 'تغييرات في تخصيص المسارات', 'أسئلة عن العقد', 'أي شيء يتطلب توثيقاً رسمياً أو أوراق'],
    am: ['የተማሪ ባህሪ ችግር — አኩመን ዘጋጣሚ ሪፖርት ማቅረብ አለበት', 'በመንገድ ላይ ተሽከርካሪ ብልሽት — አኩመን ዘጋጣሚ ሪፖርት ማቅረብ አለበት', 'የክፍያ ጥያቄዎች ወይም የጠፋ ክፍያ', 'የመንገድ ምደባ ለውጦች', 'የውል ጥያቄዎች', 'ኦፊሴላዊ ሰነድ ወይም ወረቀት የሚያስፈልጋቸው ሁኔታዎች'],
  },
  m6_emergency_title: { en: 'Emergency Only (911 first, then dispatch)', ar: 'حالات الطوارئ فقط (911 أولاً ثم المرسل)', am: 'ድንገተኛ ብቻ (911 መጀመሪያ፣ ከዚያ ዲስፓች)' },
  m6_emergency_items: {
    en: ['Medical emergency involving a student — 911 immediately, then call dispatch', 'Accident — 911 if injuries, then dispatch', 'Safety threat — 911 first'],
    ar: ['حالة طوارئ طبية تخص طالب — 911 فوراً ثم اتصل بالمرسل', 'حادث — 911 إذا كان هناك إصابات ثم المرسل', 'تهديد أمني — 911 أولاً'],
    am: ['ተማሪን የሚመለከት የህክምና ድንገተኛ — ወዲያው 911፣ ከዚያ ለዲስፓች ይደውሉ', 'አደጋ — ጉዳት ካለ 911፣ ከዚያ ዲስፓች', 'የደህንነት ስጋት — 911 መጀመሪያ'],
  },

  /* ── Module 7, 8, 9: Titles ── */
  m7_title: { en: 'Background Check Email', ar: 'بريد فحص الخلفية', am: 'የጀርባ ምርመራ ኢሜይል' },
  m8_title: { en: 'Using the FirstAlt App', ar: 'استخدام تطبيق FirstAlt', am: 'FirstAlt መተግበሪያ መጠቀም' },
  m9_title: { en: 'Online Training Class', ar: 'فصل التدريب الإلكتروني', am: 'የመስመር ሥልጠና ክፍለ ጊዜ' },

  /* ── Module 7: BGC Email Forward Steps ── */
  m7_steps: {
    en: [
      ['WAIT FOR AN EMAIL FROM BRANDON', 'After Acumen submits your information, Brandon will send a background check link to your email address. Watch for it — it may take 1–2 business days.'],
      ['OPEN THE EMAIL', 'Find the email from Brandon or First Advantage in your inbox. If you do not see it, check your Spam or Junk folder.'],
      ['TAP FORWARD', 'Do NOT click the link yourself. Instead, tap the Forward button in your email app. This is usually an arrow icon (→) at the bottom of the email.'],
      ['ENTER THE ACUMEN EMAIL', 'In the "To" field, type: contact.acumenintl@gmail.com — type it carefully, exactly as written.'],
      ['SEND IT', 'Tap Send. That is it. Do not click the link, do not fill anything out. Just forward and wait.'],
      ['TEXT ACUMEN TO CONFIRM', 'After forwarding, send a text to your Acumen contact to let them know you forwarded the email. Say: "I forwarded the background check email."'],
      ['WAIT FOR CLEARANCE', 'Acumen will complete the background check on your behalf. They will contact you when your results are back and you are cleared to continue.'],
    ],
    ar: [
      ['انتظر بريد إلكتروني من براندون', 'بعد أن يقدم أكيومن معلوماتك، سيرسل براندون رابط فحص الخلفية إلى بريدك الإلكتروني. ترقّب ذلك — قد يستغرق 1-2 يوم عمل.'],
      ['افتح البريد الإلكتروني', 'ابحث عن البريد الإلكتروني من براندون أو First Advantage في صندوق الوارد. إذا لم تجده، تحقق من مجلد البريد العشوائي.'],
      ['اضغط إعادة توجيه', 'لا تنقر على الرابط بنفسك. بدلاً من ذلك، اضغط زر "إعادة توجيه" في تطبيق البريد الإلكتروني. عادةً يكون رمز سهم (→) في أسفل البريد.'],
      ['أدخل بريد أكيومن الإلكتروني', 'في حقل "إلى"، اكتب: contact.acumenintl@gmail.com — اكتبه بعناية، تماماً كما هو مكتوب.'],
      ['أرسله', 'اضغط إرسال. هذا كل شيء. لا تنقر على الرابط، لا تملأ أي شيء. فقط أعد التوجيه وانتظر.'],
      ['أرسل رسالة نصية لأكيومن للتأكيد', 'بعد إعادة التوجيه، أرسل رسالة نصية لجهة الاتصال في أكيومن لإعلامهم. قل: "لقد أعدت توجيه بريد فحص الخلفية."'],
      ['انتظر التخليص', 'سيكمل أكيومن فحص الخلفية نيابةً عنك. سيتصلون بك عندما تعود نتائجك وتُخلَّص للمتابعة.'],
    ],
    am: [
      ['ከብራንዶን ኢሜይል ይጠብቁ', 'አኩመን መረጃዎን ካስገባ በኋላ ብራንዶን የጀርባ ምርመራ ሊንክ ወደ ኢሜይልዎ ይልካሉ። ይጠብቁ — 1-2 የሥራ ቀናት ሊወስድ ይችላል።'],
      ['ኢሜይሉን ይክፈቱ', 'ከብራንዶን ወይም First Advantage የመጣውን ኢሜይል ባጋዘዎ ውስጥ ይፈልጉ። ካላዩ Spam ወይም Junk ፎልደርዎን ያረጋግጡ።'],
      ['ፎርዋርድ ይጫኑ', 'ሊንኩን እርስዎ አይጫኑ። ይልቁንም በኢሜይል መተግበሪያዎ የፎርዋርድ ቁልፍ ይጫኑ። ብዙ ጊዜ ይህ የቀስት ምልክት (→) ነው።'],
      ['የአኩመን ኢሜይል ያስገቡ', '"ለ" (To) ሜዳ ላይ ይጻፉ: contact.acumenintl@gmail.com — በጥንቃቄ፣ ልክ እንደተጻፈው ይጻፉ።'],
      ['ይላኩ', 'ላክ ን ይጫኑ። ያ ብቻ ነው። ሊንኩን አይጫኑ፣ ምንም አይሙሉ። ፎርዋርድ ያድርጉ እና ይጠብቁ።'],
      ['ለአኩመን ጽሑፍ ይላኩ', 'ፎርዋርድ ካደረጉ በኋላ ለአኩመን ተወካይዎ ጽሑፍ ይላኩ። ይበሉ: "የጀርባ ምርመራ ኢሜይሉን ፎርዋርድ አድርጌያለሁ።"'],
      ['ፈቃድ ይጠብቁ', 'አኩመን በምትኩ የጀርባ ምርመራውን ያጠናቅቃሉ። ውጤቶቹ ሲመለሱ እና ሲጸዱ ያገኙዎታል።'],
    ],
  },

  /* ── Module 8: FirstAlt App Daily Steps ── */
  m8_steps: {
    en: [
      ['DOWNLOAD THE APP', 'Download the FirstAlt driver app from the App Store (iPhone) or Google Play (Android). Log in using the credentials Acumen provides to you during onboarding.'],
      ['CHECK FOR ASSIGNED RIDES', 'When you open the app, your assigned rides will appear. You must accept each ride at least 1 hour before the scheduled pickup time. Do not wait.'],
      ['READ THE RIDE DETAILS', 'Tap the ride to open it. Read the student\'s name, special needs notes, pickup address, and drop-off address before you leave home.'],
      ['NAVIGATE TO PICKUP', 'Use the in-app navigation or your own GPS app. The app tracks your GPS location and speed at all times. Dispatch can see where you are.'],
      ['MARK ARRIVAL', 'When you pull up to the pickup address, mark your arrival in the app — or the GPS will mark it automatically. This starts the 10-minute wait timer.'],
      ['START AND COMPLETE THE RIDE', 'Once the student is safely in the vehicle, tap Start Ride. After drop-off, tap Complete. Never leave a ride open in the app.'],
      ['REPORTING ISSUES', 'If there is a no-show, follow the 10-minute rule and call dispatch before marking no-load. For behavioral issues or breakdowns, call Acumen.'],
    ],
    ar: [
      ['تحميل التطبيق', 'قم بتحميل تطبيق السائق FirstAlt من App Store (iPhone) أو Google Play (Android). سجّل الدخول باستخدام بيانات الاعتماد التي يوفرها لك أكيومن أثناء التأهيل.'],
      ['تحقق من الرحلات المخصصة', 'عندما تفتح التطبيق، ستظهر رحلاتك المخصصة. يجب أن تقبل كل رحلة قبل ساعة على الأقل من وقت الالتقاء المقرر. لا تنتظر.'],
      ['اقرأ تفاصيل الرحلة', 'اضغط على الرحلة لفتحها. اقرأ اسم الطالب وملاحظات الاحتياجات الخاصة وعنوان الالتقاء وعنوان التوصيل قبل مغادرة المنزل.'],
      ['انتقل إلى موقع الالتقاء', 'استخدم الملاحة داخل التطبيق أو تطبيق GPS الخاص بك. يتتبع التطبيق موقعك وسرعتك بالـ GPS في جميع الأوقات. يمكن للمرسل رؤية مكانك.'],
      ['سجّل الوصول', 'عند وصولك لعنوان الالتقاء، سجّل وصولك في التطبيق — أو سيسجله GPS تلقائياً. هذا يبدأ مؤقت الانتظار 10 دقائق.'],
      ['ابدأ وأكمل الرحلة', 'بمجرد أن يكون الطالب بأمان في السيارة، اضغط بدء الرحلة. بعد التوصيل، اضغط إكمال. لا تترك رحلة مفتوحة في التطبيق.'],
      ['الإبلاغ عن المشاكل', 'إذا لم يحضر الطالب، اتبع قاعدة 10 دقائق واتصل بالمرسل قبل تسجيل بدون حمولة. للمشاكل السلوكية أو الأعطال، اتصل بأكيومن.'],
    ],
    am: [
      ['መተግበሪያውን ያውርዱ', 'የ FirstAlt ሾፌር መተግበሪያ ከ App Store (iPhone) ወይም Google Play (Android) ያውርዱ። በኦንቦርዲንግ ወቅት አኩመን ከሰጡዎ ምስክርነቶች ጋር ይግቡ።'],
      ['የተመደቡ ጉዞዎችን ያረጋግጡ', 'መተግበሪያውን ሲከፍቱ የተመደቡ ጉዞዎቻዎ ይታያሉ። እያንዳንዱ ጉዞ ቢያንስ ከቀጠሮ ማንሻ ጊዜ 1 ሰዓት ቀደም ብለው መቀበል አለብዎት። አይጠብቁ።'],
      ['የጉዞ ዝርዝሮችን ያንብቡ', 'ጉዞውን ጠቅ ያድርጉ። ከቤት ከመውጣትዎ በፊት የተማሪውን ስም፣ ልዩ ፍላጎቶች ማስታወሻዎች፣ የማንሻ አድራሻ፣ እና የወረጃ አድራሻ ያንብቡ።'],
      ['ወደ ማንሻ ይንቀሳቀሱ', 'በመተግበሪያ ውስጥ ያለ GPS ወይም የራስዎ GPS መተግበሪያ ይጠቀሙ። መተግበሪያው GPS ቦታዎን እና ፍጥነትዎን ሁልጊዜ ይከታተላል። ዲስፓች ያሉበትን ማየት ይችላል።'],
      ['መድረስዎን ያመልክቱ', 'ወደ ማንሻ አድራሻ ሲደርሱ መድረስዎን ያመልክቱ — ወይም GPS ራሱ ሊያስተውለው ይችላል። ይህ የ10 ደቂቃ ጊዜ ቆጣሪ ያስጀምራል።'],
      ['ጉዞ ይጀምሩ እና ያጠናቅቁ', 'ተማሪው በደህና ተሽከርካሪ ውስጥ ከገባ በኋላ ጉዞ ጀምር ን ይጫኑ። ካወረዱ በኋላ ያጠናቅቁ ን ይጫኑ። ጉዞን ክፍት አይተዉ።'],
      ['ችግሮችን ይዘግቡ', 'ተማሪ ካልመጣ፣ የ10 ደቂቃ ደንብ ይከተሉ እና ባዶ ጉዞ ከምልክትዎ በፊት ለዲስፓች ይደውሉ። ለባህሪ ችግሮች ወይም ብልሽቶች፣ ለአኩመን ይደውሉ።'],
    ],
  },

  /* ── Module 9: Online Training Steps ── */
  m9_steps: {
    en: [
      ['WAIT FOR YOUR INVITE', 'After your background check is cleared, Acumen will send you a link to the FirstAlt online training portal. Check your email.'],
      ['SET UP YOUR ACCOUNT', 'Click the link and create your account using your real legal name. Your name will appear on your completion certificate.'],
      ['COMPLETE EVERY MODULE', 'Work through all training modules in order. Each module must be fully completed before the next one unlocks. Do not skip or rush.'],
      ['TAKE THE FINAL QUIZ', 'At the end of the training, you will take a short quiz. You must pass to receive your certificate. Read each question carefully.'],
      ['DOWNLOAD YOUR CERTIFICATE', 'Once you pass, download or screenshot your completion certificate. You will need to submit this to Acumen.'],
      ['SEND IT TO ACUMEN', 'Email or text your certificate to your Acumen contact. Do not assume they received it — confirm with them directly.'],
      ['WAIT FOR FINAL CLEARANCE', 'After Acumen reviews your certificate, they will give you final clearance and schedule your first route. You are now ready to drive.'],
    ],
    ar: [
      ['انتظر دعوتك', 'بعد تخليص فحص خلفيتك، سيرسل لك أكيومن رابطاً لبوابة التدريب الإلكتروني لـ FirstAlt. تحقق من بريدك الإلكتروني.'],
      ['إعداد حسابك', 'انقر على الرابط وأنشئ حسابك باستخدام اسمك القانوني الحقيقي. سيظهر اسمك على شهادة الإتمام.'],
      ['أكمل كل الوحدات', 'اعمل على جميع وحدات التدريب بالترتيب. يجب إكمال كل وحدة بالكامل قبل أن تفتح الوحدة التالية. لا تتخطى أو تستعجل.'],
      ['خذ الاختبار النهائي', 'في نهاية التدريب، ستأخذ اختباراً قصيراً. يجب أن تنجح للحصول على شهادتك. اقرأ كل سؤال بعناية.'],
      ['تحميل شهادتك', 'بعد النجاح، قم بتحميل أو لقطة شاشة لشهادة الإتمام. ستحتاج إلى تقديمها لأكيومن.'],
      ['أرسلها لأكيومن', 'أرسل شهادتك بالبريد الإلكتروني أو الرسائل لجهة اتصال أكيومن الخاصة بك. لا تفترض أنهم تلقوها — تأكد معهم مباشرة.'],
      ['انتظر التخليص النهائي', 'بعد مراجعة أكيومن لشهادتك، سيعطونك التخليص النهائي ويجدولون مسارك الأول. أنت الآن جاهز للقيادة.'],
    ],
    am: [
      ['ጥሪዎን ይጠብቁ', 'የጀርባ ምርመራዎ ከጸዳ በኋላ አኩመን ወደ FirstAlt የመስመር ሥልጠና ፖርታል ሊንክ ይልክሎዎታል። ኢሜይልዎን ያረጋግጡ።'],
      ['መለያዎን ያዘጋጁ', 'ሊንኩን ጠቅ ያድርጉ እና ትክክለኛ ህጋዊ ስምዎን ተጠቅመው መለያ ይፍጠሩ። ስምዎ በማጠናቀቂያ ሰርቲፊኬትዎ ላይ ይታያል።'],
      ['ሁሉንም ሞጁሎች ያጠናቅቁ', 'ሁሉንም የሥልጠና ሞጁሎች በቅደም ተከተል ይሥሩ። የሚቀጥለው ከመከፈቱ በፊት እያንዳንዱ ሞጁል ሙሉ በሙሉ መጠናቀቅ አለበት። አይዝለሉ ወይም አይቸኩሉ።'],
      ['የመጨረሻ ፈተና ይፈትኑ', 'ሥልጠናው ሲጠናቀቅ አጭር ፈተና ይፈትናሉ። ሰርቲፊኬቱን ለማግኘት ማለፍ አለብዎት። እያንዳንዱን ጥያቄ በጥንቃቄ ያንብቡ።'],
      ['ሰርቲፊኬትዎን ያውርዱ', 'ካለፉ በኋላ የማጠናቀቂያ ሰርቲፊኬትዎን ያውርዱ ወይም ቅጽበታዊ ምስል ያንሱ። ይህን ለአኩመን ማስገባት ያስፈልጉዎታል።'],
      ['ለአኩመን ይላኩ', 'ሰርቲፊኬቱን ለአኩመን ተወካይዎ በኢሜይል ወይም ጽሑፍ ይላኩ። እንደደረሳቸው አይገምቱ — ቀጥታ ያረጋግጡ።'],
      ['የመጨረሻ ፈቃድ ይጠብቁ', 'አኩመን ሰርቲፊኬትዎን ከገመቱ በኋላ፣ የመጨረሻ ፈቃድ ይሰጡዎታል እና የመጀመሪያ መንገድዎን ይያዛሉ። አሁን ለማሽከርከር ዝግጁ ነዎት።'],
    ],
  },
  /* ── Quiz UI strings ── */
  quiz_title: { en: 'Knowledge Check', ar: 'اختبار المعرفة', am: 'የእውቀት ፍተሻ' },
  quiz_subtitle: { en: 'Answer all questions to complete your training', ar: 'أجب على جميع الأسئلة لإكمال تدريبك', am: 'ሥልጠናዎን ለማጠናቀቅ ሁሉንም ጥያቄዎች ይመልሱ' },
  quiz_submit: { en: 'Submit Answers', ar: 'إرسال الإجابات', am: 'መልሶችን ያስገቡ' },
  quiz_pass: { en: 'You passed! 🎉', ar: 'لقد نجحت! 🎉', am: 'አለፉ! 🎉' },
  quiz_pass_sub: { en: 'Excellent. Scroll down to sign off and complete your training.', ar: 'ممتاز. مرر للأسفل للتوقيع وإكمال تدريبك.', am: 'በጣም ጥሩ። ለመፈረም እና ሥልጠናዎን ለማጠናቀቅ ወደ ታች ሸብልሉ።' },
  quiz_fail: { en: 'Not quite — review and try again', ar: 'ليس تماماً — راجع وحاول مرة أخرى', am: 'ገና አልተሳካም — ይከልሱ እና እንደገና ይሞክሩ' },
  quiz_retry: { en: 'Try Again', ar: 'حاول مرة أخرى', am: 'እንደገና ሞክሩ' },
  quiz_unanswered: { en: 'Please answer all questions before submitting.', ar: 'يرجى الإجابة على جميع الأسئلة قبل الإرسال.', am: 'ከማስገባትዎ በፊት ሁሉንም ጥያቄዎች ይመልሱ።' },
} as const

/* ─── Quiz questions ─────────────────────────────────────────────────── */

interface QuizQuestion {
  q: Record<Lang, string>
  opts: Record<Lang, [string, string, string, string]>
  correct: number
}

const QUIZ_QUESTIONS: QuizQuestion[] = [
  {
    q: {
      en: 'How early must you accept your assigned ride before pickup?',
      ar: 'كم من الوقت قبل موعد الالتقاء يجب أن تقبل رحلتك المخصصة؟',
      am: 'ጉዞዎን ከማንሻ ጊዜ ምን ያህል ቀደም ብለው መቀበል አለብዎት?',
    },
    opts: {
      en: ['30 minutes before', '1 hour before', '2 hours before', 'Anytime before pickup'],
      ar: ['قبل 30 دقيقة', 'قبل ساعة واحدة', 'قبل ساعتين', 'في أي وقت قبل الالتقاء'],
      am: ['ከ30 ደቂቃ በፊት', 'ከ1 ሰዓት በፊት', 'ከ2 ሰዓት በፊት', 'ከማንሻ በፊት ማንኛውም ጊዜ'],
    },
    correct: 1,
  },
  {
    q: {
      en: 'If a student does not come out, how long must you wait before declaring a no-show?',
      ar: 'إذا لم يخرج الطالب، كم من الوقت يجب أن تنتظر قبل الإعلان عن عدم الحضور؟',
      am: 'ተማሪ ካልወጣ ባዶ ጉዞ ከማሳወቅዎ በፊት ምን ያህል ጊዜ መጠበቅ አለብዎት?',
    },
    opts: {
      en: ['5 minutes', '10 minutes', '15 minutes', '20 minutes'],
      ar: ['5 دقائق', '10 دقائق', '15 دقيقة', '20 دقيقة'],
      am: ['5 ደቂቃ', '10 ደቂቃ', '15 ደቂቃ', '20 ደቂቃ'],
    },
    correct: 1,
  },
  {
    q: {
      en: 'After waiting the full time, what must you do BEFORE marking no-load?',
      ar: 'بعد الانتظار الكامل، ماذا يجب أن تفعل قبل تسجيل بدون حمولة؟',
      am: 'ሙሉ ጊዜ ከጠበቁ በኋላ ባዶ ጉዞ ከምልክትዎ በፊት ምን ማድረግ አለብዎት?',
    },
    opts: {
      en: ['Leave immediately', 'Call the school directly', 'Call dispatch to confirm, then mark no-load', 'Text the student'],
      ar: ['اغادر فوراً', 'اتصل بالمدرسة مباشرة', 'اتصل بالمرسل للتأكيد ثم سجّل بدون حمولة', 'أرسل رسالة نصية للطالب'],
      am: ['ወዲያው ይሂዱ', 'ለትምህርት ቤቱ በቀጥታ ይደውሉ', 'ለዲስፓች ደውለው ያረጋግጡ፣ ከዚያ ባዶ ጉዞ ያስምዝግቡ', 'ለተማሪው ጽሑፍ ይላኩ'],
    },
    correct: 2,
  },
  {
    q: {
      en: 'For any ride-related question or problem, who do you call FIRST?',
      ar: 'لأي سؤال أو مشكلة تتعلق بالرحلة، لمن تتصل أولاً؟',
      am: 'ከጉዞ ጋር ለተያያዘ ማንኛውም ጥያቄ ወይም ችግር ለማን መጀመሪያ ይደውላሉ?',
    },
    opts: {
      en: ['Acumen', 'The school', 'Dispatch', '911'],
      ar: ['أكيومن', 'المدرسة', 'المرسل', '911'],
      am: ['አኩመን', 'ትምህርት ቤቱ', 'ዲስፓች', '911'],
    },
    correct: 2,
  },
  {
    q: {
      en: 'If a student has a behavioral issue or your vehicle breaks down, who do you call?',
      ar: 'إذا كان لدى الطالب مشكلة سلوكية أو تعطلت سيارتك، لمن تتصل؟',
      am: 'ተማሪ የባህሪ ችግር ካለ ወይም ተሽከርካሪዎ ቢበላሽ ለማን ይደውላሉ?',
    },
    opts: {
      en: ['Dispatch', 'Acumen', '911', 'The school'],
      ar: ['المرسل', 'أكيومن', '911', 'المدرسة'],
      am: ['ዲስፓች', 'አኩመን', '911', 'ትምህርት ቤቱ'],
    },
    correct: 1,
  },
  {
    q: {
      en: "Can you allow a student's family member to ride in your vehicle?",
      ar: 'هل يمكنك السماح لأحد أفراد عائلة الطالب بالركوب في سيارتك؟',
      am: 'የተማሪ ቤተሰብ አባል ወደ ተሽከርካሪዎ እንዲጋልብ መፍቀድ ይችላሉ?',
    },
    opts: {
      en: ['Yes, if the student approves', 'Yes, in an emergency only', 'Never', 'Only at drop-off'],
      ar: ['نعم، إذا وافق الطالب', 'نعم، في حالات الطوارئ فقط', 'أبداً', 'فقط عند التوصيل'],
      am: ['አዎ፣ ተማሪው ከፈቀደ', 'አዎ፣ ድንገተኛ ሁኔታ ብቻ', 'በፍጹም', 'ሲያወርዱ ብቻ'],
    },
    correct: 2,
  },
  {
    q: {
      en: 'Where do you forward your background check email from First Advantage?',
      ar: 'إلى أين تعيد توجيه بريد فحص الخلفية من First Advantage؟',
      am: 'ከ First Advantage የጀርባ ምርመራ ኢሜይልዎን የት ፎርዋርድ ያደርጋሉ?',
    },
    opts: {
      en: ['You click the link yourself and fill it out', 'contact.acumenintl@gmail.com', 'dispatch@acumen.com', 'You wait for Acumen to handle it without doing anything'],
      ar: ['تنقر على الرابط بنفسك وتملأه', 'contact.acumenintl@gmail.com', 'dispatch@acumen.com', 'تنتظر حتى يتولى أكيومن الأمر بدون أن تفعل شيئاً'],
      am: ['ሊንኩን እርስዎ ጠቅ ያደርጉ እና ይሞሉ', 'contact.acumenintl@gmail.com', 'dispatch@acumen.com', 'አኩመን ያስተናግዳቸዋል ብለው ምንም ሳያደርጉ ይጠብቁ'],
    },
    correct: 1,
  },
]

/* ─── Module data ────────────────────────────────────────────────────── */

type ModuleType = 'steps' | 'rules' | 'gear' | 'pay' | 'contacts'

interface Module {
  key: string
  icon: typeof Smartphone
  titleKey: keyof typeof T
  type: ModuleType
}

const MODULES: Module[] = [
  { key: 'm1', icon: Smartphone, titleKey: 'm1_title', type: 'steps' },
  { key: 'm2', icon: Clock, titleKey: 'm2_title', type: 'rules' },
  { key: 'm3', icon: Car, titleKey: 'm3_title', type: 'rules' },
  { key: 'm4', icon: ShirtIcon, titleKey: 'm4_title', type: 'gear' },
  { key: 'm5', icon: BadgeDollarSign, titleKey: 'm5_title', type: 'pay' },
  { key: 'm6', icon: Phone, titleKey: 'm6_title', type: 'contacts' },
  { key: 'm7', icon: FileText, titleKey: 'm7_title', type: 'steps' },
  { key: 'm8', icon: Smartphone, titleKey: 'm8_title', type: 'steps' },
  { key: 'm9', icon: BookOpen, titleKey: 'm9_title', type: 'steps' },
]

/* ─── Slide transitions ──────────────────────────────────────────────── */

const slideVariants = {
  enter: (dir: number) => ({ x: dir > 0 ? 300 : -300, opacity: 0 }),
  center: { x: 0, opacity: 1 },
  exit: (dir: number) => ({ x: dir > 0 ? -300 : 300, opacity: 0 }),
}

/* ─── Page component ─────────────────────────────────────────────────── */

export default function TrainingPage({
  params,
}: {
  params: Promise<{ token: string }>
}) {
  const { token } = use(params)

  const [lang, setLang] = useState<Lang>('en')
  const [screen, setScreen] = useState<Screen>('welcome')
  const [slideIdx, setSlideIdx] = useState(0)
  const [direction, setDirection] = useState(1)

  const [record, setRecord] = useState<OnboardingRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [ackChecked, setAckChecked] = useState(false)
  const [ackName, setAckName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const [quizAnswers, setQuizAnswers] = useState<Record<number, number>>({})
  const [quizSubmitted, setQuizSubmitted] = useState(false)
  const [quizPassed, setQuizPassed] = useState(false)

  const isRtl = lang === 'ar'

  /* ── Fetch onboarding record ── */
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/join/${token}`)
        if (!res.ok) throw new Error('failed')
        const data: OnboardingRecord = await res.json()
        if (cancelled) return
        setRecord(data)
        if (data.person_language === 'ar') setLang('ar')
        else if (data.person_language === 'am') setLang('am')
        if (data.maz_training_status === 'complete') setSubmitted(true)
      } catch {
        if (!cancelled) setError('not_found')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [token])

  /* ── Navigation ── */
  const goNext = useCallback(() => {
    if (slideIdx < MODULES.length - 1) {
      setDirection(1)
      setSlideIdx((i) => i + 1)
    } else {
      setScreen('quiz')
    }
  }, [slideIdx])

  const goBack = useCallback(() => {
    if (slideIdx > 0) {
      setDirection(-1)
      setSlideIdx((i) => i - 1)
    } else {
      setScreen('welcome')
    }
  }, [slideIdx])

  /* ── Swipe handler ── */
  const handleDragEnd = useCallback(
    (_: unknown, info: PanInfo) => {
      const threshold = 50
      if (info.offset.x < -threshold) goNext()
      else if (info.offset.x > threshold) goBack()
    },
    [goNext, goBack]
  )

  /* ── Submit ── */
  const handleSubmit = async () => {
    if (!ackChecked || !ackName.trim() || submitting) return
    setSubmitting(true)
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/join/${token}/step`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step: 'maz_training', acknowledged: true, name: ackName.trim() }),
      })
      setSubmitted(true)
    } catch {
      setError('submit_failed')
    } finally {
      setSubmitting(false)
    }
  }

  /* ── Helper: get translated string ── */
  const t = (key: keyof typeof T): string => {
    const val = T[key]
    if (!val) return ''
    return (val as Record<Lang, string>)[lang] ?? (val as Record<Lang, string>).en
  }

  /* ── Loading / error states ── */
  if (loading) {
    return (
      <Shell lang={lang}>
        <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-cyan-400" />
          <p className="text-white/60 text-sm">{t('loading')}</p>
        </div>
      </Shell>
    )
  }

  if (error === 'not_found') {
    return (
      <Shell lang={lang}>
        <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
          <AlertCircle className="w-10 h-10 text-red-400" />
          <p className="text-white/60 text-sm text-center">
            Invalid or expired training link.
          </p>
        </div>
      </Shell>
    )
  }

  /* ── Already completed ── */
  if (submitted) {
    return (
      <Shell lang={lang}>
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="flex flex-col items-center justify-center min-h-[60vh] gap-6 text-center px-4"
        >
          <div className="w-20 h-20 rounded-full bg-emerald-500/20 flex items-center justify-center">
            <CheckCircle2 className="w-10 h-10 text-emerald-400" />
          </div>
          <h1 className="text-2xl font-bold text-white">{t('done')}</h1>
          <p className="text-white/60 text-sm leading-relaxed max-w-xs">
            {t('doneBody')}
          </p>
        </motion.div>
      </Shell>
    )
  }

  /* ── Welcome screen ── */
  if (screen === 'welcome') {
    return (
      <Shell lang={lang}>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col items-center justify-center min-h-[80vh] gap-8 px-4"
          dir={isRtl ? 'rtl' : 'ltr'}
        >
          <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-[#667eea] to-[#06b6d4] flex items-center justify-center shadow-lg shadow-cyan-500/20">
            <span className="text-3xl font-black text-white tracking-tight">M</span>
          </div>

          <div className="text-center space-y-2">
            <h1 className="text-2xl font-bold text-white">{t('welcome')}</h1>
            <p className="text-cyan-400 text-sm font-medium">{t('welcomeSub')}</p>
          </div>

          <p className="text-white/50 text-sm text-center leading-relaxed max-w-xs">
            {t('welcomeBody')}
          </p>

          <div className="space-y-3 w-full max-w-xs">
            <p className="text-white/40 text-xs text-center uppercase tracking-wider">
              {t('selectLang')}
            </p>
            <div className="flex gap-2 justify-center">
              {([
                ['en', 'English', '\u{1F1FA}\u{1F1F8}'],
                ['ar', '\u0627\u0644\u0639\u0631\u0628\u064A\u0629', '\u{1F1F8}\u{1F1E6}'],
                ['am', '\u12A0\u121B\u122D\u129B', '\u{1F1EA}\u{1F1F9}'],
              ] as const).map(([code, label, flag]) => (
                <button
                  key={code}
                  onClick={() => setLang(code)}
                  className={`
                    flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium
                    transition-all duration-200
                    ${lang === code
                      ? 'bg-white/15 text-white border border-white/20 shadow-lg shadow-white/5'
                      : 'bg-white/5 text-white/50 border border-white/5 hover:bg-white/10'
                    }
                  `}
                >
                  <span className="text-base">{flag}</span>
                  <span>{label}</span>
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={() => { setScreen('slides'); setSlideIdx(0) }}
            className="
              w-full max-w-xs min-h-[48px] rounded-xl font-semibold text-white text-base
              bg-gradient-to-r from-[#667eea] to-[#06b6d4]
              hover:shadow-lg hover:shadow-cyan-500/25
              active:scale-[0.98] transition-all duration-200
              flex items-center justify-center gap-2
            "
          >
            {t('startTraining')}
            <ChevronRight className="w-5 h-5" />
          </button>

          {record?.person_name && (
            <p className="text-white/30 text-xs">{record.person_name}</p>
          )}
        </motion.div>
      </Shell>
    )
  }

  /* ── Slides screen ── */
  if (screen === 'slides') {
    const mod = MODULES[slideIdx]

    return (
      <Shell lang={lang}>
        <div
          className="flex flex-col min-h-[100dvh] px-4 pb-6 pt-4"
          dir={isRtl ? 'rtl' : 'ltr'}
        >
          <div className="mb-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-white/40 text-xs font-medium uppercase tracking-wider">
                {(T.moduleOf[lang] as (c: number, total: number) => string)(slideIdx + 1, MODULES.length)}
              </span>
              <div className="flex gap-1">
                {MODULES.map((_, i) => (
                  <div
                    key={i}
                    className={`h-1 rounded-full transition-all duration-300 ${
                      i <= slideIdx
                        ? 'w-6 bg-gradient-to-r from-[#667eea] to-[#06b6d4]'
                        : 'w-3 bg-white/10'
                    }`}
                  />
                ))}
              </div>
            </div>
          </div>

          <div className="flex-1 relative overflow-hidden">
            <AnimatePresence initial={false} custom={direction} mode="wait">
              <motion.div
                key={slideIdx}
                custom={direction}
                variants={slideVariants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                drag="x"
                dragConstraints={{ left: 0, right: 0 }}
                dragElastic={0.2}
                onDragEnd={handleDragEnd}
                className="w-full"
              >
                <SlideCard mod={mod} lang={lang} />
              </motion.div>
            </AnimatePresence>
          </div>

          <div className="flex gap-3 mt-6">
            <button
              onClick={goBack}
              className="
                flex-1 min-h-[48px] rounded-xl font-medium text-white/70 text-sm
                bg-white/5 border border-white/10
                hover:bg-white/10 active:scale-[0.98] transition-all
                flex items-center justify-center gap-1
              "
            >
              <ChevronLeft className="w-4 h-4" />
              {t('back')}
            </button>
            <button
              onClick={goNext}
              className="
                flex-[2] min-h-[48px] rounded-xl font-semibold text-white text-sm
                bg-gradient-to-r from-[#667eea] to-[#06b6d4]
                hover:shadow-lg hover:shadow-cyan-500/25
                active:scale-[0.98] transition-all
                flex items-center justify-center gap-1
              "
            >
              {slideIdx < MODULES.length - 1 ? t('next') : t('completeBtn')}
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </Shell>
    )
  }

  /* ── Quiz screen ── */
  if (screen === 'quiz') {
    return (
      <QuizScreen
        lang={lang}
        answers={quizAnswers}
        setAnswers={setQuizAnswers}
        submitted={quizSubmitted}
        passed={quizPassed}
        onSubmit={() => {
          const correct = QUIZ_QUESTIONS.filter((q, i) => quizAnswers[i] === q.correct).length
          setQuizSubmitted(true)
          setQuizPassed(correct === QUIZ_QUESTIONS.length)
        }}
        onRetry={() => {
          setQuizAnswers({})
          setQuizSubmitted(false)
          setQuizPassed(false)
        }}
        onContinue={() => setScreen('complete')}
      />
    )
  }

  /* ── Acknowledgment screen ── */
  return (
    <Shell lang={lang}>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col min-h-[100dvh] px-4 pb-6 pt-8"
        dir={isRtl ? 'rtl' : 'ltr'}
      >
        <div className="flex-1 flex flex-col items-center gap-6">
          <div className="w-16 h-16 rounded-2xl bg-emerald-500/15 flex items-center justify-center">
            <CheckCircle2 className="w-8 h-8 text-emerald-400" />
          </div>

          <h1 className="text-xl font-bold text-white text-center">{t('ackTitle')}</h1>

          <label className="flex items-start gap-3 p-4 rounded-xl bg-white/5 border border-white/10 cursor-pointer w-full max-w-sm">
            <input
              type="checkbox"
              checked={ackChecked}
              onChange={(e) => setAckChecked(e.target.checked)}
              className="mt-0.5 w-5 h-5 rounded accent-cyan-500 flex-shrink-0"
            />
            <span className="text-white/80 text-sm leading-relaxed">
              {t('ackCheck')}
            </span>
          </label>

          <div className="w-full max-w-sm space-y-2">
            <label className="text-white/40 text-xs uppercase tracking-wider">
              {t('ackName')}
            </label>
            <input
              type="text"
              value={ackName}
              onChange={(e) => setAckName(e.target.value)}
              placeholder={record?.person_name ?? ''}
              className="
                w-full px-4 py-3 rounded-xl text-white text-sm
                bg-white/5 border border-white/10
                placeholder:text-white/20
                focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/25
                transition-colors
              "
              dir={isRtl ? 'rtl' : 'ltr'}
            />
          </div>

          {error === 'submit_failed' && (
            <p className="text-red-400 text-sm flex items-center gap-2">
              <AlertCircle className="w-4 h-4" />
              {t('error')}
            </p>
          )}
        </div>

        <div className="flex gap-3 mt-8">
          <button
            onClick={() => setScreen('quiz')}
            className="
              flex-1 min-h-[48px] rounded-xl font-medium text-white/70 text-sm
              bg-white/5 border border-white/10
              hover:bg-white/10 active:scale-[0.98] transition-all
              flex items-center justify-center gap-1
            "
          >
            <ChevronLeft className="w-4 h-4" />
            {t('back')}
          </button>
          <button
            onClick={handleSubmit}
            disabled={!ackChecked || !ackName.trim() || submitting}
            className="
              flex-[2] min-h-[48px] rounded-xl font-semibold text-white text-sm
              bg-gradient-to-r from-emerald-500 to-emerald-600
              hover:shadow-lg hover:shadow-emerald-500/25
              active:scale-[0.98] transition-all
              disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:shadow-none
              flex items-center justify-center gap-2
            "
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('completing')}
              </>
            ) : (
              <>
                <CheckCircle2 className="w-4 h-4" />
                {t('completeBtn')}
              </>
            )}
          </button>
        </div>
      </motion.div>
    </Shell>
  )
}

/* ─── Quiz screen component ──────────────────────────────────────────── */

function QuizScreen({
  lang,
  answers,
  setAnswers,
  submitted,
  passed,
  onSubmit,
  onRetry,
  onContinue,
}: {
  lang: Lang
  answers: Record<number, number>
  setAnswers: React.Dispatch<React.SetStateAction<Record<number, number>>>
  submitted: boolean
  passed: boolean
  onSubmit: () => void
  onRetry: () => void
  onContinue: () => void
}) {
  const [unansweredError, setUnansweredError] = useState(false)

  const handleSubmit = () => {
    if (Object.keys(answers).length < QUIZ_QUESTIONS.length) {
      setUnansweredError(true)
      return
    }
    setUnansweredError(false)
    onSubmit()
  }

  return (
    <div className="min-h-screen bg-[#09090b] text-white px-4 py-8 pb-20 max-w-md mx-auto">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-bold mb-1">{T.quiz_title[lang]}</h1>
        <p className="text-sm text-zinc-500 mb-8">{T.quiz_subtitle[lang]}</p>
      </motion.div>

      <div className="space-y-6">
        {QUIZ_QUESTIONS.map((question, qi) => {
          const selected = answers[qi]
          const isCorrect = submitted && selected === question.correct
          const isWrong = submitted && selected !== undefined && selected !== question.correct

          return (
            <motion.div
              key={qi}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: qi * 0.05 }}
              className={`rounded-2xl border p-4 ${
                submitted
                  ? isCorrect
                    ? 'border-emerald-500/30 bg-emerald-500/5'
                    : isWrong
                    ? 'border-red-500/30 bg-red-500/5'
                    : 'border-white/10 bg-white/[0.03]'
                  : 'border-white/10 bg-white/[0.03]'
              }`}
            >
              <p className="text-sm font-semibold mb-3 leading-relaxed">
                <span className="text-zinc-500 mr-2">{qi + 1}.</span>
                {question.q[lang]}
              </p>
              <div className="space-y-2">
                {question.opts[lang].map((opt, oi) => {
                  const isSelected = selected === oi
                  const showCorrect = submitted && oi === question.correct
                  const showWrong = submitted && isSelected && oi !== question.correct
                  return (
                    <button
                      key={oi}
                      disabled={submitted}
                      onClick={() => !submitted && setAnswers((prev) => ({ ...prev, [qi]: oi }))}
                      className={`w-full text-left px-3 py-2.5 rounded-xl text-sm transition-colors border
                        ${
                          showCorrect
                            ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300'
                            : showWrong
                            ? 'bg-red-500/20 border-red-500/40 text-red-300'
                            : isSelected
                            ? 'bg-blue-500/20 border-blue-500/40 text-white'
                            : 'bg-white/[0.03] border-white/10 text-zinc-300 hover:bg-white/[0.06]'
                        }`}
                    >
                      {opt}
                    </button>
                  )
                })}
              </div>
            </motion.div>
          )
        })}
      </div>

      <div className="mt-8">
        {!submitted ? (
          <>
            {unansweredError && (
              <p className="text-xs text-red-400 mb-3 text-center">{T.quiz_unanswered[lang]}</p>
            )}
            <button
              onClick={handleSubmit}
              className="w-full py-3 min-h-[48px] rounded-xl bg-blue-500 hover:bg-blue-400 text-white font-semibold transition-colors"
            >
              {T.quiz_submit[lang]}
            </button>
          </>
        ) : passed ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="rounded-2xl bg-emerald-500/10 border border-emerald-500/20 p-6 text-center"
          >
            <p className="text-lg font-bold text-emerald-400 mb-1">{T.quiz_pass[lang]}</p>
            <p className="text-sm text-zinc-400 mb-4">{T.quiz_pass_sub[lang]}</p>
            <button
              onClick={onContinue}
              className="w-full py-3 min-h-[48px] rounded-xl bg-emerald-500 hover:bg-emerald-400 text-white font-semibold transition-colors"
            >
              {T.completeBtn[lang]}
            </button>
          </motion.div>
        ) : (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="rounded-2xl bg-red-500/10 border border-red-500/20 p-6 text-center"
          >
            <p className="text-lg font-bold text-red-400 mb-4">{T.quiz_fail[lang]}</p>
            <button
              onClick={onRetry}
              className="w-full py-3 min-h-[48px] rounded-xl bg-red-500 hover:bg-red-400 text-white font-semibold transition-colors"
            >
              {T.quiz_retry[lang]}
            </button>
          </motion.div>
        )}
      </div>
    </div>
  )
}

/* ─── Shell wrapper ──────────────────────────────────────────────────── */

function Shell({ lang, children }: { lang: Lang; children: React.ReactNode }) {
  return (
    <div className="min-h-[100dvh] bg-[#09090b]" dir={lang === 'ar' ? 'rtl' : 'ltr'}>
      <div className="max-w-md mx-auto">{children}</div>
    </div>
  )
}

/* ─── Phone mockup placeholder ───────────────────────────────────────── */

function PhoneMockup({ text }: { text: string }) {
  return (
    <div className="mx-auto my-4 w-[200px]">
      <div className="rounded-2xl border-2 border-white/20 bg-white/[0.03] p-1">
        <div className="rounded-xl bg-white/[0.04] border border-white/5 flex flex-col items-center justify-center py-8 px-3 gap-2">
          <span className="text-2xl">📸</span>
          <span className="text-white/30 text-[11px] text-center leading-tight">{text}</span>
        </div>
      </div>
    </div>
  )
}

/* ─── Slide card component ───────────────────────────────────────────── */

function SlideCard({ mod, lang }: { mod: Module; lang: Lang }) {
  const Icon = mod.icon
  const title = (T[mod.titleKey] as Record<Lang, string>)[lang]

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] overflow-hidden">
      <div className="p-5 pb-4 flex items-center gap-3 border-b border-white/5">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#667eea]/20 to-[#06b6d4]/20 flex items-center justify-center flex-shrink-0">
          <Icon className="w-5 h-5 text-cyan-400" />
        </div>
        <h2 className="text-lg font-bold text-white">{title}</h2>
      </div>

      <div className="p-5">
        {mod.type === 'steps' && <StepsContent steps={(T[`${mod.key}_steps` as keyof typeof T] as unknown as Record<Lang, readonly [string, string][]>)[lang]} lang={lang} />}
        {mod.type === 'rules' && <RulesContent moduleKey={mod.key} lang={lang} />}
        {mod.type === 'gear' && <GearContent lang={lang} />}
        {mod.type === 'pay' && <PayContent lang={lang} />}
        {mod.type === 'contacts' && <ContactsContent lang={lang} />}
      </div>
    </div>
  )
}

/* ─── Module 1: Steps content ────────────────────────────────────────── */

function StepsContent({ steps, lang }: { steps: readonly (readonly [string, string])[]; lang: Lang }) {
  const screenshotText = T.m1_screenshotPlaceholder[lang]
  const screenshotAfter = new Set([0, 3, 5])

  return (
    <div className="space-y-3 max-h-[55vh] overflow-y-auto pr-1">
      {steps.map((step, i) => (
        <div key={i}>
          <motion.div
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.06 }}
            className="flex gap-3 items-start"
          >
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#667eea] to-[#06b6d4] flex items-center justify-center flex-shrink-0 mt-0.5">
              <span className="text-white text-xs font-bold">{i + 1}</span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-white font-semibold text-sm">{step[0]}</p>
              <p className="text-white/60 text-[13px] leading-relaxed mt-0.5">{step[1]}</p>
            </div>
          </motion.div>
          {screenshotAfter.has(i) && <PhoneMockup text={screenshotText} />}
        </div>
      ))}
    </div>
  )
}

/* ─── Module 2 & 3: Rules content ────────────────────────────────────── */

function RulesContent({ moduleKey, lang }: { moduleKey: string; lang: Lang }) {
  if (moduleKey === 'm2') return <PickupRules lang={lang} />
  return <RoadRules lang={lang} />
}

function PickupRules({ lang }: { lang: Lang }) {
  const neverLabel = T.m2_never_label[lang]
  const alwaysLabel = T.m2_always_label[lang]
  const neverItems = T.m2_never[lang]
  const alwaysItems = T.m2_always[lang]

  return (
    <div className="space-y-5 max-h-[55vh] overflow-y-auto pr-1">
      <div>
        <h3 className="text-red-400 text-xs font-bold uppercase tracking-wider mb-3">{neverLabel}</h3>
        <div className="space-y-2">
          {neverItems.map((item, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}
              className="flex gap-2.5 items-start p-3 rounded-xl bg-red-500/[0.08] border border-red-500/15"
            >
              <X className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
              <span className="text-white/80 text-[13px] leading-relaxed">{item}</span>
            </motion.div>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-emerald-400 text-xs font-bold uppercase tracking-wider mb-3">{alwaysLabel}</h3>
        <div className="space-y-2">
          {alwaysItems.map((item, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: (i + 4) * 0.06 }}
              className="flex gap-2.5 items-start p-3 rounded-xl bg-emerald-500/[0.08] border border-emerald-500/15"
            >
              <Check className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
              <span className="text-white/80 text-[13px] leading-relaxed">{item}</span>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  )
}

function RoadRules({ lang }: { lang: Lang }) {
  const neverLabel = T.m3_never_label[lang]
  const neverItems = T.m3_never[lang]
  const specialLabel = T.m3_special_label[lang]
  const specialText = T.m3_special[lang]
  const proLabel = T.m3_pro_label[lang]
  const proItems = T.m3_pro[lang]

  return (
    <div className="space-y-5 max-h-[55vh] overflow-y-auto pr-1">
      <div>
        <h3 className="text-red-400 text-xs font-bold uppercase tracking-wider mb-3">{neverLabel}</h3>
        <div className="space-y-2">
          {neverItems.map((item, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}
              className="flex gap-2.5 items-start p-3 rounded-xl bg-red-500/[0.08] border border-red-500/15"
            >
              <X className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
              <span className="text-white/80 text-[13px] leading-relaxed">{item}</span>
            </motion.div>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-amber-400 text-xs font-bold uppercase tracking-wider mb-3">{specialLabel}</h3>
        <div className="p-3 rounded-xl bg-amber-500/[0.08] border border-amber-500/15">
          <p className="text-white/80 text-[13px] leading-relaxed">{specialText}</p>
        </div>
      </div>

      <div>
        <h3 className="text-amber-400 text-xs font-bold uppercase tracking-wider mb-3">{proLabel}</h3>
        <div className="space-y-2">
          {proItems.map((item, i) => (
            <div
              key={i}
              className="flex gap-2.5 items-start p-3 rounded-xl bg-amber-500/[0.06] border border-amber-500/10"
            >
              <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
              <span className="text-white/80 text-[13px] leading-relaxed">{item}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ─── Module 4: Gear content ─────────────────────────────────────────── */

function GearContent({ lang }: { lang: Lang }) {
  const vestTitle = T.m4_vest_title[lang]
  const vestRequired = T.m4_vest_required[lang]
  const vestWhy = T.m4_vest_why[lang]
  const vestRule = T.m4_vest_rule[lang]
  const vestPhoto = T.m4_photo_vest[lang]

  const plaqueTitle = T.m4_plaque_title[lang]
  const plaqueRequired = T.m4_plaque_required[lang]
  const plaqueWhy = T.m4_plaque_why[lang]
  const plaqueHow = T.m4_plaque_how[lang]
  const plaqueRule = T.m4_plaque_rule[lang]
  const plaquePhoto = T.m4_photo_plaque[lang]

  return (
    <div className="space-y-4 max-h-[55vh] overflow-y-auto pr-1">
      {/* Vest */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="rounded-xl border border-white/10 bg-white/[0.03] p-4 space-y-3"
      >
        <div className="flex items-center gap-3">
          <span className="text-3xl">{'\u{1F9BA}'}</span>
          <div>
            <h3 className="text-white font-bold text-sm">{vestTitle}</h3>
            <span className="inline-block mt-1 px-2 py-0.5 rounded-md bg-red-500/20 text-red-400 text-[10px] font-bold uppercase">Required</span>
          </div>
        </div>
        <p className="text-white/70 text-[13px] leading-relaxed">{vestRequired}</p>
        <p className="text-white/50 text-[12px] leading-relaxed">{vestWhy}</p>
        <div className="flex gap-2 items-start p-2.5 rounded-lg bg-red-500/[0.08] border border-red-500/15">
          <AlertCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0 mt-0.5" />
          <span className="text-red-300/90 text-[12px] leading-relaxed">{vestRule}</span>
        </div>
        <div className="rounded-lg border border-dashed border-white/10 bg-white/[0.02] flex items-center justify-center py-6 px-3">
          <span className="text-white/25 text-[11px] text-center">{vestPhoto}</span>
        </div>
      </motion.div>

      {/* Plaque */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="rounded-xl border border-white/10 bg-white/[0.03] p-4 space-y-3"
      >
        <div className="flex items-center gap-3">
          <span className="text-3xl">{'\u{1FAAA}'}</span>
          <div>
            <h3 className="text-white font-bold text-sm">{plaqueTitle}</h3>
            <span className="inline-block mt-1 px-2 py-0.5 rounded-md bg-red-500/20 text-red-400 text-[10px] font-bold uppercase">Required</span>
          </div>
        </div>
        <p className="text-white/70 text-[13px] leading-relaxed">{plaqueRequired}</p>
        <p className="text-white/50 text-[12px] leading-relaxed">{plaqueWhy}</p>
        <p className="text-white/50 text-[12px] leading-relaxed">{plaqueHow}</p>
        <div className="flex gap-2 items-start p-2.5 rounded-lg bg-red-500/[0.08] border border-red-500/15">
          <AlertCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0 mt-0.5" />
          <span className="text-red-300/90 text-[12px] leading-relaxed">{plaqueRule}</span>
        </div>
        <div className="rounded-lg border border-dashed border-white/10 bg-white/[0.02] flex items-center justify-center py-6 px-3">
          <span className="text-white/25 text-[11px] text-center">{plaquePhoto}</span>
        </div>
      </motion.div>
    </div>
  )
}

/* ─── Module 5: Pay content ──────────────────────────────────────────── */

function PayContent({ lang }: { lang: Lang }) {
  const header = T.m5_header[lang]
  const items = T.m5_items[lang]
  const exLabel = T.m5_example_label[lang]
  const example = T.m5_example[lang]
  const timeline = T.m5_timeline[lang]
  const payQ = T.m5_pay_questions[lang]
  const payMissing = T.m5_pay_missing[lang]

  return (
    <div className="space-y-5 max-h-[55vh] overflow-y-auto pr-1">
      <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
        <AlertCircle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
        <p className="text-amber-300/90 text-sm font-medium leading-relaxed">{header}</p>
      </div>

      <ul className="space-y-3">
        {items.map((item, i) => (
          <motion.li
            key={i}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.08 }}
            className="flex gap-3 items-start"
          >
            <span className={`
              w-6 h-6 rounded-full text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5
              ${i < 2 ? 'bg-amber-500/20 text-amber-400' : 'bg-white/10 text-white/50'}
            `}>
              {i + 1}
            </span>
            <span className={`text-sm leading-relaxed ${i < 2 ? 'text-white font-semibold' : 'text-white/70'}`}>
              {item}
            </span>
          </motion.li>
        ))}
      </ul>

      {/* Visual timeline */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="p-4 rounded-xl bg-white/[0.04] border border-white/10"
      >
        <div className="flex items-center justify-between mb-4">
          {[0, 2, 4].map((idx, nodeIdx) => (
            <div key={idx} className="flex flex-col items-center gap-2 flex-1">
              <div className={`
                w-12 h-12 rounded-full flex items-center justify-center text-lg
                ${nodeIdx === 0 ? 'bg-[#667eea]/20 border-2 border-[#667eea]/40' : ''}
                ${nodeIdx === 1 ? 'bg-amber-500/20 border-2 border-amber-500/40' : ''}
                ${nodeIdx === 2 ? 'bg-emerald-500/20 border-2 border-emerald-500/40' : ''}
              `}>
                {nodeIdx === 0 ? '\u{1F697}' : nodeIdx === 1 ? '\u23F3' : '\u{1F4B0}'}
              </div>
              <span className={`text-xs font-bold text-center ${
                nodeIdx === 0 ? 'text-[#667eea]' : nodeIdx === 1 ? 'text-amber-400' : 'text-emerald-400'
              }`}>
                {timeline[idx]}
              </span>
              <span className="text-[11px] text-white/40 text-center leading-tight">
                {timeline[idx + 1]}
              </span>
            </div>
          ))}
        </div>

        <div className="relative h-2 rounded-full bg-white/5 mx-6 mb-3">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: '100%' }}
            transition={{ delay: 0.5, duration: 1.2, ease: 'easeOut' }}
            className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-[#667eea] via-amber-500 to-emerald-500"
          />
        </div>

        <div className="mt-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/15">
          <p className="text-emerald-400 text-xs font-bold uppercase tracking-wider mb-1">{exLabel}</p>
          <p className="text-white/80 text-sm leading-relaxed">{example}</p>
        </div>
      </motion.div>

      {/* Pay questions & missing pay */}
      <div className="space-y-2">
        <div className="flex gap-2 items-start p-3 rounded-xl bg-amber-500/[0.06] border border-amber-500/10">
          <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
          <span className="text-white/70 text-[13px] leading-relaxed">{payQ}</span>
        </div>
        <div className="flex gap-2 items-start p-3 rounded-xl bg-white/[0.04] border border-white/10">
          <AlertCircle className="w-4 h-4 text-white/40 flex-shrink-0 mt-0.5" />
          <span className="text-white/50 text-[13px] leading-relaxed">{payMissing}</span>
        </div>
      </div>
    </div>
  )
}

/* ─── Module 6: Contacts content ─────────────────────────────────────── */

function ContactsContent({ lang }: { lang: Lang }) {
  const dispatchTitle = T.m6_dispatch_title[lang]
  const dispatchSub = T.m6_dispatch_sub[lang]
  const dispatchItems = T.m6_dispatch_items[lang]

  const officeTitle = T.m6_office_title[lang]
  const officeItems = T.m6_office_items[lang]

  const emergencyTitle = T.m6_emergency_title[lang]
  const emergencyItems = T.m6_emergency_items[lang]

  return (
    <div className="space-y-3 max-h-[55vh] overflow-y-auto pr-1">
      {/* Dispatch */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        className="rounded-xl border-l-4 border-l-emerald-500 border border-emerald-500/15 bg-emerald-500/[0.06] p-3.5"
      >
        <div className="flex items-center gap-2 mb-2">
          <Phone className="w-4 h-4 text-emerald-400" />
          <h3 className="text-emerald-400 font-bold text-[13px]">{dispatchTitle}</h3>
        </div>
        <p className="text-emerald-300/80 text-[12px] font-medium mb-2">{dispatchSub}</p>
        <ul className="space-y-1.5">
          {dispatchItems.map((item, i) => (
            <li key={i} className="text-white/60 text-[12px] leading-relaxed flex gap-2 items-start">
              <span className="text-emerald-400/60 mt-px">&bull;</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </motion.div>

      {/* Acumen */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.08 }}
        className="rounded-xl border-l-4 border-l-indigo-500 border border-indigo-500/15 bg-indigo-500/[0.06] p-3.5"
      >
        <div className="flex items-center gap-2 mb-2">
          <Phone className="w-4 h-4 text-indigo-400" />
          <h3 className="text-indigo-400 font-bold text-[13px]">{officeTitle}</h3>
        </div>
        <ul className="space-y-1.5">
          {officeItems.map((item, i) => (
            <li key={i} className="text-white/60 text-[12px] leading-relaxed flex gap-2 items-start">
              <span className="text-indigo-400/60 mt-px">&bull;</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </motion.div>

      {/* Emergency */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.16 }}
        className="rounded-xl border-l-4 border-l-red-500 border border-red-500/15 bg-red-500/[0.06] p-3.5"
      >
        <div className="flex items-center gap-2 mb-2">
          <AlertCircle className="w-4 h-4 text-red-400" />
          <h3 className="text-red-400 font-bold text-[13px]">{emergencyTitle}</h3>
        </div>
        <ul className="space-y-1.5">
          {emergencyItems.map((item, i) => (
            <li key={i} className="text-white/60 text-[12px] leading-relaxed flex gap-2 items-start">
              <span className="text-red-400/60 mt-px">&bull;</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </motion.div>

    </div>
  )
}
