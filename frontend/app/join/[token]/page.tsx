'use client'

import { use, useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import {
  Smartphone,
  ClipboardList,
  BookOpen,
  FileSignature,
  CheckCircle2,
  Clock,
  Loader2,
  AlertCircle,
  Phone,
  ChevronRight,
  ChevronDown,
  FileText,
  BadgeDollarSign,
  Sparkles,
  ShieldCheck,
} from 'lucide-react'
import IntakeForm from './IntakeForm'
import type { Lang } from './IntakeForm'

/* ─── Types ──────────────────────────────────────────────────────────── */

interface OnboardingData {
  person_name: string | null
  person_phone: string | null
  person_email: string | null
  person_language: string | null
  personal_info: Record<string, unknown> | null
  consent_status: string
  bgc_status: string
  drug_test_status: string
  training_status: string
  files_status: string
  contract_status: string
  paychex_status: string
  maz_training_status: string
  maz_contract_status: string
  firstalt_invite_status?: string
  priority_email_status?: string
  intake_submitted_at?: string | null
  completed_at?: string | null
}

interface DriverStep {
  key: string
  stepNumber: number
  title: Record<Lang, string>
  description: Record<Lang, string>
  hasAction: boolean
  actionLabel?: Record<Lang, string>
  actionUrl?: string
  isWaiting: boolean
  icon: React.ReactNode
}

/* ─── Constants ──────────────────────────────────────────────────────── */

const DISPATCH_PHONE = '(425) 555-0199'
const FIRSTALT_APP_URL = 'https://firstalt.com/app'
const FLAGS: Record<Lang, string> = { en: '🇺🇸', ar: '🇸🇦', am: '🇪🇹' }

/* ─── Step Translations ─────────────────────────────────────────────── */

const S = {
  waiting_team: {
    title: { en: 'Waiting for Team', ar: 'في انتظار الفريق', am: 'ቡድኑን በመጠባበቅ' },
    description: { en: 'Our team is setting up your FirstAlt account. This page updates automatically.', ar: 'فريقنا يقوم بإعداد حسابك في FirstAlt. هذه الصفحة تتحدث تلقائياً.', am: 'ቡድናችን የFirstAlt መለያዎን እያዘጋጀ ነው። ይህ ገጽ በራስ-ሰር ይዘምናል።' },
  },
  download_app: {
    title: { en: 'Download FirstAlt', ar: 'حمّل FirstAlt', am: 'FirstAlt ያውርዱ' },
    description: { en: 'Check your email for the FirstAlt invite. Download the app and complete your profile.', ar: 'تحقق من بريدك الإلكتروني لدعوة FirstAlt. حمّل التطبيق وأكمل ملفك الشخصي.', am: 'ለFirstAlt ግብዣ ኢሜይልዎን ይፈትሹ። መተግበሪያውን ያውርዱ እና መገለጫዎን ያጠናቅቁ።' },
    action: { en: 'Download App', ar: 'حمّل التطبيق', am: 'መተግበሪያ ያውርዱ' },
  },
  bgc_processing: {
    title: { en: 'Background Check', ar: 'فحص الخلفية', am: 'የዳራ ምርመራ' },
    description: { en: 'Your background check is being processed. We\'ll update this page when it\'s done.', ar: 'جاري معالجة فحص الخلفية. سنحدث هذه الصفحة عند الانتهاء.', am: 'የዳራ ምርመራዎ በሂደት ላይ ነው። ሲጠናቀቅ ይህን ገጽ እናዘምናለን።' },
  },
  consent_waiting: {
    title: { en: 'Drug Test Consent', ar: 'موافقة اختبار المخدرات', am: 'የመድኃኒት ምርመራ ስምምነት' },
    description: { en: 'Your consent form is being prepared. Check your email soon.', ar: 'جاري إعداد نموذج الموافقة. تحقق من بريدك قريباً.', am: 'የስምምነት ቅጽዎ እየተዘጋጀ ነው። በቅርቡ ኢሜይልዎን ይፈትሹ።' },
  },
  consent_sign: {
    title: { en: 'Sign Consent Form', ar: 'وقّع نموذج الموافقة', am: 'የስምምነት ቅጽ ይፈርሙ' },
    description: { en: 'Check your email to sign the drug test consent form.', ar: 'تحقق من بريدك لتوقيع نموذج موافقة اختبار المخدرات.', am: 'የመድኃኒት ምርመራ ስምምነት ቅጽ ለመፈረም ኢሜይልዎን ይፈትሹ።' },
  },
  drug_test: {
    title: { en: 'Drug Test', ar: 'اختبار المخدرات', am: 'የመድኃኒት ምርመራ' },
    description: { en: 'Donna from Concentra will call you to schedule your drug test.', ar: 'ستتصل بك دونا من كونسينترا لتحديد موعد اختبار المخدرات.', am: 'ከConcentra ዶና የመድኃኒት ምርመራዎን ለማቀድ ይደውሉልዎታል።' },
  },
  firstalt_training: {
    title: { en: 'FirstAlt Training', ar: 'تدريب FirstAlt', am: 'FirstAlt ስልጠና' },
    description: { en: 'Complete your training on the FirstAlt app. It\'s available anytime.', ar: 'أكمل تدريبك على تطبيق FirstAlt. متوفر في أي وقت.', am: 'በFirstAlt መተግበሪያ ላይ ስልጠናዎን ያጠናቅቁ። በማንኛውም ጊዜ ይገኛል።' },
  },
  documents: {
    title: { en: 'Documents', ar: 'المستندات', am: 'ሰነዶች' },
    description: { en: 'Your team is reviewing your documents.', ar: 'فريقك يراجع مستنداتك.', am: 'ቡድንዎ ሰነዶችዎን እየገመገመ ነው።' },
  },
  contract_waiting: {
    title: { en: 'Partner Contract', ar: 'عقد الشريك', am: 'የአጋር ውል' },
    description: { en: 'Your contract is being prepared.', ar: 'جاري إعداد عقدك.', am: 'ውልዎ እየተዘጋጀ ነው።' },
  },
  contract_sign: {
    title: { en: 'Sign Contract', ar: 'وقّع العقد', am: 'ውል ይፈርሙ' },
    description: { en: 'Check your email to sign your partner contract.', ar: 'تحقق من بريدك لتوقيع عقد الشريك.', am: 'የአጋር ውልዎን ለመፈረም ኢሜይልዎን ይፈትሹ።' },
  },
  acumen_training: {
    title: { en: 'Acumen Training', ar: 'تدريب أكيومن', am: 'አኩመን ስልጠና' },
    description: { en: 'Complete your Acumen training to learn our procedures.', ar: 'أكمل تدريب أكيومن لتتعلم إجراءاتنا.', am: 'የአኩመን ስልጠናዎን ያጠናቅቁ ሂደቶቻችንን ለመማር።' },
    action: { en: 'Start Training', ar: 'ابدأ التدريب', am: 'ስልጠና ይጀምሩ' },
  },
  acumen_contract: {
    title: { en: 'Acumen Contract', ar: 'عقد أكيومن', am: 'የአኩመን ውል' },
    description: { en: 'Review and sign your Acumen agreement.', ar: 'راجع ووقّع اتفاقية أكيومن.', am: 'የአኩመን ስምምነትዎን ይገምግሙ እና ይፈርሙ።' },
    action: { en: 'Sign Contract', ar: 'وقّع العقد', am: 'ውል ይፈርሙ' },
  },
  paychex: {
    title: { en: 'Paychex + W-9', ar: 'Paychex + W-9', am: 'Paychex + W-9' },
    description: { en: 'Final step — your payroll enrollment is being set up.', ar: 'الخطوة الأخيرة — جاري إعداد تسجيلك في الرواتب.', am: 'የመጨረሻ ደረጃ — የደመወዝ ምዝገባዎ እየተዘጋጀ ነው።' },
  },
  complete_title: { en: "You're all set!", ar: 'أنت جاهز!', am: 'ሁሉም ተዘጋጅቷል!' },
  complete_desc: { en: 'Congratulations! Your onboarding is complete. Your dispatcher will contact you with your first route.', ar: 'تهانينا! تأهيلك مكتمل. سيتصل بك المرسل بأول مهمة.', am: 'እንኳን ደስ አለዎት! መግቢያዎ ተጠናቋል። መላኪያዎ በመጀመሪያ መንገድ ያገኙዎታል።' },
  waiting_update: { en: 'This page updates automatically', ar: 'هذه الصفحة تتحدث تلقائياً', am: 'ይህ ገጽ በራስ-ሰር ይዘምናል' },
  completed_steps: { en: 'Completed Steps', ar: 'الخطوات المكتملة', am: 'የተጠናቀቁ ደረጃዎች' },
  welcome: { en: 'Welcome to Acumen!', ar: '!مرحباً بك في أكيومن', am: 'ወደ አኩመን እንኳን ደህና መጡ!' },
  heres_what: { en: "Here's your onboarding progress:", ar: 'إليك تقدم تأهيلك:', am: 'የመግቢያ እድገትዎ ይህ ነው:' },
  need_help: { en: 'Need Help?', ar: 'تحتاج مساعدة؟', am: 'እርዳታ ይፈልጋሉ?' },
  call_dispatch: { en: 'Call dispatch', ar: 'اتصل بمركز التوزيع', am: 'ዲስፓች ይደውሉ' },
  error_title: { en: 'Invalid Link', ar: 'رابط غير صالح', am: 'ልክ ያልሆነ ማገናኛ' },
  error_desc: { en: 'This link is invalid or expired. Contact your dispatcher.', ar: 'هذا الرابط غير صالح أو منتهي. اتصل بمركز التوزيع.', am: 'ይህ ማገናኛ ልክ ያልሆነ ወይም ጊዜው ያለፈበት ነው። ዲስፓቸርዎን ያግኙ።' },
}

/* ─── Step Helpers ───────────────────────────────────────────────────── */

const DONE_STATUSES = new Set(['complete', 'completed', 'signed', 'done', 'manual', 'skipped'])
const isDone = (s: string | undefined) => s ? DONE_STATUSES.has(s.toLowerCase()) : false

const STEP_NAMES: { key: string; field: keyof OnboardingData; label: Record<Lang, string> }[] = [
  { key: 'firstalt_invite', field: 'firstalt_invite_status', label: { en: 'FirstAlt Invite', ar: 'دعوة FirstAlt', am: 'FirstAlt ግብዣ' } },
  { key: 'bgc', field: 'bgc_status', label: { en: 'Background Check', ar: 'فحص الخلفية', am: 'የዳራ ምርመራ' } },
  { key: 'consent', field: 'consent_status', label: { en: 'Drug Test Consent', ar: 'موافقة اختبار المخدرات', am: 'የመድኃኒት ምርመራ ስምምነት' } },
  { key: 'drug_test', field: 'drug_test_status', label: { en: 'Drug Test', ar: 'اختبار المخدرات', am: 'የመድኃኒት ምርመራ' } },
  { key: 'training', field: 'training_status', label: { en: 'FirstAlt Training', ar: 'تدريب FirstAlt', am: 'FirstAlt ስልጠና' } },
  { key: 'documents', field: 'files_status', label: { en: 'Documents', ar: 'المستندات', am: 'ሰነዶች' } },
  { key: 'contract', field: 'contract_status', label: { en: 'Partner Contract', ar: 'عقد الشريك', am: 'የአጋር ውል' } },
  { key: 'maz_training', field: 'maz_training_status', label: { en: 'Acumen Training', ar: 'تدريب أكيومن', am: 'አኩመን ስልጠና' } },
  { key: 'maz_contract', field: 'maz_contract_status', label: { en: 'Acumen Contract', ar: 'عقد أكيومن', am: 'የአኩመን ውል' } },
  { key: 'paychex', field: 'paychex_status', label: { en: 'Paychex + W-9', ar: 'Paychex + W-9', am: 'Paychex + W-9' } },
]

function countCompleted(data: OnboardingData): number {
  return STEP_NAMES.filter(s => isDone(data[s.field] as string)).length
}

function getDriverCurrentStep(data: OnboardingData, token: string): DriverStep | null {
  let stepNum = 2 // Step 1 is the intake form (already complete by the time we show this portal)

  // 2. FirstAlt Invite
  const faStatus = data.firstalt_invite_status ?? data.priority_email_status
  if (!isDone(faStatus)) {
    return { key: 'waiting_team', stepNumber: stepNum, ...S.waiting_team, hasAction: false, isWaiting: true, icon: <Clock className="w-6 h-6 text-amber-400" /> }
  }
  stepNum++

  // 2. BGC — driver should download app while BGC processes
  if (!isDone(data.bgc_status)) {
    return { key: 'download_app', stepNumber: stepNum, ...S.download_app, hasAction: true, actionLabel: S.download_app.action, actionUrl: FIRSTALT_APP_URL, isWaiting: false, icon: <Smartphone className="w-6 h-6 text-blue-400" /> }
  }
  stepNum++

  // 3. Consent
  if (!isDone(data.consent_status)) {
    const sent = data.consent_status?.toLowerCase() === 'sent'
    const step = sent ? S.consent_sign : S.consent_waiting
    return { key: 'consent', stepNumber: stepNum, ...step, hasAction: false, isWaiting: !sent, icon: <ClipboardList className="w-6 h-6 text-violet-400" /> }
  }
  stepNum++

  // 4. Drug Test
  if (!isDone(data.drug_test_status)) {
    return { key: 'drug_test', stepNumber: stepNum, ...S.drug_test, hasAction: false, isWaiting: true, icon: <ShieldCheck className="w-6 h-6 text-cyan-400" /> }
  }
  stepNum++

  // 5. FirstAlt Training
  if (!isDone(data.training_status)) {
    return { key: 'training', stepNumber: stepNum, ...S.firstalt_training, hasAction: false, isWaiting: true, icon: <BookOpen className="w-6 h-6 text-amber-400" /> }
  }
  stepNum++

  // 6. Documents
  if (!isDone(data.files_status)) {
    return { key: 'documents', stepNumber: stepNum, ...S.documents, hasAction: false, isWaiting: true, icon: <FileText className="w-6 h-6 text-zinc-400" /> }
  }
  stepNum++

  // 7. Partner Contract
  if (!isDone(data.contract_status)) {
    const sent = data.contract_status?.toLowerCase() === 'sent'
    const step = sent ? S.contract_sign : S.contract_waiting
    return { key: 'contract', stepNumber: stepNum, ...step, hasAction: false, isWaiting: !sent, icon: <FileSignature className="w-6 h-6 text-emerald-400" /> }
  }
  stepNum++

  // 8. Acumen Training
  if (!isDone(data.maz_training_status)) {
    return { key: 'maz_training', stepNumber: stepNum, ...S.acumen_training, hasAction: true, actionLabel: S.acumen_training.action, actionUrl: `/training/${token}`, isWaiting: false, icon: <BookOpen className="w-6 h-6 text-amber-400" /> }
  }
  stepNum++

  // 9. Acumen Contract
  if (!isDone(data.maz_contract_status)) {
    return { key: 'maz_contract', stepNumber: stepNum, ...S.acumen_contract, hasAction: true, actionLabel: S.acumen_contract.action, actionUrl: `/contract/${token}`, isWaiting: false, icon: <FileSignature className="w-6 h-6 text-emerald-400" /> }
  }
  stepNum++

  // 10. Paychex
  if (!isDone(data.paychex_status)) {
    return { key: 'paychex', stepNumber: stepNum, ...S.paychex, hasAction: false, isWaiting: true, icon: <BadgeDollarSign className="w-6 h-6 text-green-400" /> }
  }

  return null // All done
}

/* ─── Sub-Components ─────────────────────────────────────────────────── */

function ProgressRing({ completed, total }: { completed: number; total: number }) {
  const pct = (completed / total) * 100
  const r = 40
  const c = 2 * Math.PI * r
  return (
    <div className="flex justify-center my-8">
      <div className="relative w-24 h-24">
        <svg className="w-24 h-24 -rotate-90" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r={r} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="6" />
          <motion.circle cx="50" cy="50" r={r} fill="none" stroke="#10b981" strokeWidth="6"
            strokeDasharray={c} initial={{ strokeDashoffset: c }}
            animate={{ strokeDashoffset: c - (c * pct / 100) }}
            strokeLinecap="round" transition={{ duration: 1, ease: 'easeOut' }} />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-bold text-white">{completed}<span className="text-zinc-500">/{total}</span></span>
        </div>
      </div>
    </div>
  )
}

function StepCard({ step, lang }: { step: DriverStep; lang: Lang }) {
  return (
    <motion.div
      key={step.key}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
      className="rounded-2xl bg-white/5 border border-white/10 p-6 mb-6"
    >
      <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-4">
        Step {step.stepNumber} of 11
      </p>
      <div className="flex items-start gap-4">
        <div className="w-12 h-12 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center shrink-0">
          {step.icon}
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-lg font-semibold mb-2">{step.title[lang]}</h2>
          <p className="text-sm text-zinc-400 leading-relaxed">{step.description[lang]}</p>
          {step.isWaiting && (
            <div className="flex items-center gap-2 mt-4 text-amber-400/80 text-xs">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span>{S.waiting_update[lang]}</span>
            </div>
          )}
          {step.hasAction && step.actionUrl && step.actionLabel && (
            <Link
              href={step.actionUrl}
              target={step.actionUrl.startsWith('http') ? '_blank' : undefined}
              rel={step.actionUrl.startsWith('http') ? 'noopener noreferrer' : undefined}
              className="inline-flex items-center gap-1.5 mt-4 px-5 py-3 min-h-[48px] rounded-xl bg-blue-500 hover:bg-blue-400 text-white text-sm font-semibold transition-colors"
            >
              {step.actionLabel[lang]}
              <ChevronRight className="w-4 h-4" />
            </Link>
          )}
        </div>
      </div>
    </motion.div>
  )
}

function CompletionCard({ lang }: { lang: Lang }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="rounded-2xl bg-emerald-500/10 border border-emerald-500/20 p-8 text-center mb-6"
    >
      <div className="w-16 h-16 rounded-2xl bg-emerald-500/20 flex items-center justify-center mx-auto mb-4">
        <Sparkles className="w-8 h-8 text-emerald-400" />
      </div>
      <h2 className="text-xl font-bold mb-2">{S.complete_title[lang]}</h2>
      <p className="text-sm text-zinc-400 leading-relaxed">{S.complete_desc[lang]}</p>
    </motion.div>
  )
}

