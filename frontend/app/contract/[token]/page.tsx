'use client'

import { use, useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { CheckCircle2, Globe, Loader2, FileText, Shield, AlertTriangle } from 'lucide-react'

/* ─── Types ──────────────────────────────────────────────────────────── */

type Lang = 'en' | 'ar' | 'am'

interface JoinRecord {
  person_name: string | null
  person?: { full_name: string; language: string | null }
}

/* ─── Translations ───────────────────────────────────────────────────── */

const T: Record<string, Record<Lang, string>> = {
  page_title: {
    en: 'MAZ SERVICES LLC',
    ar: 'شركة ماز للخدمات ذ.م.م',
    am: 'ማዝ ሰርቪስ ኤል.ኤል.ሲ',
  },
  agreement_title: {
    en: 'INDEPENDENT DRIVER AGREEMENT',
    ar: 'اتفاقية السائق المستقل',
    am: 'ነፃ የሹፌር ስምምነት',
  },
  effective_date: {
    en: 'Effective Date',
    ar: 'تاريخ السريان',
    am: 'ተፈጻሚ ቀን',
  },
  driver_name: {
    en: 'Driver',
    ar: 'السائق',
    am: 'ሹፌር',
  },

  /* Section 1 — Payment */
  s1_title: {
    en: '1. Payment Terms',
    ar: '1. شروط الدفع',
    am: '1. የክፍያ ውሎች',
  },
  s1_classification: {
    en: 'The Driver is classified as an independent contractor and is not an employee of MAZ Services LLC.',
    ar: 'يُصنَّف السائق كمقاول مستقل وليس موظفاً في شركة ماز للخدمات ذ.م.م.',
    am: 'ሹፌሩ ነፃ ተቋራጭ ሲሆን የማዝ ሰርቪስ ኤል.ኤል.ሲ ሰራተኛ አይደለም።',
  },
  s1_weekly: {
    en: 'Payment is issued on a weekly basis.',
    ar: 'يتم إصدار الدفع على أساس أسبوعي.',
    am: 'ክፍያ በየሳምንቱ ይከፈላል።',
  },
  s1_delay: {
    en: 'Payment runs two (2) weeks behind completed work. First Alt remits payment to MAZ Services weekly. MAZ Services requires one (1) week to process and distribute driver payments. As a result, the Driver\'s first payment will be issued approximately two (2) weeks after their first completed ride.',
    ar: 'يتأخر الدفع أسبوعين (2) عن العمل المنجز. ترسل First Alt الدفع إلى خدمات ماز أسبوعياً. تحتاج خدمات ماز أسبوعاً واحداً (1) لمعالجة وتوزيع مدفوعات السائقين. ونتيجة لذلك، سيتم إصدار أول دفعة للسائق بعد حوالي أسبوعين (2) من أول رحلة مكتملة.',
    am: 'ክፍያ ከተጠናቀቀ ስራ ሁለት (2) ሳምንት ይዘገያል። First Alt ክፍያን ለማዝ ሰርቪስ በየሳምንቱ ያስተላልፋል። ማዝ ሰርቪስ የሾፌሮችን ክፍያ ለማዘጋጀት እና ለማከፋፈል አንድ (1) ሳምንት ይፈልጋል። በዚህ ምክንያት የሹፌሩ የመጀመሪያ ክፍያ ከመጀመሪያው ተጠናቅቆ ከቀረ ጉዞ ከሁለት (2) ሳምንት በኋላ ይሰጣል።',
  },
  s1_paychex: {
    en: 'All payments are processed through Paychex payroll services.',
    ar: 'تتم معالجة جميع المدفوعات من خلال خدمات رواتب Paychex.',
    am: 'ሁሉም ክፍያዎች በPaychex የደመወዝ አገልግሎት ይከናወናሉ።',
  },

  /* Section 2 — Operating Procedures */
  s2_title: {
    en: '2. Operating Procedures',
    ar: '2. إجراءات التشغيل',
    am: '2. የአሰራር ሂደቶች',
  },
  s2_vest: {
    en: 'Driver must wear a safety vest during all pickups and drop-offs.',
    ar: 'يجب على السائق ارتداء سترة السلامة أثناء جميع عمليات الإنزال والتحميل.',
    am: 'ሹፌሩ ሁሉም ማንሳትና ማውረድ ጊዜ የደህንነት ቦዲ ማድረግ አለበት።',
  },
  s2_plaque: {
    en: 'Driver must display the MAZ Services identification plaque on their vehicle at all times during active service.',
    ar: 'يجب على السائق عرض لوحة تعريف خدمات ماز على مركبته في جميع الأوقات أثناء الخدمة الفعلية.',
    am: 'ሹፌሩ በንቁ አገልግሎት ጊዜ ሁሉ የማዝ ሰርቪስ መታወቂያ ምልክት በተሽከርካሪው ላይ ማሳየት አለበት።',
  },
  s2_wait: {
    en: 'Driver must wait a minimum of ten (10) minutes at the pickup location before marking a ride as "no-load."',
    ar: 'يجب على السائق الانتظار عشر (10) دقائق على الأقل في موقع التحميل قبل تسجيل الرحلة كـ"بدون حمولة".',
    am: 'ሹፌሩ ጉዞን "ባዶ-ጭነት" ብሎ ከመመዝገቡ በፊት ቢያንስ አስር (10) ደቂቃ መጠበቅ አለበት።',
  },
  s2_first_pickup: {
    en: 'For first-time pickups at a new address, Driver must contact dispatch to notify the guardian.',
    ar: 'لعمليات التحميل لأول مرة في عنوان جديد، يجب على السائق الاتصال بالإرسال لإخطار ولي الأمر.',
    am: 'በአዲስ አድራሻ ለመጀመሪያ ጊዜ ሲያነሳ ሹፌሩ አስተባባሪን ማሳወቅ አለበት።',
  },
  s2_dispatch: {
    en: 'Driver must follow all instructions from dispatch and maintain professional conduct at all times.',
    ar: 'يجب على السائق اتباع جميع تعليمات الإرسال والحفاظ على السلوك المهني في جميع الأوقات.',
    am: 'ሹፌሩ ከአስተባባሪ የሚመጡ ሁሉንም መመሪያዎች መከተል እና ሁልጊዜ ሙያዊ ባህሪ ማሳየት አለበት።',
  },
  s2_vehicle: {
    en: 'Driver is responsible for maintaining their vehicle in safe operating condition.',
    ar: 'السائق مسؤول عن صيانة مركبته في حالة تشغيل آمنة.',
    am: 'ሹፌሩ ተሽከርካሪውን በደህና የአሰራር ሁኔታ ለመጠበቅ ኃላፊነት አለበት።',
  },

  /* Section 3 — Student Transport Safety */
  s3_title: {
    en: '3. Student Transport Safety',
    ar: '3. سلامة نقل الطلاب',
    am: '3. የተማሪ ማጓጓዝ ደህንነት',
  },
  s3_seatbelt: {
    en: 'Driver must ensure students are safely seated with seatbelts before departing.',
    ar: 'يجب على السائق التأكد من جلوس الطلاب بأمان مع ربط أحزمة الأمان قبل المغادرة.',
    am: 'ሹፌሩ ከመነሳቱ በፊት ተማሪዎች በደህና ቀበቶ ታስረው መቀመጣቸውን ማረጋገጥ አለበት።',
  },
  s3_phone: {
    en: 'No use of personal phone while transporting students.',
    ar: 'يُمنع استخدام الهاتف الشخصي أثناء نقل الطلاب.',
    am: 'ተማሪዎችን ሲያጓጉዙ የግል ስልክ መጠቀም አይፈቀድም።',
  },
  s3_route: {
    en: 'Driver must follow designated routes and report any safety concerns to dispatch immediately.',
    ar: 'يجب على السائق اتباع المسارات المحددة والإبلاغ عن أي مخاوف تتعلق بالسلامة إلى الإرسال فوراً.',
    am: 'ሹፌሩ የተመደቡ መንገዶችን መከተል እና ማንኛውንም የደህንነት ስጋት ወዲያውኑ ለአስተባባሪ ማሳወቅ አለበት።',
  },
  s3_conduct: {
    en: 'Professional and respectful behavior toward all students and guardians at all times.',
    ar: 'سلوك مهني ومحترم تجاه جميع الطلاب وأولياء الأمور في جميع الأوقات.',
    am: 'ሁልጊዜ ለሁሉም ተማሪዎች እና አሳዳጊዎች ሙያዊ እና ያከበረ ባህሪ።',
  },

  /* Section 4 — Non-Compete */
  s4_title: {
    en: '4. Non-Compete Agreement',
    ar: '4. اتفاقية عدم المنافسة',
    am: '4. ያለመወዳደር ስምምነት',
  },
  s4_intro: {
    en: 'During the term of this agreement and for a period of twelve (12) months following termination, the Driver agrees not to:',
    ar: 'خلال مدة هذه الاتفاقية ولمدة اثني عشر (12) شهراً بعد الإنهاء، يوافق السائق على عدم:',
    am: 'በዚህ ስምምነት ጊዜ እና ከማቋረጥ በኋላ ለአስራ ሁለት (12) ወራት ሹፌሩ የሚከተሉትን ላለማድረግ ይስማማል:',
  },
  s4_direct: {
    en: 'Enter into a direct service provider agreement with First Alt Transportation or any of its subsidiaries.',
    ar: 'الدخول في اتفاقية مزود خدمة مباشر مع First Alt Transportation أو أي من شركاتها التابعة.',
    am: 'ከFirst Alt Transportation ወይም ከማንኛውም ንዑስ ድርጅቶቹ ጋር ቀጥተኛ የአገልግሎት ሰጪ ስምምነት መግባት።',
  },
  s4_solicit: {
    en: 'Solicit or accept direct contracts from clients, schools, or districts currently served through MAZ Services.',
    ar: 'طلب أو قبول عقود مباشرة من العملاء أو المدارس أو المناطق التي تخدمها خدمات ماز حالياً.',
    am: 'በአሁኑ ጊዜ በማዝ ሰርቪስ በኩል ከሚገለገሉ ደንበኞች፣ ትምህርት ቤቶች ወይም ዲስትሪክቶች ቀጥተኛ ውል መጠየቅ ወይም መቀበል።',
  },
  s4_proprietary: {
    en: 'Use proprietary route information, client contacts, or business processes obtained through MAZ Services.',
    ar: 'استخدام معلومات المسارات الخاصة أو جهات اتصال العملاء أو العمليات التجارية التي تم الحصول عليها من خلال خدمات ماز.',
    am: 'በማዝ ሰርቪስ በኩል የተገኙ የባለቤትነት መንገድ መረጃዎችን፣ የደንበኛ ግንኙነቶችን ወይም የንግድ ሂደቶችን መጠቀም።',
  },

  /* Section 5 — Termination */
  s5_title: {
    en: '5. Termination',
    ar: '5. الإنهاء',
    am: '5. ማቋረጥ',
  },
  s5_notice: {
    en: 'Either party may terminate this agreement with seven (7) days written notice.',
    ar: 'يجوز لأي طرف إنهاء هذه الاتفاقية بإشعار خطي قبل سبعة (7) أيام.',
    am: 'ማንኛውም ወገን ይህን ስምምነት በሰባት (7) ቀናት የጽሁፍ ማስታወቂያ ሊያቋርጥ ይችላል።',
  },
  s5_cause: {
    en: 'MAZ Services reserves the right to immediately terminate for cause, including but not limited to: safety violations, failure to appear for assigned routes, unprofessional conduct, or breach of this agreement.',
    ar: 'تحتفظ خدمات ماز بالحق في الإنهاء الفوري لسبب، بما في ذلك على سبيل المثال لا الحصر: انتهاكات السلامة، عدم الحضور للمسارات المعينة، السلوك غير المهني، أو خرق هذه الاتفاقية.',
    am: 'ማዝ ሰርቪስ ለምክንያት ወዲያውኑ የማቋረጥ መብቱ የተጠበቀ ነው፣ ይህም ያለገደብ የደህንነት ጥሰቶችን፣ ለተመደቡ መንገዶች አለመቅረብን፣ ኢሙያዊ ባህሪን ወይም የዚህን ስምምነት ጥሰት ያካትታል።',
  },

  /* Section 6 — Acknowledgment */
  s6_title: {
    en: '6. Acknowledgment',
    ar: '6. الإقرار',
    am: '6. ማረጋገጫ',
  },
  s6_read: {
    en: 'By signing below, the Driver acknowledges that they have read and understood all terms of this agreement.',
    ar: 'بالتوقيع أدناه، يقر السائق بأنه قد قرأ وفهم جميع شروط هذه الاتفاقية.',
    am: 'ከዚህ በታች በመፈረም ሹፌሩ የዚህን ስምምነት ሁሉንም ውሎች ማንበቡን እና መረዳቱን ያረጋግጣል።',
  },
  s6_comply: {
    en: 'The Driver agrees to comply with all operating procedures described herein.',
    ar: 'يوافق السائق على الالتزام بجميع إجراءات التشغيل الموضحة في هذه الوثيقة.',
    am: 'ሹፌሩ በዚህ ሰነድ ውስጥ የተገለጹትን ሁሉንም የአሰራር ሂደቶች ለመከተል ይስማማል።',
  },
  s6_understand: {
    en: 'The Driver understands the payment schedule and non-compete terms.',
    ar: 'يفهم السائق جدول الدفع وشروط عدم المنافسة.',
    am: 'ሹፌሩ የክፍያ መርሃ ግብሩን እና ያለመወዳደር ውሎችን ይረዳል።',
  },

  /* Signature area */
  sig_agreement: {
    en: 'I, {name}, agree to all terms above.',
    ar: 'أنا، {name}، أوافق على جميع الشروط المذكورة أعلاه.',
    am: 'እኔ, {name}, ከላይ ለተጠቀሱት ሁሉም ውሎች እስማማለሁ።',
  },
  sig_type_name: {
    en: 'Type your full legal name to sign',
    ar: 'اكتب اسمك القانوني الكامل للتوقيع',
    am: 'ለመፈረም ሙሉ ህጋዊ ስምዎን ይጻፉ',
  },
  sig_button: {
    en: 'Sign Agreement',
    ar: 'توقيع الاتفاقية',
    am: 'ስምምነቱን ፈርም',
  },
  sig_date: {
    en: 'Date',
    ar: 'التاريخ',
    am: 'ቀን',
  },
  sig_signing: {
    en: 'Signing...',
    ar: 'جارٍ التوقيع...',
    am: 'በመፈረም ላይ...',
  },

  /* States */
  loading: {
    en: 'Loading agreement...',
    ar: 'جارٍ تحميل الاتفاقية...',
    am: 'ስምምነት በመጫን ላይ...',
  },
  error_load: {
    en: 'Could not load your agreement. Please try again or contact dispatch.',
    ar: 'تعذر تحميل اتفاقيتك. يرجى المحاولة مرة أخرى أو الاتصال بالإرسال.',
    am: 'ስምምነትዎን መጫን አልተቻለም። እባክዎ እንደገና ይሞክሩ ወይም አስተባባሪን ያግኙ።',
  },
  error_sign: {
    en: 'Failed to submit signature. Please try again.',
    ar: 'فشل في تقديم التوقيع. يرجى المحاولة مرة أخرى.',
    am: 'ፊርማ ማስገባት አልተሳካም። እባክዎ እንደገና ይሞክሩ።',
  },
  success_title: {
    en: 'Agreement Signed',
    ar: 'تم توقيع الاتفاقية',
    am: 'ስምምነት ተፈርሟል',
  },
  success_body: {
    en: 'Your contract has been recorded. You may close this page.',
    ar: 'تم تسجيل عقدك. يمكنك إغلاق هذه الصفحة.',
    am: 'ውልዎ ተመዝግቧል። ይህን ገጽ መዝጋት ይችላሉ።',
  },
  name_mismatch: {
    en: 'Name must match: {name}',
    ar: 'يجب أن يتطابق الاسم: {name}',
    am: 'ስም መመሳሰል አለበት: {name}',
  },
}

/* ─── Helpers ─────────────────────────────────────────────────────────── */

function t(key: string, lang: Lang, vars?: Record<string, string>): string {
  let str = T[key]?.[lang] ?? T[key]?.en ?? key
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      str = str.replace(`{${k}}`, v)
    }
  }
  return str
}

