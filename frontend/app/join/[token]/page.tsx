'use client'

import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { CheckCircle2, Clock, ChevronRight, AlertCircle, Loader2 } from 'lucide-react'

/* ─── Types ──────────────────────────────────────────────────────────── */

interface JoinRecord {
  id: number
  person_id: number
  person_name: string | null
  person_email: string | null
  person_phone: string | null
  consent_status: string
  priority_email_status: string
  brandon_email_status: string
  bgc_status: string
  drug_test_status: string
  contract_status: string
  files_status: string
  paychex_status: string
  notes: string | null
  started_at: string
  completed_at: string | null
  invite_token: string | null
  personal_info: Record<string, string> | null
  person?: {
    person_id: number
    full_name: string
    email: string
    phone: string
    home_address: string | null
    language: string | null
  }
}

type Lang = 'en' | 'ar' | 'am'

/* ─── Strings (all UI text in 3 languages) ───────────────────────────── */

const S = {
  welcome_title: {
    en: 'Welcome to MAZ Services',
    ar: 'مرحباً بك في خدمات ماز',
    am: 'ወደ ማዝ አገልግሎቶች እንኳን ደህና መጡ',
  },
  welcome_subtitle: {
    en: 'Driver Onboarding',
    ar: 'تأهيل السائق',
    am: 'የሾፌር ምዝገባ',
  },
  welcome_body: {
    en: "We're glad to have you on the team. This guide will walk you through each step of the onboarding process. It should take about 10–15 minutes to review.",
    ar: 'يسعدنا انضمامك إلى فريقنا. سيرشدك هذا الدليل خلال كل خطوة من خطوات عملية التأهيل.',
    am: 'ቡድናችን አካል ስለሆናችሁ ደስ ብሎናል። ይህ መመሪያ የምዝገባ ሂደቱን ደረጃ በደረጃ ያሳያዎታል።',
  },
  select_language: {
    en: 'Select your language',
    ar: 'اختر لغتك',
    am: 'ቋንቋዎን ይምረጡ',
  },
  get_started: {
    en: "Let's get started",
    ar: 'لنبدأ',
    am: 'እንጀምር',
  },
  step_of: {
    en: (current: number, total: number) => `Step ${current} of ${total}`,
    ar: (current: number, total: number) => `الخطوة ${current} من ${total}`,
    am: (current: number, total: number) => `ደረጃ ${current} ከ ${total}`,
  },
  complete_title: {
    en: "You're all set!",
    ar: 'أنت جاهز!',
    am: 'ሁሉም ተዘጋጅቷል!',
  },
  complete_body: {
    en: "Welcome to the MAZ Services team. Your dispatcher will contact you with your first route assignment. Make sure your phone is on and your app is updated.",
    ar: 'مرحباً بك في فريق خدمات ماز. سيتصل بك المرسل بأول مهمة توصيل. تأكد من أن هاتفك مفعل وتطبيقك محدث.',
    am: 'ወደ ማዝ አገልግሎቶች ቡድን እንኳን ደህና መጡ። የእርስዎ ላኪ ለመጀመሪያ ጉዞ ስምሪትዎ ያነጋግሩዎታል። ስልክዎ ሃይለኛ እና አፕሊኬሽኑ ወቅታዊ መሆኑን ያረጋግጡ።',
  },
  error_invalid: {
    en: 'Link expired or invalid',
    ar: 'الرابط منتهي الصلاحية أو غير صالح',
    am: 'አገናኙ ጊዜው አልፎ ወይም ልክ ያልሆነ',
  },
  error_body: {
    en: 'Please contact your dispatcher to get a new onboarding link.',
    ar: 'يرجى الاتصال بالمرسل للحصول على رابط تأهيل جديد.',
    am: 'አዲስ የምዝገባ አገናኝ ለማግኘት ላኪዎን ያነጋግሩ።',
  },
  save: {
    en: 'Save & Continue',
    ar: 'حفظ ومتابعة',
    am: 'አስቀምጥ እና ቀጥል',
  },
  saving: {
    en: 'Saving…',
    ar: 'جارٍ الحفظ…',
    am: 'በማስቀምጥ ላይ…',
  },
  next: {
    en: 'Next',
    ar: 'التالي',
    am: 'ቀጣይ',
  },
  // Step titles
  step_titles: {
    en: ['Personal Info', 'Consent Form', 'Background Check', 'Drug Test', 'Contract', 'Documents', 'Payroll Setup', 'Complete'],
    ar: ['المعلومات الشخصية', 'نموذج الموافقة', 'فحص الخلفية', 'اختبار المخدرات', 'العقد', 'المستندات', 'إعداد الرواتب', 'مكتمل'],
    am: ['የግል መረጃ', 'የፈቃድ ቅጽ', 'የዳራ ምርመራ', 'የዕፅ ምርመራ', 'ውል', 'ሰነዶች', 'የደሞዝ ዝግጅት', 'ተጠናቋል'],
  },
  // Step guidance
  step_guidance: {
    personal_info: {
      en: "Please confirm your personal details. This information helps us set up your account correctly.",
      ar: "يرجى تأكيد بياناتك الشخصية. تساعدنا هذه المعلومات في إعداد حسابك بشكل صحيح.",
      am: "የግልዎን መረጃ ያረጋግጡ። ይህ መረጃ መለያዎን በትክክል እንድናዘጋጅ ይረዳናል።",
    },
    consent: {
      en: "We need your consent to begin the onboarding process. You'll receive an email with a document to sign electronically. Check your email and sign the consent form to continue.",
      ar: "نحتاج إلى موافقتك لبدء عملية التأهيل. ستتلقى بريدًا إلكترونيًا بمستند للتوقيع إلكترونيًا. تحقق من بريدك الإلكتروني ووقّع على نموذج الموافقة للمتابعة.",
      am: "ሂደቱን ለመጀመር ፈቃድዎን ያስፈልጋታል። ኢሜይልዎን ይፈትሹ እና የፈቃድ ቅጹን ይፈርሙ።",
    },
    bgc: {
      en: "A background check is required for all drivers. This is standard for working with school children. You'll receive instructions by email. This typically takes 3–5 business days.",
      ar: "مطلوب إجراء فحص خلفية لجميع السائقين. هذا أمر قياسي للعمل مع طلاب المدارس. ستتلقى التعليمات عبر البريد الإلكتروني. عادةً ما يستغرق هذا 3–5 أيام عمل.",
      am: "ለሁሉም ሾፌሮች የዳራ ምርመራ ያስፈልጋል። ይህ ለትምህርት ቤት ልጆች ከሚሰሩ ሰዎች ሁሉ መደበኛ ነው። ትእዛዞቹ ወደ ኢሜይልዎ ይላካሉ። ብዙውን ጊዜ 3–5 የስራ ቀናት ይወስዳል።",
    },
    drug_test: {
      en: `You need to take a drug test at Concentra before you can begin driving. Our team will notify the clinic that you are coming.${process.env.NEXT_PUBLIC_CONCENTRA_ADDRESS ? ` Go to: ${process.env.NEXT_PUBLIC_CONCENTRA_ADDRESS}.` : ''} When you arrive, ask for Donna. You will need to pay over the phone before your test. The test takes about 15 minutes. Bring your ID.`,
      ar: `يجب عليك إجراء اختبار مخدرات في Concentra قبل أن تتمكن من بدء القيادة. سيقوم فريقنا بإبلاغ العيادة بقدومك.${process.env.NEXT_PUBLIC_CONCENTRA_ADDRESS ? ` توجه إلى: ${process.env.NEXT_PUBLIC_CONCENTRA_ADDRESS}.` : ''} عند وصولك، اسأل عن Donna. ستحتاج إلى الدفع عبر الهاتف قبل اختبارك. يستغرق الاختبار حوالي 15 دقيقة. أحضر هويتك.`,
      am: `መንዳት ከመጀመርዎ በፊት በ Concentra የዕፅ ምርመራ ማድረግ ያስፈልግዎታል። ቡድናችን ክሊኒኩን ስለ መምጣትዎ ያሳውቃቸዋል።${process.env.NEXT_PUBLIC_CONCENTRA_ADDRESS ? ` ወደዚህ ይሂዱ: ${process.env.NEXT_PUBLIC_CONCENTRA_ADDRESS}።` : ''} ሲደርሱ፣ Donna ን ይጠይቁ። ምርመራዎ ከመደረጉ በፊት በስልክ ክፍያ መፈፀም ያስፈልጋዎታል። ምርመራው ወደ 15 ደቂቃ ያህል ይወስዳል። መታወቂያዎን ይዘው ይምጡ።`,
    },
    contract: {
      en: "Your driving contract outlines your route, pay rate, and responsibilities. Review it carefully before signing. You'll receive it by email.",
      ar: "يوضح عقد القيادة الخاص بك مسارك ومعدل أجرك ومسؤولياتك. راجعه بعناية قبل التوقيع. ستتلقاه عبر البريد الإلكتروني.",
      am: "የእርስዎ የማሽከርከር ውል መስመርዎን፣ የደሞዝ ምጣኔዎን እና ኃላፊነቶቻዎን ይዘረዝራል። ከመፈረምዎ በፊት በጥንቃቄ ያንብቡ። ወደ ኢሜይልዎ ይላካል።",
    },
    files: {
      en: "Please have the following ready: Driver's License (front and back), Vehicle Registration, Proof of Insurance, and a photo of your vehicle (front and side). Our team will guide you on how to submit these.",
      ar: "يرجى تجهيز ما يلي: رخصة القيادة (الأمامية والخلفية)، تسجيل المركبة، إثبات التأمين، وصورة مركبتك (الأمامية والجانبية). سيرشدك فريقنا حول كيفية تقديمها.",
      am: "እባኮትን የሚከተሉትን ያዘጋጁ: የሾፌር ፍቃድ (ፊት እና ኋላ)፣ የተሽከርካሪ ምዝገባ፣ የኢንሹራንስ ማስረጃ እና የተሽከርካሪዎ ፎቶ (ፊት እና ጎን)። ቡድናችን እነዚህን እንዴት ማቅረብ እንደሚቻል ይመራዎታል።",
    },
    paychex: {
      en: "To receive your pay, you need to be added to our payroll system. This step is completed by our team — no action needed from you. You'll receive a welcome email from Paychex with instructions to set up direct deposit.",
      ar: "لاستلام راتبك، تحتاج إلى إضافتك إلى نظام الرواتب لدينا. يتم إكمال هذه الخطوة من قبل فريقنا — لا يلزمك اتخاذ أي إجراء. ستتلقى بريدًا إلكترونيًا ترحيبيًا من Paychex مع تعليمات لإعداد الإيداع المباشر.",
      am: "ደሞዝዎን ለመቀበል ወደ የደሞዝ ስርዓታችን ሊጨምሩ ያስፈልጋቸዋል። ይህ ደረጃ በቡድናችን ይጠናቀቃል — ምንም እርምጃ አያስፈልግዎትም። ቀጥታ ቀጥ ቅናሽ ለማዘጋጀት ከ Paychex የእንኳን ደህና መጡ ኢሜይል ይደርስዎታል።",
    },
  },
  // Field labels
  field_full_name: { en: 'Full Name', ar: 'الاسم الكامل', am: 'ሙሉ ስም' },
  field_address: { en: 'Home Address', ar: 'العنوان المنزلي', am: 'የቤት አድራሻ' },
  field_dob: { en: 'Date of Birth', ar: 'تاريخ الميلاد', am: 'የልደት ቀን' },
  field_emergency_name: { en: 'Emergency Contact Name', ar: 'اسم جهة الاتصال الطارئة', am: 'የአደጋ ጊዜ ድረስ ስም' },
  field_emergency_phone: { en: 'Emergency Contact Phone', ar: 'هاتف جهة الاتصال الطارئة', am: 'የአደጋ ጊዜ ድረስ ስልክ' },
  // Status labels
  status_pending: { en: 'Pending', ar: 'قيد الانتظار', am: 'በጠበቃ ላይ' },
  status_sent: { en: 'Sent — check your email', ar: 'تم الإرسال — تحقق من بريدك الإلكتروني', am: 'ተልኳል — ኢሜይልዎን ይፈትሹ' },
  status_signed: { en: 'Signed', ar: 'تم التوقيع', am: 'ተፈርሟል' },
  status_complete: { en: 'Complete', ar: 'مكتمل', am: 'ተጠናቋል' },
  status_manual: { en: 'Being arranged by our team', ar: 'يتم الترتيب من قبل فريقنا', am: 'በቡድናችን እየተዘጋጀ ነው' },
  action_required: { en: 'Action Required', ar: 'مطلوب إجراء', am: 'እርምጃ ያስፈልጋል' },
  admin_handling: { en: 'Our team is handling this', ar: 'فريقنا يتولى هذا', am: 'ቡድናችን ይህን ይወስዳል' },

  // "What happens next" interstitial
  whn_title: {
    en: "You're all set!",
    ar: 'أنت جاهز!',
    am: 'ሁሉም ተዘጋጅቷል!',
  },
  whn_subtitle: {
    en: "Here's what to expect:",
    ar: 'إليك ما يمكن توقعه:',
    am: 'ምን እንደሚጠብቅዎ ይኸውና:',
  },
  whn_step1_title: {
    en: 'Check your email',
    ar: 'تحقق من بريدك الإلكتروني',
    am: 'ኢሜይልዎን ይፈትሹ',
  },
  whn_step1_body: {
    en: "You'll receive two emails shortly: an invitation to join the FirstAlt driver app (sign up and complete your profile there), and a consent form to review and sign electronically.",
    ar: 'ستتلقى بريدين إلكترونيين قريبًا: دعوة للانضمام إلى تطبيق سائقي FirstAlt (سجّل واستكمل ملفك الشخصي هناك)، ونموذج موافقة لمراجعته والتوقيع عليه إلكترونيًا.',
    am: 'ሁለት ኢሜይሎችን ብዙም ሳይቆይ ይደርስዎታል: ወደ FirstAlt ሾፌር አፕ ለመቀላቀል ግብዣ (እዚያ ይመዝገቡ እና መገለጫዎን ያጠናቅቁ)፣ እና ለማስፈረም ፈቃድ ቅጽ።',
  },
  whn_step2_title: {
    en: 'Complete your consent form',
    ar: 'أكمل نموذج الموافقة',
    am: 'የፈቃድ ቅጽዎን ያጠናቅቁ',
  },
  whn_step2_body: {
    en: 'Open the consent form email, read it carefully, and sign it. This takes about 2 minutes.',
    ar: 'افتح بريد نموذج الموافقة، اقرأه بعناية، ووقّع عليه. يستغرق هذا حوالي دقيقتين.',
    am: 'የፈቃድ ቅጽ ኢሜይሉን ይክፈቱ፣ በጥንቃቄ ያንብቡት፣ እና ይፈርሙ። ይህ ወደ 2 ደቂቃ ይወስዳል።',
  },
  whn_step3_title: {
    en: "We'll take it from there",
    ar: 'سنتولى الأمر من هنا',
    am: 'ከዚህ ወዲህ እኛ እንወስዳለን',
  },
  whn_step3_body: {
    en: 'Once you sign, our team gets notified automatically. We\'ll send your background check and contract. You\'ll get everything by email.',
    ar: 'بمجرد توقيعك، سيتلقى فريقنا إشعارًا تلقائيًا. سنرسل لك فحص خلفيتك وعقدك. ستتلقى كل شيء عبر البريد الإلكتروني.',
    am: 'ከፈረሙ በኋላ ቡድናችን ራሱ በራሱ ይነገረዋል። የዳራ ምርመራዎን እና ውልዎን እንልካለን። ሁሉንም ወደ ኢሜይልዎ ያገኛሉ።',
  },
  whn_step4_title: {
    en: 'Drug test',
    ar: 'اختبار المخدرات',
    am: 'የዕፅ ምርመራ',
  },
  whn_step4_body: {
    en: "We'll give you a location and reference number. The test takes about 15 minutes.",
    ar: 'سنزودك بموقع ورقم مرجعي. يستغرق الاختبار حوالي 15 دقيقة.',
    am: 'ቦታ እና ማጣቀሻ ቁጥር እናቀርብዎታለን። ምርመራው ወደ 15 ደቂቃ ይወስዳል።',
  },
  whn_step5_title: {
    en: "You're ready to drive",
    ar: 'أنت مستعد للقيادة',
    am: 'ለመንዳት ዝግጁ ነዎት',
  },
  whn_step5_body: {
    en: 'After all steps are complete, your dispatcher will contact you with your first route.',
    ar: 'بعد اكتمال جميع الخطوات، سيتصل بك المرسل بأول مسار لك.',
    am: 'ሁሉም ደረጃዎች ከተጠናቀቁ በኋላ ላኪዎ ለመጀመሪያ መስመርዎ ያነጋግሩዎታል።',
  },
  whn_footer: {
    en: 'Keep this link saved — you can check your progress here anytime.',
    ar: 'احتفظ بهذا الرابط — يمكنك التحقق من تقدمك هنا في أي وقت.',
    am: 'ይህን አገናኝ አስቀምጡ — ሂደትዎን እዚህ በማንኛውም ጊዜ ማረጋገጥ ይችላሉ።',
  },
  whn_got_it: {
    en: 'Got it →',
    ar: '← حسنًا، فهمت',
    am: 'ገባኝ →',
  },
}

