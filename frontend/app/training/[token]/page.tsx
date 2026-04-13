'use client'

import { use, useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence, PanInfo } from 'framer-motion'
import {
  Smartphone,
  ShieldCheck,
  ShirtIcon,
  BadgeDollarSign,
  UserCheck,
  ChevronRight,
  ChevronLeft,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Globe,
} from 'lucide-react'
import { api } from '@/lib/api'

/* ─── Types ──────────────────────────────────────────────────────────── */

type Lang = 'en' | 'ar' | 'am'
type Screen = 'welcome' | 'slides' | 'complete'

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
    en: 'Complete these 5 short training modules to learn everything you need to know before your first ride. Takes about 5 minutes.',
    ar: 'أكمل هذه الوحدات التدريبية الخمس القصيرة لتتعلم كل ما تحتاج معرفته قبل أول رحلة لك. يستغرق حوالي 5 دقائق.',
    am: 'ከመጀመሪያ ጉዞዎ በፊት ማወቅ ያለብዎትን ሁሉ ለመማር እነዚህን 5 አጫጭር የሥልጠና ሞጁሎች ይጨርሱ። ወደ 5 ደቂቃ ይወስዳል።',
  },
  startTraining: {
    en: 'Start Training',
    ar: 'ابدأ التدريب',
    am: 'ሥልጠና ጀምር',
  },
  next: { en: 'Next', ar: 'التالي', am: 'ቀጣይ' },
  back: { en: 'Back', ar: 'السابق', am: 'ተመለስ' },
  moduleOf: {
    en: (c: number, t: number) => `${c} of ${t}`,
    ar: (c: number, t: number) => `${c} من ${t}`,
    am: (c: number, t: number) => `${c} ከ ${t}`,
  },
  ackTitle: {
    en: 'Training Complete',
    ar: 'التدريب مكتمل',
    am: 'ሥልጠና ተጠናቋል',
  },
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
  completeBtn: {
    en: 'Complete Training',
    ar: 'إكمال التدريب',
    am: 'ሥልጠና ጨርስ',
  },
  completing: {
    en: 'Submitting...',
    ar: 'جاري التقديم...',
    am: 'በማስገባት ላይ...',
  },
  done: {
    en: 'You\'re all set!',
    ar: 'أنت جاهز!',
    am: 'ሁሉም ተዘጋጅቷል!',
  },
  doneBody: {
    en: 'Your training is complete. Your dispatcher will contact you with your first route assignment.',
    ar: 'تدريبك مكتمل. سيتصل بك المرسل بأول مهمة.',
    am: 'ሥልጠናዎ ተጠናቋል። መላኪያዎ በመጀመሪያ የመንገድ ምደባ ያገኙዎታል።',
  },
  alreadyDone: {
    en: 'Training already completed',
    ar: 'التدريب مكتمل بالفعل',
    am: 'ሥልጠና ቀድሞውኑ ተጠናቋል',
  },
  error: {
    en: 'Something went wrong. Please try again.',
    ar: 'حدث خطأ. يرجى المحاولة مرة أخرى.',
    am: 'ስህተት ተፈጥሯል። እባክዎ እንደገና ይሞክሩ።',
  },
  loading: {
    en: 'Loading training...',
    ar: 'جاري تحميل التدريب...',
    am: 'ሥልጠና በመጫን ላይ...',
  },
  selectLang: {
    en: 'Choose your language',
    ar: 'اختر لغتك',
    am: 'ቋንቋዎን ይምረጡ',
  },

  /* ── Module titles ── */
  m1_title: {
    en: 'App Basics',
    ar: 'أساسيات التطبيق',
    am: 'የመተግበሪያ መሰረታዊ',
  },
  m2_title: {
    en: 'Transport Rules',
    ar: 'قواعد النقل',
    am: 'የትራንስፖርት ደንቦች',
  },
  m3_title: {
    en: 'Required Items',
    ar: 'المتطلبات',
    am: 'አስፈላጊ ዕቃዎች',
  },
  m4_title: {
    en: 'Pay Structure',
    ar: 'هيكل الدفع',
    am: 'የክፍያ መዋቅር',
  },
  m5_title: {
    en: 'Self-Sufficiency',
    ar: 'الاستقلالية',
    am: 'ራስን መቻል',
  },

  /* ── Module 1 content ── */
  m1_items: {
    en: [
      'Open the FirstAlt app and log in with your driver credentials',
      'When a ride appears, tap "Accept" to take it',
      'When you arrive at pickup, tap "Mark Pickup" so dispatch knows you\'re there',
      'If the student is a no-show, tap "No-Load" — but ONLY after waiting the full 10 minutes',
      'After drop-off, close the ride in the app. Do NOT leave rides open.',
    ],
    ar: [
      'افتح تطبيق FirstAlt وسجّل الدخول ببيانات السائق',
      'عند ظهور رحلة، اضغط "قبول" لأخذها',
      'عند وصولك لنقطة الالتقاء، اضغط "تأكيد الوصول" ليعرف المرسل',
      'إذا لم يحضر الطالب، اضغط "بدون حمولة" — فقط بعد الانتظار 10 دقائق كاملة',
      'بعد التوصيل، أغلق الرحلة في التطبيق. لا تترك الرحلات مفتوحة.',
    ],
    am: [
      'FirstAlt መተግበሪያውን ይክፈቱ እና በሾፌር ማረጋገጫ ይግቡ',
      'ጉዞ ሲታይ "ተቀበል" ን ይጫኑ',
      'ማንሻ ቦታ ሲደርሱ "ማንሻ ምልክት" ን ይጫኑ',
      'ተማሪው ካልመጣ "ባዶ ጉዞ" ን ይጫኑ — ግን 10 ደቂቃ ሙሉ ከጠበቁ በኋላ ብቻ',
      'ካወረዱ በኋላ ጉዞውን በመተግበሪያ ውስጥ ይዝጉ። ጉዞዎችን ክፍት አይተዉ።',
    ],
  },

  /* ── Module 2 content ── */
  m2_items: {
    en: [
      'Safety first — always be patient and professional with students',
      'Never use your phone while driving with students in the car',
      'Do NOT play loud music or have inappropriate content on',
      'Wait time: you MUST wait 10 minutes before marking a no-load',
      'First-time pickup at a new address? Call dispatch so they can notify the guardian that you\'re outside waiting',
      'Never let anyone other than the assigned student into your vehicle',
    ],
    ar: [
      'السلامة أولاً — كن دائماً صبوراً ومحترفاً مع الطلاب',
      'لا تستخدم هاتفك أثناء القيادة مع الطلاب',
      'لا تشغّل موسيقى عالية أو محتوى غير مناسب',
      'يجب الانتظار 10 دقائق كاملة قبل تسجيل "بدون حمولة"',
      'أول مرة تذهب لعنوان جديد؟ اتصل بالمرسل ليخبر ولي الأمر أنك تنتظر',
      'لا تسمح لأي شخص غير الطالب المخصص بركوب سيارتك',
    ],
    am: [
      'ደህንነት ቅድሚያ — ሁልጊዜ ከተማሪዎች ጋር ታጋሽ እና ሙያዊ ይሁኑ',
      'ተማሪዎች በመኪናው ውስጥ ሳሉ ስልክዎን አይጠቀሙ',
      'ጮኸ ሙዚቃ ወይም ተገቢ ያልሆነ ይዘት አያጫውቱ',
      'ባዶ ጉዞ ከማስመዝገብዎ በፊት 10 ደቂቃ ሙሉ መጠበቅ አለብዎት',
      'በአዲስ አድራሻ ለመጀመሪያ ጊዜ? ተጓዳኙን ለማሳወቅ ወደ መላኪያ ይደውሉ',
      'ከተመደበው ተማሪ ውጪ ማንንም ወደ መኪናዎ አይፍቀዱ',
    ],
  },

  /* ── Module 3 content ── */
  m3_items: {
    en: [
      'Wear your SAFETY VEST at ALL times during pickups and drop-offs — this is mandatory, no exceptions',
      'Display the Acumen PLAQUE on your car dashboard at all times — it must be visible from outside',
    ],
    ar: [
      'ارتدِ سترة السلامة في جميع الأوقات أثناء الالتقاء والتوصيل — هذا إلزامي بدون استثناءات',
      'ضع لوحة أكيومن على لوحة القيادة في جميع الأوقات — يجب أن تكون مرئية من الخارج',
    ],
    am: [
      'ማንሻ እና ማውረድ ጊዜ ሁሉ የደህንነት ቀሚስ ይልበሱ — ይህ ግዴታ ነው ምንም ልዩ ሁኔታ የለም',
      'የአኩመን ሰሌዳ ሁልጊዜ በመኪናዎ ዳሽቦርድ ላይ ያሳዩ — ከውጭ መታየት አለበት',
    ],
  },

  /* ── Module 4 content ── */
  m4_header: {
    en: 'This is the #1 thing new drivers ask about. Read carefully.',
    ar: 'هذا هو السؤال الأول الذي يسأله السائقون الجدد. اقرأ بعناية.',
    am: 'ይህ አዳዲስ ሾፌሮች ስለሚጠይቁት ቁጥር 1 ነገር ነው። በጥንቃቄ ያንብቡ።',
  },
  m4_items: {
    en: [
      'You are paid WEEKLY',
      'Your pay is 2 WEEKS behind your work',
      'Why? First Alt pays Acumen once a week. Then Acumen needs one week to process all driver payments.',
      'That means your first paycheck comes 2 weeks after your first ride.',
    ],
    ar: [
      'يتم الدفع لك أسبوعياً',
      'راتبك متأخر أسبوعين عن عملك',
      'لماذا؟ First Alt يدفع لأكيومن مرة في الأسبوع. ثم أكيومن يحتاج أسبوع لمعالجة مدفوعات السائقين.',
      'يعني ذلك أن أول راتب لك يأتي بعد أسبوعين من أول رحلة.',
    ],
    am: [
      'በሳምንት ይከፈልዎታል',
      'ክፍያዎ ከሥራዎ 2 ሳምንት ወደ ኋላ ነው',
      'ለምን? First Alt አኩመንን በሳምንት አንድ ጊዜ ይከፍላል። ከዚያ አኩመን የሾፌሮችን ክፍያ ለማስፈጸም አንድ ሳምንት ያስፈልገዋል።',
      'ይህ ማለት የመጀመሪያ ደመወዝዎ ከመጀመሪያ ጉዞዎ 2 ሳምንት በኋላ ይመጣል ማለት ነው።',
    ],
  },
  m4_example_label: {
    en: 'Example',
    ar: 'مثال',
    am: 'ምሳሌ',
  },
  m4_example: {
    en: 'Start driving Monday Jan 1st → First paycheck Friday Jan 17th',
    ar: 'تبدأ القيادة الاثنين 1 يناير ← أول راتب الجمعة 17 يناير',
    am: 'ሰኞ ጥር 1 ማሽከርከር ይጀምሩ → የመጀመሪያ ደመወዝ አርብ ጥር 17',
  },
  m4_timeline: {
    en: ['Week 1', 'You drive', 'Week 2', 'Acumen processes', 'Week 3', 'You get paid!'],
    ar: ['الأسبوع 1', 'أنت تقود', 'الأسبوع 2', 'أكيومن يعالج', 'الأسبوع 3', 'تحصل على راتبك!'],
    am: ['ሳምንት 1', 'ያሽከረክራሉ', 'ሳምንት 2', 'አኩመን ያስፈጽማል', 'ሳምንት 3', 'ይከፈልዎታል!'],
  },

  /* ── Module 5 content ── */
  m5_items: {
    en: [
      'For ride issues: call dispatch DIRECTLY — they handle everything',
      'Always check the app for route and schedule updates BEFORE calling anyone',
      'Handle minor issues on your own — be an independent professional',
      'Your dispatcher is your primary contact, not the office',
      'The more self-sufficient you are, the more routes you\'ll get',
    ],
    ar: [
      'لمشاكل الرحلات: اتصل بالمرسل مباشرة — هم يتولون كل شيء',
      'تحقق دائماً من التطبيق للتحديثات قبل الاتصال بأي شخص',
      'تعامل مع المشاكل البسيطة بنفسك — كن محترفاً مستقلاً',
      'المرسل هو جهة اتصالك الأساسية، وليس المكتب',
      'كلما كنت أكثر استقلالية، كلما حصلت على مهام أكثر',
    ],
    am: [
      'ለጉዞ ችግሮች: በቀጥታ ወደ መላኪያ ይደውሉ — ሁሉንም ያስተናግዳሉ',
      'ማንንም ከመደወልዎ በፊት ሁልጊዜ መተግበሪያውን ለመንገድ እና የጊዜ ሰሌዳ ዝመናዎች ያረጋግጡ',
      'ትንንሽ ችግሮችን በራስዎ ያስተናግዱ — ገለልተኛ ሙያተኛ ይሁኑ',
      'መላኪያዎ ዋና ግንኙነትዎ ነው፣ ቢሮው አይደለም',
      'ራስዎን በበቂ ሁኔታ ሲችሉ፣ ተጨማሪ መንገዶች ያገኛሉ',
    ],
  },
} as const