function formatDate(lang: Lang): string {
  const d = new Date()
  if (lang === 'ar') {
    return d.toLocaleDateString('ar-SA', { year: 'numeric', month: 'long', day: 'numeric' })
  }
  if (lang === 'am') {
    return d.toLocaleDateString('am-ET', { year: 'numeric', month: 'long', day: 'numeric' })
  }
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
}

/* ─── Components ──────────────────────────────────────────────────────── */

function LanguageSelector({ lang, setLang }: { lang: Lang; setLang: (l: Lang) => void }) {
  const langs: { code: Lang; label: string; native: string }[] = [
    { code: 'en', label: 'English', native: 'English' },
    { code: 'ar', label: 'Arabic', native: 'العربية' },
    { code: 'am', label: 'Amharic', native: 'አማርኛ' },
  ]

  return (
    <div className="flex items-center justify-center gap-2">
      <Globe className="h-4 w-4 text-white/40" />
      <div className="flex gap-1 rounded-xl bg-white/[0.04] p-1">
        {langs.map((l) => (
          <button
            key={l.code}
            onClick={() => setLang(l.code)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-all duration-200 ${
              lang === l.code
                ? 'bg-gradient-to-r from-[#667eea] to-[#06b6d4] text-white shadow-lg shadow-[#667eea]/20'
                : 'text-white/50 hover:text-white/80 hover:bg-white/[0.06]'
            }`}
          >
            {l.native}
          </button>
        ))}
      </div>
    </div>
  )
}

function SectionHeader({ children, icon }: { children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 mb-3 mt-8 first:mt-0">
      {icon && <div className="mt-0.5 text-[#667eea]">{icon}</div>}
      <h2 className="text-base font-semibold text-white tracking-tight">{children}</h2>
    </div>
  )
}

function Clause({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-1.5">
      <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#667eea]/60" />
      <p className="text-sm leading-relaxed text-white/70">{children}</p>
    </div>
  )
}

function HighlightClause({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-1.5">
      <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400/80" />
      <p className="text-sm leading-relaxed text-white font-medium">{children}</p>
    </div>
  )
}

function NonCompeteItem({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-1 pl-4">
      <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-red-400/70" />
      <p className="text-sm leading-relaxed text-white/80">{children}</p>
    </div>
  )
}

/* ─── Main Page ───────────────────────────────────────────────────────── */

export default function ContractPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params)
  const [lang, setLang] = useState<Lang>('en')
  const [record, setRecord] = useState<JoinRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [typedName, setTypedName] = useState('')
  const [signing, setSigning] = useState(false)
  const [signed, setSigned] = useState(false)
  const [signError, setSignError] = useState<string | null>(null)

  const isRtl = lang === 'ar'
  const driverName = record?.person?.full_name ?? record?.person_name ?? 'Driver'

  /* Load record */
  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/join/${token}`)
      .then((r) => {
        if (!r.ok) throw new Error('Failed to load')
        return r.json()
      })
      .then((data) => {
        setRecord(data)
        if (data?.person?.language === 'ar') setLang('ar')
        else if (data?.person?.language === 'am') setLang('am')
      })
      .catch(() => setError('error_load'))
      .finally(() => setLoading(false))
  }, [token])

  /* Sign handler */
  const handleSign = useCallback(async () => {
    if (signing || signed) return
    const nameNorm = typedName.trim().toLowerCase()
    const expectedNorm = driverName.toLowerCase()
    if (nameNorm !== expectedNorm) return

    setSigning(true)
    setSignError(null)

    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/join/${token}/step`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          step: 'maz_contract',
          signed: true,
          name: typedName.trim(),
          signed_at: new Date().toISOString(),
        }),
      })
      if (!res.ok) throw new Error('Failed')
      setSigned(true)
    } catch {
      setSignError('error_sign')
    } finally {
      setSigning(false)
    }
  }, [signing, signed, typedName, driverName, token])

  const nameMatch =
    typedName.trim().toLowerCase() === driverName.toLowerCase() && typedName.trim().length > 0

  /* Loading state */
  if (loading) {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center px-4">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex flex-col items-center gap-4"
        >
          <Loader2 className="h-8 w-8 text-[#667eea] animate-spin" />
          <p className="text-white/50 text-sm">{t('loading', lang)}</p>
        </motion.div>
      </div>
    )
  }

  /* Error state */
  if (error) {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center px-4">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center max-w-sm"
        >
          <AlertTriangle className="h-10 w-10 text-red-400 mx-auto mb-4" />
          <p className="text-white/70 text-sm">{t('error_load', lang)}</p>
        </motion.div>
      </div>
    )
  }

  /* Success state */
  if (signed) {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center px-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ type: 'spring', stiffness: 200, damping: 20 }}
          className="text-center max-w-sm"
        >
          <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500/10">
            <CheckCircle2 className="h-8 w-8 text-emerald-400" />
          </div>
          <h1 className="text-xl font-semibold text-white mb-2">{t('success_title', lang)}</h1>
          <p className="text-white/60 text-sm">{t('success_body', lang)}</p>
        </motion.div>
      </div>
    )
  }

  /* ─── Contract ─────────────────────────────────────────────────────── */

  return (
    <div className="min-h-screen bg-[#09090b]" dir={isRtl ? 'rtl' : 'ltr'}>
      {/* Top bar */}
      <div className="sticky top-0 z-20 bg-[#09090b]/90 backdrop-blur-xl border-b border-white/[0.06]">
        <div className="max-w-lg mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-[#667eea]" />
            <span className="text-xs font-medium text-white/50 uppercase tracking-wider">
              Contract
            </span>
          </div>
          <LanguageSelector lang={lang} setLang={setLang} />
        </div>
      </div>

      {/* Contract body */}
      <div className="max-w-lg mx-auto px-4 pt-6 pb-52">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          {/* Header */}
          <div className="rounded-2xl bg-white/[0.03] border border-white/10 p-6 mb-4">
            <div className="text-center mb-6">
              <h1 className="text-lg font-bold text-white tracking-tight mb-1">
                {t('page_title', lang)}
              </h1>
              <div className="h-px w-16 mx-auto bg-gradient-to-r from-transparent via-[#667eea] to-transparent mb-3" />
              <p className="text-sm font-semibold text-[#667eea]">
                {t('agreement_title', lang)}
              </p>
            </div>

            <div className="flex justify-between text-xs text-white/50 border-t border-white/[0.06] pt-4">
              <div>
                <span className="text-white/30">{t('effective_date', lang)}:</span>{' '}
                <span className="text-white/70">{formatDate(lang)}</span>
              </div>
              <div>
                <span className="text-white/30">{t('driver_name', lang)}:</span>{' '}
                <span className="text-white/70">{driverName}</span>
              </div>
            </div>
          </div>

          {/* Sections */}
          <div className="rounded-2xl bg-white/[0.03] border border-white/10 p-6">

            {/* 1 — Payment */}
            <SectionHeader>{t('s1_title', lang)}</SectionHeader>
            <Clause>{t('s1_classification', lang)}</Clause>
            <Clause>{t('s1_weekly', lang)}</Clause>
            <HighlightClause>{t('s1_delay', lang)}</HighlightClause>
            <Clause>{t('s1_paychex', lang)}</Clause>

            {/* 2 — Operating Procedures */}
            <SectionHeader>{t('s2_title', lang)}</SectionHeader>
            <Clause>{t('s2_vest', lang)}</Clause>
            <Clause>{t('s2_plaque', lang)}</Clause>
            <Clause>{t('s2_wait', lang)}</Clause>
            <Clause>{t('s2_first_pickup', lang)}</Clause>
            <Clause>{t('s2_dispatch', lang)}</Clause>
            <Clause>{t('s2_vehicle', lang)}</Clause>

            {/* 3 — Student Safety */}
            <SectionHeader>{t('s3_title', lang)}</SectionHeader>
            <Clause>{t('s3_seatbelt', lang)}</Clause>
            <Clause>{t('s3_phone', lang)}</Clause>
            <Clause>{t('s3_route', lang)}</Clause>
            <Clause>{t('s3_conduct', lang)}</Clause>

            {/* 4 — Non-Compete (prominent) */}
            <div className="mt-8 -mx-6 px-6 py-5 bg-red-500/[0.06] border-y border-red-500/20">
              <div className="flex items-start gap-3 mb-3">
                <Shield className="h-5 w-5 text-red-400 mt-0.5 shrink-0" />
                <h2 className="text-base font-semibold text-red-300 tracking-tight">
                  {t('s4_title', lang)}
                </h2>
              </div>
              <p className="text-sm leading-relaxed text-white/80 mb-3 font-medium">
                {t('s4_intro', lang)}
              </p>
              <NonCompeteItem>{t('s4_direct', lang)}</NonCompeteItem>
              <NonCompeteItem>{t('s4_solicit', lang)}</NonCompeteItem>
              <NonCompeteItem>{t('s4_proprietary', lang)}</NonCompeteItem>
            </div>

            {/* 5 — Termination */}
            <SectionHeader>{t('s5_title', lang)}</SectionHeader>
            <Clause>{t('s5_notice', lang)}</Clause>
            <HighlightClause>{t('s5_cause', lang)}</HighlightClause>

            {/* 6 — Acknowledgment */}
            <SectionHeader>{t('s6_title', lang)}</SectionHeader>
            <Clause>{t('s6_read', lang)}</Clause>
            <Clause>{t('s6_comply', lang)}</Clause>
            <Clause>{t('s6_understand', lang)}</Clause>
          </div>
        </motion.div>
      </div>

      {/* ─── Sticky Signature Area ───────────────────────────────────── */}
      <div className="fixed bottom-0 inset-x-0 z-30">
        <div className="h-8 bg-gradient-to-t from-[#09090b] to-transparent pointer-events-none" />
        <div className="bg-[#09090b]/95 backdrop-blur-xl border-t border-white/[0.08]">
          <div className="max-w-lg mx-auto px-4 py-4">
            <AnimatePresence mode="wait">
              {signError && (
                <motion.p
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="text-xs text-red-400 mb-2 text-center"
                >
                  {t('error_sign', lang)}
                </motion.p>
              )}
            </AnimatePresence>

            <p className="text-xs text-white/40 mb-3 text-center">
              {t('sig_agreement', lang, { name: driverName })}
            </p>

            <div className="flex flex-col gap-3">
              <div className="relative">
                <input
                  type="text"
                  value={typedName}
                  onChange={(e) => setTypedName(e.target.value)}
                  placeholder={t('sig_type_name', lang)}
                  className={`w-full rounded-xl bg-white/[0.05] border px-4 py-3 text-sm text-white
                    placeholder:text-white/25 outline-none transition-all duration-200
                    ${nameMatch
                      ? 'border-emerald-500/50 bg-emerald-500/[0.05]'
                      : typedName.length > 0
                        ? 'border-amber-500/30'
                        : 'border-white/10'
                    }
                    focus:border-[#667eea]/50 focus:ring-1 focus:ring-[#667eea]/20`}
                  dir={isRtl ? 'rtl' : 'ltr'}
                />
                {typedName.length > 0 && !nameMatch && (
                  <p className="text-[11px] text-amber-400/70 mt-1.5 px-1">
                    {t('name_mismatch', lang, { name: driverName })}
                  </p>
                )}
              </div>

              <div className="flex items-center justify-between text-xs text-white/30 px-1">
                <span>{t('sig_date', lang)}: {formatDate(lang)}</span>
              </div>

              <motion.button
                whileTap={{ scale: 0.98 }}
                disabled={!nameMatch || signing}
                onClick={handleSign}
                className={`w-full rounded-xl py-3.5 text-sm font-semibold text-white transition-all duration-200
                  ${nameMatch && !signing
                    ? 'bg-gradient-to-r from-[#667eea] to-[#06b6d4] shadow-lg shadow-[#667eea]/20 active:shadow-none'
                    : 'bg-white/[0.06] text-white/30 cursor-not-allowed'
                  }`}
              >
                {signing ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t('sig_signing', lang)}
                  </span>
                ) : (
                  t('sig_button', lang)
                )}
              </motion.button>
            </div>
          </div>

          {/* Safe area padding for notch devices */}
          <div className="h-[env(safe-area-inset-bottom)]" />
        </div>
      </div>
    </div>
  )
}