function CompletedSteps({ data, lang }: { data: OnboardingData; lang: Lang }) {
  const [open, setOpen] = useState(false)
  const done = STEP_NAMES.filter(s => isDone(data[s.field] as string))
  if (done.length === 0) return null

  return (
    <div className="mb-6">
      <button onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full text-sm text-zinc-500 hover:text-zinc-300 transition-colors py-2">
        <span>{S.completed_steps[lang]} ({done.length})</span>
        <ChevronDown className={`w-4 h-4 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="space-y-2 pt-2">
              {done.map(s => (
                <div key={s.key} className="flex items-center gap-2.5 text-sm text-zinc-400">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>{s.label[lang]}</span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/* ─── Page Component ─────────────────────────────────────────────────── */

export default function JoinPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params)

  const [data, setData] = useState<OnboardingData | null>(null)
  const [loading, setLoading] = useState(true)
  const [invalid, setInvalid] = useState(false)
  const [lang, setLang] = useState<Lang>('en')
  const [showIntake, setShowIntake] = useState(false)

  const fetchData = useCallback(() => {
    return fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/join/${token}`)
      .then(res => { if (!res.ok) throw new Error('invalid'); return res.json() })
      .then((d: OnboardingData) => {
        setData(d)
        const pl = d.person_language?.toLowerCase() as Lang | undefined
        if (pl && (pl === 'ar' || pl === 'am')) setLang(pl)
        if (!d.personal_info || Object.keys(d.personal_info).length === 0) {
          setShowIntake(true)
        } else {
          setShowIntake(false)
        }
        setLoading(false)
      })
      .catch(() => { setInvalid(true); setLoading(false) })
  }, [token])

  // Initial fetch + polling
  useEffect(() => {
    fetchData()
    const interval = setInterval(() => {
      if (!showIntake) fetchData()
    }, 5000)
    return () => clearInterval(interval)
  }, [fetchData, showIntake])

  /* ── Loading ── */
  if (loading) {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-white/40 animate-spin" />
      </div>
    )
  }

  /* ── Invalid token ── */
  if (invalid || !data) {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center px-4">
        <div className="max-w-sm text-center">
          <div className="w-16 h-16 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center mx-auto mb-4">
            <AlertCircle className="w-8 h-8 text-red-400" />
          </div>
          <h1 className="text-xl font-bold text-white mb-2">{S.error_title.en}</h1>
          <p className="text-sm text-zinc-400">{S.error_desc.en}</p>
        </div>
      </div>
    )
  }

  /* ── Intake form ── */
  if (showIntake) {
    return (
      <IntakeForm
        token={token}
        initialLang={lang}
        prefill={{
          full_name: data.person_name ?? undefined,
          phone: data.person_phone ?? undefined,
          email: data.person_email ?? undefined,
        }}
        onComplete={() => {
          setShowIntake(false)
          fetchData()
        }}
      />
    )
  }

  /* ── Main portal ── */
  const currentStep = getDriverCurrentStep(data, token)
  const completedCount = countCompleted(data) + 1 // +1 for the intake form (always done at this point)
  const isComplete = !currentStep
  const isRtl = lang === 'ar'
  const firstName = data.person_name?.split(' ')[0] ?? ''

  return (
    <div className={`min-h-screen bg-[#09090b] text-white ${isRtl ? 'rtl' : 'ltr'}`} dir={isRtl ? 'rtl' : 'ltr'}>
      <div className="max-w-md mx-auto px-4 py-8 pb-20">

        {/* Language selector */}
        <motion.div className="flex items-center justify-center gap-2 mb-8"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
          {(Object.keys(FLAGS) as Lang[]).map(l => (
            <button key={l} onClick={() => setLang(l)}
              className={`text-2xl px-3 py-2 rounded-xl transition-all min-h-[48px] min-w-[48px]
                ${lang === l ? 'bg-white/10 border border-white/20 scale-110' : 'bg-white/5 border border-transparent hover:bg-white/10 opacity-60 hover:opacity-100'}`}
              aria-label={`Switch to ${l === 'en' ? 'English' : l === 'ar' ? 'Arabic' : 'Amharic'}`}>
              {FLAGS[l]}
            </button>
          ))}
        </motion.div>

        {/* Welcome */}
        <motion.div className="text-center mb-6" initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.1 }}>
          <h1 className="text-2xl font-bold tracking-tight mb-1">{S.welcome[lang]}</h1>
          {firstName && <p className="text-lg text-zinc-400 font-medium">{firstName}</p>}
          <p className="text-sm text-zinc-500 mt-3">{S.heres_what[lang]}</p>
        </motion.div>

        {/* Progress Ring */}
        <ProgressRing completed={completedCount} total={11} />

        {/* Current Step or Completion */}
        <AnimatePresence mode="wait">
          {isComplete ? (
            <CompletionCard lang={lang} />
          ) : (
            <StepCard key={currentStep.key} step={currentStep} lang={lang} />
          )}
        </AnimatePresence>

        {/* Completed Steps */}
        <CompletedSteps data={data} lang={lang} />

        {/* Help */}
        <motion.div className="text-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 }}>
          <p className="text-sm text-zinc-500 mb-2">{S.need_help[lang]}</p>
          <a href={`tel:${DISPATCH_PHONE.replace(/\D/g, '')}`}
            className="inline-flex items-center gap-2 px-4 py-2.5 min-h-[48px] rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 text-zinc-300 text-sm font-medium transition-colors">
            <Phone className="w-4 h-4" />
            {S.call_dispatch[lang]}: {DISPATCH_PHONE}
          </a>
        </motion.div>

      </div>
    </div>
  )
}