function t(key: keyof typeof S, lang: Lang, ...args: unknown[]): string {
  const entry = S[key] as Record<Lang, string | ((...a: unknown[]) => string)>
  const val = entry[lang] || entry['en']
  if (typeof val === 'function') return (val as (...a: unknown[]) => string)(...args)
  return val as string
}

function tStepTitle(idx: number, lang: Lang): string {
  return S.step_titles[lang]?.[idx] ?? S.step_titles['en'][idx]
}

function tGuidance(key: keyof typeof S['step_guidance'], lang: Lang): string {
  return S.step_guidance[key][lang] ?? S.step_guidance[key]['en']
}

/* ─── Step status helpers ────────────────────────────────────────────── */

function isDone(status: string) {
  return status === 'complete' || status === 'signed'
}

function isInProgress(status: string) {
  return status === 'sent' || status === 'manual'
}

/* ─── Status Chip ────────────────────────────────────────────────────── */

function StatusChip({ status, lang }: { status: string; lang: Lang }) {
  if (isDone(status)) {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-emerald-50 text-emerald-600 border border-emerald-200">
        <CheckCircle2 className="w-4 h-4" />
        {t('status_complete', lang)}
      </span>
    )
  }
  if (status === 'sent') {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-amber-50 text-amber-600 border border-amber-200">
        <Clock className="w-4 h-4" />
        {t('status_sent', lang)}
      </span>
    )
  }
  if (status === 'manual') {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-blue-50 text-blue-600 border border-blue-200">
        <Clock className="w-4 h-4" />
        {t('admin_handling', lang)}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-500 border border-gray-200">
      <Clock className="w-4 h-4" />
      {t('status_pending', lang)}
    </span>
  )
}

