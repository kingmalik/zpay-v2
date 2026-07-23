'use client'

import React, { use, useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence, PanInfo } from 'framer-motion'
import {
  ChevronRight,
  ChevronLeft,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Check,
  Info,
  ListChecks,
  Camera,
  Users,
  AlertTriangle,
  FileText,
} from 'lucide-react'

/* ─── Types ──────────────────────────────────────────────────────────── */

type Lang = 'en' | 'ar' | 'am'
type Screen = 'welcome' | 'slides' | 'quiz' | 'sign' | 'complete'
type TriLang = Record<Lang, string>

interface OnboardingRecord {
  person_name?: string
  person_language?: string
  maz_training_status?: string
  [key: string]: unknown
}

interface ModuleBlock {
  lead: TriLang | null
  text: TriLang
}

interface CourseModuleData {
  key: string
  title: TriLang
  intro: TriLang | null
  blocks: ModuleBlock[]
}

interface QuizQuestionData {
  question: TriLang
  options: TriLang[]
  correct: number
}

interface CourseContent {
  course_version: string
  pass_threshold_ratio: number
  modules: CourseModuleData[]
  quiz: QuizQuestionData[]
}

interface QuizResult {
  score: number
  total: number
  passed: boolean
  threshold: number
}

/* ─── Module icons (positional — 6 binder modules, in order) ─────────── */

const MODULE_ICONS = [Info, ListChecks, Camera, Users, AlertTriangle, FileText]

/* ─── Chrome translations (UI strings only — module/quiz content comes
       from the backend certification service, single source of truth) ── */