/* ─── Module data ────────────────────────────────────────────────────── */

interface Module {
  key: string
  icon: typeof Smartphone
  titleKey: keyof typeof T
  type: 'list' | 'pay'
  contentKey?: keyof typeof T
}

const MODULES: Module[] = [
  { key: 'm1', icon: Smartphone, titleKey: 'm1_title', type: 'list', contentKey: 'm1_items' },
  { key: 'm2', icon: ShieldCheck, titleKey: 'm2_title', type: 'list', contentKey: 'm2_items' },
  { key: 'm3', icon: ShirtIcon, titleKey: 'm3_title', type: 'list', contentKey: 'm3_items' },
  { key: 'm4', icon: BadgeDollarSign, titleKey: 'm4_title', type: 'pay' },
  { key: 'm5', icon: UserCheck, titleKey: 'm5_title', type: 'list', contentKey: 'm5_items' },
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

  const isRtl = lang === 'ar'

  /* ── Fetch onboarding record ── */
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const data = await api.get<OnboardingRecord>(
          `/api/data/onboarding/join/${token}`
        )
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
      setScreen('complete')
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
      await api.post(`/api/data/onboarding/join/${token}/step`, {
        step: 'maz_training',
        acknowledged: true,
        name: ackName.trim(),
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
          {/* Logo area */}
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

          {/* Language selector */}
          <div className="space-y-3 w-full max-w-xs">
            <p className="text-white/40 text-xs text-center uppercase tracking-wider">
              {t('selectLang')}
            </p>
            <div className="flex gap-2 justify-center">
              {([
                ['en', 'English', '🇺🇸'],
                ['ar', 'العربية', '🇸🇦'],
                ['am', 'አማርኛ', '🇪🇹'],
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

          {/* Start button */}
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
            <p className="text-white/30 text-xs">
              {record.person_name}
            </p>
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
          {/* Progress bar */}
          <div className="mb-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-white/40 text-xs font-medium uppercase tracking-wider">
                {(T.moduleOf[lang] as (c: number, t: number) => string)(slideIdx + 1, MODULES.length)}
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

          {/* Slide content */}
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
                <SlideCard
                  mod={mod}
                  lang={lang}
                />
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Navigation buttons */}
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

          {/* Checkbox */}
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

          {/* Name input */}
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

        {/* Buttons */}
        <div className="flex gap-3 mt-8">
          <button
            onClick={() => { setScreen('slides'); setSlideIdx(MODULES.length - 1) }}
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

/* ─── Shell wrapper ──────────────────────────────────────────────────── */

function Shell({ lang, children }: { lang: Lang; children: React.ReactNode }) {
  return (
    <div
      className="min-h-[100dvh] bg-[#09090b]"
      dir={lang === 'ar' ? 'rtl' : 'ltr'}
    >
      <div className="max-w-md mx-auto">
        {children}
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
      {/* Header */}
      <div className="p-5 pb-4 flex items-center gap-3 border-b border-white/5">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#667eea]/20 to-[#06b6d4]/20 flex items-center justify-center flex-shrink-0">
          <Icon className="w-5 h-5 text-cyan-400" />
        </div>
        <h2 className="text-lg font-bold text-white">{title}</h2>
      </div>

      {/* Body */}
      <div className="p-5">
        {mod.type === 'list' && mod.contentKey && (
          <ListContent contentKey={mod.contentKey} lang={lang} />
        )}
        {mod.type === 'pay' && (
          <PayContent lang={lang} />
        )}
      </div>
    </div>
  )
}

/* ─── List content ───────────────────────────────────────────────────── */

function ListContent({ contentKey, lang }: { contentKey: keyof typeof T; lang: Lang }) {
  const items = (T[contentKey] as Record<Lang, readonly string[]>)[lang]

  return (
    <ul className="space-y-3">
      {items.map((item, i) => (
        <motion.li
          key={i}
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * 0.08 }}
          className="flex gap-3 items-start"
        >
          <span className="
            w-6 h-6 rounded-full text-xs font-bold
            bg-gradient-to-br from-[#667eea]/20 to-[#06b6d4]/20
            text-cyan-400 flex items-center justify-center flex-shrink-0 mt-0.5
          ">
            {i + 1}
          </span>
          <span className="text-white/80 text-sm leading-relaxed">{item}</span>
        </motion.li>
      ))}
    </ul>
  )
}

/* ─── Pay structure (Module 4) — the most important slide ────────────── */

function PayContent({ lang }: { lang: Lang }) {
  const header = (T.m4_header as Record<Lang, string>)[lang]
  const items = (T.m4_items as Record<Lang, readonly string[]>)[lang]
  const exLabel = (T.m4_example_label as Record<Lang, string>)[lang]
  const example = (T.m4_example as Record<Lang, string>)[lang]
  const timeline = (T.m4_timeline as Record<Lang, readonly string[]>)[lang]

  return (
    <div className="space-y-5">
      {/* Warning header */}
      <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
        <AlertCircle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
        <p className="text-amber-300/90 text-sm font-medium leading-relaxed">
          {header}
        </p>
      </div>

      {/* Key points */}
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
              ${i < 2
                ? 'bg-amber-500/20 text-amber-400'
                : 'bg-white/10 text-white/50'
              }
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
          {/* 3 week nodes */}
          {[0, 2, 4].map((idx, nodeIdx) => (
            <div key={idx} className="flex flex-col items-center gap-2 flex-1">
              <div className={`
                w-12 h-12 rounded-full flex items-center justify-center text-lg
                ${nodeIdx === 0 ? 'bg-[#667eea]/20 border-2 border-[#667eea]/40' : ''}
                ${nodeIdx === 1 ? 'bg-amber-500/20 border-2 border-amber-500/40' : ''}
                ${nodeIdx === 2 ? 'bg-emerald-500/20 border-2 border-emerald-500/40' : ''}
              `}>
                {nodeIdx === 0 ? '🚗' : nodeIdx === 1 ? '⏳' : '💰'}
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

        {/* Connecting line */}
        <div className="relative h-2 rounded-full bg-white/5 mx-6 mb-3">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: '100%' }}
            transition={{ delay: 0.5, duration: 1.2, ease: 'easeOut' }}
            className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-[#667eea] via-amber-500 to-emerald-500"
          />
        </div>

        {/* Example callout */}
        <div className="mt-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/15">
          <p className="text-emerald-400 text-xs font-bold uppercase tracking-wider mb-1">
            {exLabel}
          </p>
          <p className="text-white/80 text-sm leading-relaxed">
            {example}
          </p>
        </div>
      </motion.div>
    </div>
  )
}