/* ─── Step Card ──────────────────────────────────────────────────────── */

function StepCard({
  number,
  title,
  guidance,
  status,
  lang,
  isCurrent,
  children,
}: {
  number: number
  title: string
  guidance: string
  status: string
  lang: Lang
  isCurrent: boolean
  children?: React.ReactNode
}) {
  const done = isDone(status)

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: number * 0.05 }}
      className={`rounded-2xl border p-5 ${
        done
          ? 'bg-emerald-50 border-emerald-200'
          : isCurrent
          ? 'bg-white border-indigo-300 shadow-md shadow-indigo-100'
          : 'bg-gray-50 border-gray-200 opacity-60'
      }`}
    >
      <div className="flex items-start gap-3">
        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0 ${
          done ? 'bg-emerald-500 text-white' : isCurrent ? 'bg-indigo-500 text-white' : 'bg-gray-200 text-gray-500'
        }`}>
          {done ? <CheckCircle2 className="w-4 h-4" /> : number}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
            <h3 className={`font-semibold text-base ${done ? 'text-emerald-700' : 'text-gray-900'}`}>{title}</h3>
            <StatusChip status={status} lang={lang} />
          </div>
          {isCurrent && (
            <p className="text-sm text-gray-600 leading-relaxed mb-3">{guidance}</p>
          )}
          {children}
        </div>
      </div>
    </motion.div>
  )
}

/* ─── Personal Info Form ─────────────────────────────────────────────── */

function PersonalInfoForm({
  record,
  lang,
  token,
  onSaved,
}: {
  record: JoinRecord
  lang: Lang
  token: string
  onSaved: (updated: JoinRecord) => void
}) {
  const existing = record.personal_info || {}
  const [form, setForm] = useState({
    full_name: existing.full_name || record.person_name || '',
    address: existing.address || record.person?.home_address || '',
    dob: existing.dob || '',
    emergency_name: existing.emergency_name || '',
    emergency_phone: existing.emergency_phone || '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      const res = await fetch(`/api/data/onboarding/join/${token}/step`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step: 'personal_info', data: form }),
      })
      if (!res.ok) throw new Error('Failed to save')
      const updated: JoinRecord = await res.json()
      onSaved(updated)
    } catch {
      setError('Could not save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const fields = [
    { key: 'full_name', label: t('field_full_name', lang), type: 'text', placeholder: 'e.g. Ahmed Hassan' },
    { key: 'address', label: t('field_address', lang), type: 'text', placeholder: 'e.g. 123 Main St, Bellevue WA 98004' },
    { key: 'dob', label: t('field_dob', lang), type: 'date', placeholder: '' },
    { key: 'emergency_name', label: t('field_emergency_name', lang), type: 'text', placeholder: 'e.g. Fatima Hassan' },
    { key: 'emergency_phone', label: t('field_emergency_phone', lang), type: 'tel', placeholder: 'e.g. (206) 555-0100' },
  ] as const

  return (
    <form onSubmit={handleSubmit} className="mt-3 space-y-3">
      {fields.map(f => (
        <div key={f.key}>
          <label className="block text-sm font-medium text-gray-700 mb-1">{f.label}</label>
          <input
            type={f.type}
            value={form[f.key]}
            onChange={e => setForm(prev => ({ ...prev, [f.key]: e.target.value }))}
            placeholder={f.placeholder}
            className="w-full px-3 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 transition-all bg-white"
          />
        </div>
      ))}
      {error && <p className="text-red-500 text-sm">{error}</p>}
      <button
        type="submit"
        disabled={saving}
        className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-medium text-white disabled:opacity-60 cursor-pointer transition-all"
        style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
      >
        {saving ? (
          <><Loader2 className="w-4 h-4 animate-spin" />{t('saving', lang)}</>
        ) : (
          <>{t('save', lang)}<ChevronRight className="w-4 h-4" /></>
        )}
      </button>
    </form>
  )
}

/* ─── Main Portal Page ───────────────────────────────────────────────── */

export default function JoinPage({ params }: { params: { token: string } }) {
  const { token } = params

  const [record, setRecord]       = useState<JoinRecord | null>(null)
  const [loading, setLoading]     = useState(true)
  const [invalid, setInvalid]     = useState(false)
  const [lang, setLang]           = useState<Lang>('en')
  const [started, setStarted]     = useState(false)
  // Must be declared here (before any early returns) to satisfy React Rules of Hooks
  const [showWhatNext, setShowWhatNext] = useState(false)

  useEffect(() => {
    fetch(`/api/data/onboarding/join/${token}`)
      .then(res => {
        if (!res.ok) throw new Error('invalid')
        return res.json()
      })
      .then((data: JoinRecord) => {
        setRecord(data)
        // Auto-detect language from person record if available
        const personLang = data.person?.language as Lang | undefined
        if (personLang && ['en', 'ar', 'am'].includes(personLang)) {
          setLang(personLang)
        }
        setLoading(false)
      })
      .catch(() => {
        setInvalid(true)
        setLoading(false)
      })
  }, [token])

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
      </div>
    )
  }

  if (invalid || !record) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="max-w-sm text-center">
          <div className="w-16 h-16 rounded-2xl bg-red-100 flex items-center justify-center mx-auto mb-4">
            <AlertCircle className="w-8 h-8 text-red-500" />
          </div>
          <h1 className="text-xl font-bold text-gray-900 mb-2">{t('error_invalid', 'en')}</h1>
          <p className="text-sm text-gray-500">{t('error_body', 'en')}</p>
        </div>
      </div>
    )
  }

  // Derive per-step status
  const steps = [
    { key: 'personal_info',   status: record.personal_info ? 'complete' : 'pending' },
    { key: 'consent',         status: record.consent_status },
    { key: 'bgc',             status: record.bgc_status },
    { key: 'drug_test',       status: record.drug_test_status },
    { key: 'contract',        status: record.contract_status },
    { key: 'files',           status: record.files_status },
    { key: 'paychex',         status: record.paychex_status },
    { key: 'complete',        status: record.completed_at ? 'complete' : 'pending' },
  ]

  const completedCount = steps.filter(s => isDone(s.status)).length
  const currentIdx = steps.findIndex(s => !isDone(s.status))
  const isAllDone = completedCount >= steps.length - 1 || !!record.completed_at

  const progressPct = Math.round((completedCount / (steps.length - 1)) * 100)

  const guidanceMap: Record<string, keyof typeof S['step_guidance']> = {
    consent: 'consent',
    bgc: 'bgc',
    drug_test: 'drug_test',
    contract: 'contract',
    files: 'files',
    paychex: 'paychex',
  }

  const isRTL = lang === 'ar'

  /* ── Welcome screen ── */
  if (!started) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-cyan-50 flex items-center justify-center px-4 py-8" dir={isRTL ? 'rtl' : 'ltr'}>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="max-w-lg w-full"
        >
          {/* Logo / brand */}
          <div className="text-center mb-8">
            <div
              className="w-16 h-16 rounded-2xl mx-auto mb-4 flex items-center justify-center text-white text-2xl font-bold shadow-lg"
              style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
            >
              M
            </div>
            <h1 className="text-2xl font-bold text-gray-900">{t('welcome_title', lang)}</h1>
            <p className="text-gray-500 text-sm mt-1">{t('welcome_subtitle', lang)}</p>
          </div>

          {/* Greeting */}
          <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-6">
            <p className="text-lg font-semibold text-gray-900 mb-1">
              {isRTL ? `${record.person_name}،` : `Hello, ${record.person_name}!`}
            </p>
            <p className="text-gray-600 text-sm leading-relaxed">{t('welcome_body', lang)}</p>
          </div>

          {/* Language selector */}
          <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-5 mb-6">
            <p className="text-sm font-medium text-gray-700 mb-3">{t('select_language', lang)}</p>
            <div className="grid grid-cols-3 gap-2">
              {([
                { code: 'en' as Lang, flag: '🇺🇸', label: 'English' },
                { code: 'ar' as Lang, flag: '🇸🇦', label: 'العربية' },
                { code: 'am' as Lang, flag: '🇪🇹', label: 'አማርኛ' },
              ]).map(opt => (
                <button
                  key={opt.code}
                  onClick={() => setLang(opt.code)}
                  className={[
                    'flex flex-col items-center gap-1 px-3 py-3 rounded-xl text-sm font-medium border transition-all cursor-pointer',
                    lang === opt.code
                      ? 'bg-indigo-500 text-white border-indigo-500 shadow-sm'
                      : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100',
                  ].join(' ')}
                >
                  <span className="text-2xl">{opt.flag}</span>
                  <span className="text-xs">{opt.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Progress preview */}
          <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-5 mb-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-gray-700">{t('step_of', lang, completedCount, steps.length - 1)}</span>
              <span className="text-sm font-medium text-indigo-600">{progressPct}%</span>
            </div>
            <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-indigo-500 to-cyan-500 rounded-full transition-all"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>

          <button
            onClick={() => setStarted(true)}
            className="w-full flex items-center justify-center gap-2 px-4 py-4 rounded-2xl text-base font-semibold text-white shadow-lg cursor-pointer transition-all hover:opacity-90 active:scale-[0.98]"
            style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
          >
            {t('get_started', lang)}
            <ChevronRight className="w-5 h-5" />
          </button>
        </motion.div>
      </div>
    )
  }

  /* ── What Happens Next interstitial ── */
  if (showWhatNext) {
    const whnSteps = [
      { titleKey: 'whn_step1_title', bodyKey: 'whn_step1_body', icon: '📧' },
      { titleKey: 'whn_step2_title', bodyKey: 'whn_step2_body', icon: '✍️' },
      { titleKey: 'whn_step3_title', bodyKey: 'whn_step3_body', icon: '🔔' },
      { titleKey: 'whn_step4_title', bodyKey: 'whn_step4_body', icon: '🧪' },
      { titleKey: 'whn_step5_title', bodyKey: 'whn_step5_body', icon: '🚗' },
    ] as const

    return (
      <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-cyan-50 flex items-center justify-center px-4 py-10" dir={isRTL ? 'rtl' : 'ltr'}>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="max-w-lg w-full"
        >
          {/* Header */}
          <div className="text-center mb-6">
            <div
              className="w-16 h-16 rounded-full mx-auto mb-4 flex items-center justify-center shadow-lg"
              style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
            >
              <CheckCircle2 className="w-8 h-8 text-white" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900">{t('whn_title', lang)}</h1>
            <p className="text-gray-500 text-sm mt-1">{t('whn_subtitle', lang)}</p>
          </div>

          {/* Steps */}
          <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-5 mb-5 space-y-5">
            {whnSteps.map((step, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: isRTL ? 12 : -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.07 }}
                className="flex gap-3"
              >
                <div className="flex-shrink-0 w-9 h-9 rounded-full bg-indigo-50 border border-indigo-100 flex items-center justify-center text-lg">
                  {step.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-900 mb-0.5">
                    {i + 1}. {t(step.titleKey as keyof typeof S, lang)}
                  </p>
                  <p className="text-sm text-gray-500 leading-relaxed">
                    {t(step.bodyKey as keyof typeof S, lang)}
                  </p>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Footer note */}
          <p className="text-center text-xs text-gray-400 mb-5 px-2">{t('whn_footer', lang)}</p>

          {/* CTA */}
          <button
            onClick={() => setShowWhatNext(false)}
            className="w-full flex items-center justify-center gap-2 px-4 py-4 rounded-2xl text-base font-semibold text-white shadow-lg cursor-pointer transition-all hover:opacity-90 active:scale-[0.98]"
            style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
          >
            {t('whn_got_it', lang)}
          </button>
        </motion.div>
      </div>
    )
  }

  /* ── Portal flow ── */
  return (
    <div className="min-h-screen bg-gray-50" dir={isRTL ? 'rtl' : 'ltr'}>
      {/* Top bar */}
      <div className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-lg mx-auto px-4 py-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">
              {isAllDone ? t('complete_title', lang) : t('step_of', lang, completedCount, steps.length - 1)}
            </span>
            <span className="text-sm font-semibold text-indigo-600">{progressPct}%</span>
          </div>
          <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-gradient-to-r from-indigo-500 to-cyan-500 rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${progressPct}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </div>
      </div>

      {/* Steps */}
      <div className="max-w-lg mx-auto px-4 py-6 space-y-3">
        <AnimatePresence>
          {isAllDone ? (
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="rounded-2xl border-2 border-emerald-300 bg-emerald-50 p-8 text-center"
            >
              <div className="w-16 h-16 rounded-full bg-emerald-500 flex items-center justify-center mx-auto mb-4">
                <CheckCircle2 className="w-8 h-8 text-white" />
              </div>
              <h2 className="text-2xl font-bold text-emerald-700 mb-2">{t('complete_title', lang)}</h2>
              <p className="text-emerald-600 text-sm leading-relaxed">{t('complete_body', lang)}</p>
            </motion.div>
          ) : (
            steps.map((step, i) => {
              const isCurrent = i === currentIdx
              const done = isDone(step.status)

              if (i === steps.length - 1) return null // 'complete' is handled above

              const guidanceKey = guidanceMap[step.key] as keyof typeof S['step_guidance'] | undefined
              const guidance = step.key === 'personal_info'
                ? tGuidance('personal_info', lang)
                : guidanceKey ? tGuidance(guidanceKey, lang) : ''

              return (
                <StepCard
                  key={step.key}
                  number={i + 1}
                  title={tStepTitle(i, lang)}
                  guidance={guidance}
                  status={step.status}
                  lang={lang}
                  isCurrent={isCurrent}
                >
                  {/* Personal info step gets an inline form */}
                  {step.key === 'personal_info' && isCurrent && !done && (
                    <PersonalInfoForm
                      record={record}
                      lang={lang}
                      token={token}
                      onSaved={updated => { setRecord(updated); setShowWhatNext(true) }}
                    />
                  )}
                </StepCard>
              )
            })
          )}
        </AnimatePresence>
      </div>

      {/* Footer */}
      <div className="max-w-lg mx-auto px-4 pb-8 text-center">
        <p className="text-xs text-gray-400">MAZ Services · Driver Onboarding Portal</p>
      </div>
    </div>
  )
}