const T = {
  welcome: {
    en: 'Driver Certification',
    ar: 'شهادة السائق',
    am: 'የሾፌር ማረጋገጫ',
  },
  welcomeSub: {
    en: 'Maz Services — Driver Rules Course',
    ar: 'خدمات ماز — دورة قواعد السائقين',
    am: 'ማዝ ሰርቪስስ — የሾፌር ደንቦች ኮርስ',
  },
  welcomeBody: {
    en: 'Complete 6 short modules and a 10-question quiz (pass = 8 of 10) to get certified. No first ride happens until you pass.',
    ar: 'أكمل 6 وحدات قصيرة واختباراً من 10 أسئلة (النجاح = 8 من 10) لتحصل على الشهادة. لن تبدأ أول رحلة لك حتى تنجح.',
    am: 'ለመመስከር 6 አጭር ሞጁሎችን እና የ10 ጥያቄ ፈተና (ማለፊያ = ከ10 8) ያጠናቅቁ። እስኪያልፉ ድረስ የመጀመሪያ ጉዞ የለም።',
  },
  startTraining: { en: 'Start Course', ar: 'ابدأ الدورة', am: 'ኮርስ ጀምር' },
  next: { en: 'Next', ar: 'التالي', am: 'ቀጣይ' },
  back: { en: 'Back', ar: 'السابق', am: 'ተመለስ' },
  startQuiz: { en: 'Start Quiz', ar: 'ابدأ الاختبار', am: 'ፈተና ጀምር' },
  moduleOf: {
    en: (c: number, total: number) => `Module ${c} of ${total}`,
    ar: (c: number, total: number) => `الوحدة ${c} من ${total}`,
    am: (c: number, total: number) => `ሞጁል ${c} ከ ${total}`,
  },
  loading: { en: 'Loading course...', ar: 'جاري تحميل الدورة...', am: 'ኮርስ በመጫን ላይ...' },
  selectLang: { en: 'Choose your language', ar: 'اختر لغتك', am: 'ቋንቋዎን ይምረጡ' },
  notFound: {
    en: 'Invalid or expired training link.',
    ar: 'رابط التدريب غير صالح أو منتهي الصلاحية.',
    am: 'ልክ ያልሆነ ወይም ጊዜው ያለፈበት የሥልጠና ሊንክ።',
  },
  error: {
    en: 'Something went wrong. Please try again.',
    ar: 'حدث خطأ. يرجى المحاولة مرة أخرى.',
    am: 'ስህተት ተፈጥሯል። እባክዎ እንደገና ይሞክሩ።',
  },

  /* Quiz */
  quizTitle: { en: 'Knowledge Check', ar: 'اختبار المعرفة', am: 'የእውቀት ፍተሻ' },
  quizSubtitle: {
    en: 'Answer all 10 questions. You need 8 correct to pass.',
    ar: 'أجب على جميع الأسئلة العشرة. تحتاج إلى 8 إجابات صحيحة للنجاح.',
    am: 'ሁሉንም 10 ጥያቄዎች ይመልሱ። ለማለፍ 8 ትክክለኛ ያስፈልጋሉ።',
  },
  quizSubmit: { en: 'Submit Quiz', ar: 'إرسال الاختبار', am: 'ፈተና ያስገቡ' },
  quizUnanswered: {
    en: 'Please answer all questions before submitting.',
    ar: 'يرجى الإجابة على جميع الأسئلة قبل الإرسال.',
    am: 'ከማስገባትዎ በፊት ሁሉንም ጥያቄዎች ይመልሱ።',
  },
  quizPassTitle: { en: 'You passed!', ar: 'لقد نجحت!', am: 'አልፈዋል!' },
  quizPassSub: {
    en: 'Great work. Continue to sign off and finish your certification.',
    ar: 'عمل رائع. تابع للتوقيع وإنهاء شهادتك.',
    am: 'በጣም ጥሩ ስራ። ለመፈረም እና ማረጋገጫዎን ለማጠናቀቅ ይቀጥሉ።',
  },
  quizFailTitle: {
    en: "Not yet — let's review",
    ar: 'ليس بعد — لنراجع',
    am: 'ገና አይደለም — እንከልስ',
  },
  quizFailSub: {
    en: 'You need 8 of 10 to pass. Re-read the modules, then try the quiz again — as many times as you need.',
    ar: 'تحتاج إلى 8 من 10 للنجاح. أعد قراءة الوحدات، ثم حاول الاختبار مرة أخرى — بقدر ما تحتاج.',
    am: 'ለማለፍ ከ10 8 ያስፈልግዎታል። ሞጁሎችን እንደገና ያንብቡ፣ ከዚያ ፈተናውን እንደገና ይሞክሩ — እስከሚያስፈልግዎት ድረስ።',
  },
  scoreLabel: {
    en: (score: number, total: number) => `Your score: ${score} of ${total}`,
    ar: (score: number, total: number) => `درجتك: ${score} من ${total}`,
    am: (score: number, total: number) => `ውጤትዎ: ${score} ከ ${total}`,
  },
  reReadModules: { en: 'Re-read Modules', ar: 'إعادة قراءة الوحدات', am: 'ሞጁሎችን እንደገና ያንብቡ' },
  continueToSign: { en: 'Continue to Sign-off', ar: 'المتابعة للتوقيع', am: 'ወደ ፊርማ ይቀጥሉ' },

  /* Sign-off */
  signTitle: { en: 'Sign & Certify', ar: 'التوقيع والتصديق', am: 'ይፈርሙ እና ያረጋግጡ' },
  signCheck: {
    en: 'I have read and understood the rules. I understand no first ride happens until I pass, and that app verification is what makes my pay safe.',
    ar: 'لقد قرأت وفهمت القواعد. أفهم أنه لن تحدث أول رحلة لي حتى أنجح، وأن التحقق عبر التطبيق هو ما يحمي أجري.',
    am: 'ደንቦቹን አንብቤ ተረድቻለሁ። እስካልፍ ድረስ የመጀመሪያ ጉዞ እንደሌለኝ፣ እና የመተግበሪያ ማረጋገጫ ክፍያዬን ደህንነት እንደሚጠብቅ ተረድቻለሁ።',
  },
  signNameLabel: {
    en: 'Type your full name to sign',
    ar: 'اكتب اسمك الكامل للتوقيع',
    am: 'ለመፈረም ሙሉ ስምዎን ይጻፉ',
  },
  signSubmit: { en: 'Complete Certification', ar: 'إكمال الشهادة', am: 'ማረጋገጫ ጨርስ' },
  signSubmitting: { en: 'Submitting...', ar: 'جاري التقديم...', am: 'በማስገባት ላይ...' },

  /* Complete */
  done: { en: "You're certified!", ar: 'أنت معتمد الآن!', am: 'ተመስክሮልዎታል!' },
  doneBody: {
    en: 'Your certification is complete. Your dispatcher will contact you with your first route assignment.',
    ar: 'اكتملت شهادتك. سيتصل بك المرسل بأول مهمة طريق.',
    am: 'ማረጋገጫዎ ተጠናቋል። መላኪያዎ በመጀመሪያ የመንገድ ምደባ ያገኝዎታል።',
  },
} as const

/* ─── Audio slot — renders only if the file actually exists ──────────── */

function AudioSlot({ lang, moduleKey }: { lang: Lang; moduleKey: string }) {
  const [available, setAvailable] = useState(false)
  const src = `/audio/certification/${lang}/${moduleKey}.mp3`

  useEffect(() => {
    let cancelled = false
    fetch(src, { method: 'HEAD' })
      .then((res) => { if (!cancelled) setAvailable(res.ok) })
      .catch(() => { if (!cancelled) setAvailable(false) })
    return () => { cancelled = true }
  }, [src])

  if (!available) return null
  // eslint-disable-next-line jsx-a11y/media-has-caption
  return <audio controls src={src} className="w-full mt-3 rounded-lg" />
}

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
  const [moduleIdx, setModuleIdx] = useState(0)
  const [direction, setDirection] = useState(1)

  const [record, setRecord] = useState<OnboardingRecord | null>(null)
  const [course, setCourse] = useState<CourseContent | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [quizAnswers, setQuizAnswers] = useState<Record<number, number>>({})
  const [quizResult, setQuizResult] = useState<QuizResult | null>(null)

  const [signChecked, setSignChecked] = useState(false)
  const [signName, setSignName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(false)

  const isRtl = lang === 'ar'

  /* ── Fetch onboarding record + course content ── */
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [recRes, courseRes] = await Promise.all([
          fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/join/${token}`),
          fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/join/${token}/certification`),
        ])
        if (!recRes.ok || !courseRes.ok) throw new Error('failed')
        const recData: OnboardingRecord = await recRes.json()
        const courseData: CourseContent = await courseRes.json()
        if (cancelled) return
        setRecord(recData)
        setCourse(courseData)
        if (recData.person_language === 'ar') setLang('ar')
        else if (recData.person_language === 'am') setLang('am')
        if (recData.maz_training_status === 'complete') setScreen('complete')
      } catch {
        if (!cancelled) setError('not_found')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [token])

  const totalModules = course?.modules.length ?? 0

  /* ── Module navigation ── */
  const goNext = useCallback(() => {
    if (moduleIdx < totalModules - 1) {
      setDirection(1)
      setModuleIdx((i) => i + 1)
    } else {
      setScreen('quiz')
    }
  }, [moduleIdx, totalModules])

  const goBack = useCallback(() => {
    if (moduleIdx > 0) {
      setDirection(-1)
      setModuleIdx((i) => i - 1)
    } else {
      setScreen('welcome')
    }
  }, [moduleIdx])

  const handleDragEnd = useCallback(
    (_: unknown, info: PanInfo) => {
      const threshold = 50
      if (info.offset.x < -threshold) goNext()
      else if (info.offset.x > threshold) goBack()
    },
    [goNext, goBack]
  )

  /* ── Quiz submit ── */
  const handleQuizSubmit = () => {
    if (!course) return
    if (Object.keys(quizAnswers).length < course.quiz.length) return
    const total = course.quiz.length
    const score = course.quiz.filter((q, i) => quizAnswers[i] === q.correct).length
    const threshold = Math.ceil(total * course.pass_threshold_ratio)
    setQuizResult({ score, total, passed: score >= threshold, threshold })
  }

  const handleRetry = () => {
    setQuizAnswers({})
    setQuizResult(null)
    setModuleIdx(0)
    setScreen('slides')
  }

  /* ── Final submit (quiz + sign-off) ── */
  const handleSignSubmit = async () => {
    if (!signChecked || !signName.trim() || !quizResult || !course || submitting) return
    setSubmitting(true)
    setSubmitError(false)
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/join/${token}/step`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          step: 'maz_training',
          acknowledged: true,
          name: signName.trim(),
          quiz_score: quizResult.score,
          quiz_total: quizResult.total,
          course_version: course.course_version,
          signed_name: signName.trim(),
        }),
      })
      if (!res.ok) throw new Error('submit_failed')
      setScreen('complete')
    } catch {
      setSubmitError(true)
    } finally {
      setSubmitting(false)
    }
  }

  /* ── Loading / error states ── */
  if (loading) {
    return (
      <Shell lang={lang}>
        <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-cyan-400" />
          <p className="text-white/60 text-sm">{T.loading[lang]}</p>
        </div>
      </Shell>
    )
  }

  if (error === 'not_found' || !course) {
    return (
      <Shell lang={lang}>
        <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 px-4">
          <AlertCircle className="w-10 h-10 text-red-400" />
          <p className="text-white/60 text-sm text-center">{T.notFound[lang]}</p>
        </div>
      </Shell>
    )
  }

  /* ── Complete screen ── */
  if (screen === 'complete') {
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
          <h1 className="text-2xl font-bold text-white">{T.done[lang]}</h1>
          <p className="text-white/60 text-sm leading-relaxed max-w-xs">{T.doneBody[lang]}</p>
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
            <h1 className="text-2xl font-bold text-white">{T.welcome[lang]}</h1>
            <p className="text-cyan-400 text-sm font-medium">{T.welcomeSub[lang]}</p>
          </div>

          <p className="text-white/50 text-sm text-center leading-relaxed max-w-xs">
            {T.welcomeBody[lang]}
          </p>

          <div className="space-y-3 w-full max-w-xs">
            <p className="text-white/40 text-xs text-center uppercase tracking-wider">
              {T.selectLang[lang]}
            </p>
            <div className="flex gap-2 justify-center">
              {([
                ['en', 'English', '\u{1F1FA}\u{1F1F8}'],
                ['ar', 'العربية', '\u{1F1F8}\u{1F1E6}'],
                ['am', 'አማርኛ', '\u{1F1EA}\u{1F1F9}'],
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
            onClick={() => { setScreen('slides'); setModuleIdx(0) }}
            className="
              w-full max-w-xs min-h-[48px] rounded-xl font-semibold text-white text-base
              bg-gradient-to-r from-[#667eea] to-[#06b6d4]
              hover:shadow-lg hover:shadow-cyan-500/25
              active:scale-[0.98] transition-all duration-200
              flex items-center justify-center gap-2
            "
          >
            {T.startTraining[lang]}
            <ChevronRight className="w-5 h-5" />
          </button>

          {record?.person_name && (
            <p className="text-white/30 text-xs">{record.person_name}</p>
          )}
        </motion.div>
      </Shell>
    )
  }

  /* ── Module slides screen ── */
  if (screen === 'slides') {
    const mod = course.modules[moduleIdx]
    const Icon = MODULE_ICONS[moduleIdx % MODULE_ICONS.length]

    return (
      <Shell lang={lang}>
        <div className="flex flex-col min-h-[100dvh] px-4 pb-6 pt-4" dir={isRtl ? 'rtl' : 'ltr'}>
          <div className="mb-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-white/40 text-xs font-medium uppercase tracking-wider">
                {T.moduleOf[lang](moduleIdx + 1, totalModules)}
              </span>
              <div className="flex gap-1">
                {course.modules.map((_, i) => (
                  <div
                    key={i}
                    className={`h-1 rounded-full transition-all duration-300 ${
                      i <= moduleIdx
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
                key={moduleIdx}
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
                <ModuleCard mod={mod} lang={lang} Icon={Icon} />
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
              {T.back[lang]}
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
              {moduleIdx < totalModules - 1 ? T.next[lang] : T.startQuiz[lang]}
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
        questions={course.quiz}
        answers={quizAnswers}
        setAnswers={setQuizAnswers}
        result={quizResult}
        onSubmit={handleQuizSubmit}
        onRetry={handleRetry}
        onContinue={() => setScreen('sign')}
      />
    )
  }

  /* ── Sign-off screen ── */
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

          <h1 className="text-xl font-bold text-white text-center">{T.signTitle[lang]}</h1>

          {quizResult && (
            <p className="text-emerald-400 text-sm font-medium">
              {T.scoreLabel[lang](quizResult.score, quizResult.total)}
            </p>
          )}

          <label className="flex items-start gap-3 p-4 rounded-xl bg-white/5 border border-white/10 cursor-pointer w-full max-w-sm">
            <input
              type="checkbox"
              checked={signChecked}
              onChange={(e) => setSignChecked(e.target.checked)}
              className="mt-0.5 w-5 h-5 rounded accent-cyan-500 flex-shrink-0"
            />
            <span className="text-white/80 text-sm leading-relaxed">{T.signCheck[lang]}</span>
          </label>

          <div className="w-full max-w-sm space-y-2">
            <label className="text-white/40 text-xs uppercase tracking-wider">
              {T.signNameLabel[lang]}
            </label>
            <input
              type="text"
              value={signName}
              onChange={(e) => setSignName(e.target.value)}
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

          {submitError && (
            <p className="text-red-400 text-sm flex items-center gap-2">
              <AlertCircle className="w-4 h-4" />
              {T.error[lang]}
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
            {T.back[lang]}
          </button>
          <button
            onClick={handleSignSubmit}
            disabled={!signChecked || !signName.trim() || submitting}
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
                {T.signSubmitting[lang]}
              </>
            ) : (
              <>
                <CheckCircle2 className="w-4 h-4" />
                {T.signSubmit[lang]}
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
  questions,
  answers,
  setAnswers,
  result,
  onSubmit,
  onRetry,
  onContinue,
}: {
  lang: Lang
  questions: QuizQuestionData[]
  answers: Record<number, number>
  setAnswers: React.Dispatch<React.SetStateAction<Record<number, number>>>
  result: QuizResult | null
  onSubmit: () => void
  onRetry: () => void
  onContinue: () => void
}) {
  const [unansweredError, setUnansweredError] = useState(false)
  const isRtl = lang === 'ar'
  const submitted = result !== null

  const handleSubmit = () => {
    if (Object.keys(answers).length < questions.length) {
      setUnansweredError(true)
      return
    }
    setUnansweredError(false)
    onSubmit()
  }

  return (
    <div className="min-h-screen bg-[#09090b] text-white px-4 py-8 pb-20 max-w-md mx-auto" dir={isRtl ? 'rtl' : 'ltr'}>
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-bold mb-1">{T.quizTitle[lang]}</h1>
        <p className="text-sm text-zinc-500 mb-8">{T.quizSubtitle[lang]}</p>
      </motion.div>

      <div className="space-y-6">
        {questions.map((question, qi) => {
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
                {question.question[lang]}
              </p>
              <div className="space-y-2">
                {question.options.map((opt, oi) => {
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
                      {opt[lang]}
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
              <p className="text-xs text-red-400 mb-3 text-center">{T.quizUnanswered[lang]}</p>
            )}
            <button
              onClick={handleSubmit}
              className="w-full py-3 min-h-[48px] rounded-xl bg-blue-500 hover:bg-blue-400 text-white font-semibold transition-colors"
            >
              {T.quizSubmit[lang]}
            </button>
          </>
        ) : result.passed ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="rounded-2xl bg-emerald-500/10 border border-emerald-500/20 p-6 text-center"
          >
            <p className="text-lg font-bold text-emerald-400 mb-1">{T.quizPassTitle[lang]}</p>
            <p className="text-sm text-zinc-400 mb-1">{T.scoreLabel[lang](result.score, result.total)}</p>
            <p className="text-sm text-zinc-400 mb-4">{T.quizPassSub[lang]}</p>
            <button
              onClick={onContinue}
              className="w-full py-3 min-h-[48px] rounded-xl bg-emerald-500 hover:bg-emerald-400 text-white font-semibold transition-colors"
            >
              {T.continueToSign[lang]}
            </button>
          </motion.div>
        ) : (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="rounded-2xl bg-red-500/10 border border-red-500/20 p-6 text-center"
          >
            <p className="text-lg font-bold text-red-400 mb-1">{T.quizFailTitle[lang]}</p>
            <p className="text-sm text-zinc-400 mb-1">{T.scoreLabel[lang](result.score, result.total)}</p>
            <p className="text-sm text-zinc-400 mb-4">{T.quizFailSub[lang]}</p>
            <button
              onClick={onRetry}
              className="w-full py-3 min-h-[48px] rounded-xl bg-red-500 hover:bg-red-400 text-white font-semibold transition-colors"
            >
              {T.reReadModules[lang]}
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

/* ─── Module card — generic renderer for all 6 modules ───────────────── */

function ModuleCard({
  mod,
  lang,
  Icon,
}: {
  mod: CourseModuleData
  lang: Lang
  Icon: typeof Info
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] overflow-hidden">
      <div className="p-5 pb-4 flex items-center gap-3 border-b border-white/5">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#667eea]/20 to-[#06b6d4]/20 flex items-center justify-center flex-shrink-0">
          <Icon className="w-5 h-5 text-cyan-400" />
        </div>
        <h2 className="text-lg font-bold text-white">{mod.title[lang]}</h2>
      </div>

      <div className="p-5 space-y-3 max-h-[55vh] overflow-y-auto pr-1">
        {mod.intro && (
          <p className="text-white/70 text-sm leading-relaxed">{mod.intro[lang]}</p>
        )}

        {mod.blocks.map((block, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.06 }}
            className={`rounded-xl border p-3.5 flex gap-2.5 items-start ${
              block.lead
                ? 'bg-[#667eea]/[0.06] border-[#667eea]/15'
                : 'bg-white/[0.03] border-white/10'
            }`}
          >
            {block.lead ? (
              <Check className="w-4 h-4 text-cyan-400 flex-shrink-0 mt-0.5" />
            ) : (
              <Info className="w-4 h-4 text-white/30 flex-shrink-0 mt-0.5" />
            )}
            <span className="text-white/80 text-[13px] leading-relaxed">
              {block.lead && (
                <span className="font-semibold text-white block mb-0.5">{block.lead[lang]}</span>
              )}
              {block.text[lang]}
            </span>
          </motion.div>
        ))}

        <AudioSlot lang={lang} moduleKey={mod.key} />
      </div>
    </div>
  )
}
