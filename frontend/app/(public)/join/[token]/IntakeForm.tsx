'use client'

import { useState, useRef } from 'react'
import { motion } from 'framer-motion'
import { Loader2, Upload, CheckCircle2 } from 'lucide-react'

/* ─── Types ──────────────────────────────────────────────────────────── */

export type Lang = 'en' | 'ar' | 'am'

interface IntakeFormProps {
  token: string
  initialLang?: Lang
  prefill?: { full_name?: string; phone?: string; email?: string }
  onComplete: (data: Record<string, unknown>) => void
  /** When provided, bypasses the internal API call and delegates submission to the parent.
   *  Should return { onboarding_id } so the form can upload the DL file. */
  overrideSubmit?: (values: Record<string, string>) => Promise<{ onboarding_id?: number } | void>
}

/* ─── Translations ───────────────────────────────────────────────────── */

const T: Record<string, Record<Lang, string>> = {
  stepLabel:    { en: 'Step 1 of 11 — Your Information', ar: 'الخطوة 1 من 11 — معلوماتك', am: 'ደረጃ 1 ከ 11 — መረጃዎ' },
  header:       { en: "Let's get you started", ar: 'هيا نبدأ', am: 'እንጀምር' },
  subtitle:     { en: 'Fill in your info below', ar: 'املأ معلوماتك أدناه', am: 'ከዚህ በታች መረጃዎን ይሙሉ' },
  fullName:     { en: 'Full Name', ar: 'الاسم الكامل', am: 'ሙሉ ስም' },
  phone:        { en: 'Phone Number', ar: 'رقم الهاتف', am: 'ስልክ ቁጥር' },
  email:        { en: 'Email', ar: 'البريد الإلكتروني', am: 'ኢሜይል' },
  address:      { en: 'Home Address', ar: 'عنوان المنزل', am: 'የቤት አድራሻ' },
  dlNumber:     { en: "Driver's License Number", ar: 'رقم رخصة القيادة', am: 'የመንጃ ፈቃድ ቁጥር' },
  vehicleSection: { en: 'Vehicle Information', ar: 'معلومات السيارة', am: 'የተሽከርካሪ መረጃ' },
  vehicleMake:  { en: 'Make', ar: 'الشركة المصنعة', am: 'አምራች' },
  vehicleModel: { en: 'Model', ar: 'الموديل', am: 'ሞዴል' },
  vehicleYear:  { en: 'Year', ar: 'السنة', am: 'ዓመት' },
  vehiclePlate: { en: 'License Plate', ar: 'لوحة الترخيص', am: 'ሰሌዳ ቁጥር' },
  vehicleColor: { en: 'Color', ar: 'اللون', am: 'ቀለም' },
  emergencySection: { en: 'Emergency Contact', ar: 'جهة اتصال الطوارئ', am: 'የአደጋ ጊዜ ተገናኝ' },
  emergencyName:  { en: 'Contact Name', ar: 'اسم جهة الاتصال', am: 'የተገናኝ ስም' },
  emergencyPhone: { en: 'Contact Phone', ar: 'هاتف جهة الاتصال', am: 'የተገናኝ ስልክ' },
  submit:       { en: 'Start Onboarding', ar: 'ابدأ التأهيل', am: 'መግቢያ ይጀምሩ' },
  submitting:   { en: 'Submitting...', ar: 'جاري التقديم...', am: 'በማስገባት ላይ...' },
  required:     { en: 'Required', ar: 'مطلوب', am: 'ያስፈልጋል' },
  invalidEmail: { en: 'Invalid email', ar: 'بريد إلكتروني غير صالح', am: 'ልክ ያልሆነ ኢሜይል' },
  invalidPhone: { en: 'Invalid phone', ar: 'رقم هاتف غير صالح', am: 'ልክ ያልሆነ ስልክ' },
  invalidYear:  { en: 'Invalid year', ar: 'سنة غير صالحة', am: 'ልክ ያልሆነ ዓመት' },
  error:        { en: 'Something went wrong. Please try again.', ar: 'حدث خطأ. يرجى المحاولة مرة أخرى.', am: 'ችግር ተፈጥሯል። እባክዎ እንደገና ይሞክሩ።' },
  dlPhoto:      { en: "Driver's License Photo", ar: 'صورة رخصة القيادة', am: 'የመንጃ ፈቃድ ፎቶ' },
  dlPhotoHint:  { en: 'Required for background check. Take a clear photo of the front.', ar: 'مطلوب لفحص الخلفية. التقط صورة واضحة للوجه الأمامي.', am: 'ለዳራ ምርመራ ያስፈልጋል። የፊቱን ግልፅ ፎቶ ይውሰዱ።' },
  dlPhotoBtn:   { en: 'Tap to upload photo', ar: 'انقر لرفع الصورة', am: 'ፎቶ ለመስቀል ጠቅ ያድርጉ' },
  dlPhotoDone:  { en: 'Photo ready', ar: 'الصورة جاهزة', am: 'ፎቶ ዝግጁ ነው' },
}

const FLAGS: Record<Lang, string> = { en: '🇺🇸', ar: '🇸🇦', am: '🇪🇹' }

/* ─── Animation ──────────────────────────────────────────────────────── */

const fadeUp = {
  hidden: { opacity: 0, y: 16 },
  visible: (i: number) => ({
    opacity: 1, y: 0,
    transition: { delay: i * 0.08, duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] as [number, number, number, number] },
  }),
}

/* ─── Field keys ─────────────────────────────────────────────────────── */

type FieldKey = 'full_name' | 'phone' | 'email' | 'address' | 'drivers_license_number' |
  'vehicle_make' | 'vehicle_model' | 'vehicle_year' | 'vehicle_plate' | 'vehicle_color' |
  'emergency_name' | 'emergency_phone'

const LABEL_MAP: Record<FieldKey, keyof typeof T> = {
  full_name: 'fullName', phone: 'phone', email: 'email', address: 'address',
  drivers_license_number: 'dlNumber',
  vehicle_make: 'vehicleMake', vehicle_model: 'vehicleModel', vehicle_year: 'vehicleYear',
  vehicle_plate: 'vehiclePlate', vehicle_color: 'vehicleColor',
  emergency_name: 'emergencyName', emergency_phone: 'emergencyPhone',
}

/* ─── Component ──────────────────────────────────────────────────────── */

export default function IntakeForm({ token, initialLang = 'en', prefill, onComplete, overrideSubmit }: IntakeFormProps) {
  const isDev = token === 'dev'
  const [lang, setLang] = useState<Lang>(initialLang)
  const locked = {
    full_name: !!(prefill?.full_name),
    phone: !!(prefill?.phone),
    email: !!(prefill?.email),
  }
  const [values, setValues] = useState<Record<FieldKey, string>>({
    full_name: prefill?.full_name ?? '',
    phone: prefill?.phone ?? '',
    email: prefill?.email ?? '',
    address: '', drivers_license_number: '',
    vehicle_make: '', vehicle_model: '', vehicle_year: '', vehicle_plate: '', vehicle_color: '',
    emergency_name: '', emergency_phone: '',
  })
  const [errors, setErrors] = useState<Partial<Record<FieldKey, string>>>({})
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [dlFile, setDlFile] = useState<File | null>(null)
  const formRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const isRtl = lang === 'ar'

  const set = (key: FieldKey, val: string) => {
    setValues(prev => ({ ...prev, [key]: val }))
    if (errors[key]) setErrors(prev => { const n = { ...prev }; delete n[key]; return n })
  }

  const validate = (): boolean => {
    const errs: Partial<Record<FieldKey, string>> = {}
    const required: FieldKey[] = [
      'full_name', 'phone', 'email', 'address', 'drivers_license_number',
      'vehicle_make', 'vehicle_model', 'vehicle_year', 'vehicle_plate', 'vehicle_color',
      'emergency_name', 'emergency_phone',
    ]
    for (const k of required) {
      if (!values[k].trim()) errs[k] = T.required[lang]
    }
    if (values.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email)) errs.email = T.invalidEmail[lang]
    if (values.phone && values.phone.replace(/\D/g, '').length < 10) errs.phone = T.invalidPhone[lang]
    if (values.emergency_phone && values.emergency_phone.replace(/\D/g, '').length < 10) errs.emergency_phone = T.invalidPhone[lang]
    if (values.vehicle_year) {
      const yr = parseInt(values.vehicle_year)
      if (isNaN(yr) || yr < 1990 || yr > new Date().getFullYear() + 1) errs.vehicle_year = T.invalidYear[lang]
    }
    setErrors(errs)
    if (Object.keys(errs).length > 0) {
      const firstErr = formRef.current?.querySelector('[data-error]')
      firstErr?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      return false
    }
    return true
  }

  const uploadDL = async (onboarding_id: number, file: File) => {
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('file_type', 'drivers_license')
      await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/${onboarding_id}/upload`, {
        method: 'POST',
        body: fd,
      })
    } catch {
      // Non-blocking — continue even if DL upload fails
    }
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setSubmitting(true)
    setSubmitError('')
    try {
      let onboarding_id: number | undefined
      if (overrideSubmit) {
        const result = await overrideSubmit({ ...values, language: lang })
        onboarding_id = (result as { onboarding_id?: number } | void)?.onboarding_id
      } else {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/join/${token}/step`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ step: 'personal_info', data: { ...values, language: lang } }),
        })
        if (!res.ok) throw new Error('submit failed')
        const result = await res.json()
        onboarding_id = result?.id
      }
      if (dlFile && onboarding_id) {
        await uploadDL(onboarding_id, dlFile)
      }
      onComplete({})
    } catch {
      setSubmitError(T.error[lang])
      setSubmitting(false)
    }
  }

  const isLocked = (key: FieldKey): boolean => key in locked && locked[key as keyof typeof locked]

  const inputClass = (key: FieldKey) => {
    const base = 'w-full border rounded-xl px-4 py-3 min-h-[48px] placeholder-zinc-500 focus:outline-none transition-colors'
    if (isLocked(key)) return `${base} bg-white/3 border-white/5 text-zinc-500 cursor-not-allowed`
    return `${base} bg-white/5 ${errors[key] ? 'border-red-500/60' : 'border-white/10'} text-white focus:border-blue-500`
  }

  const renderField = (key: FieldKey, type: string = 'text', rows?: number) => (
    <div key={key} data-error={errors[key] ? '' : undefined}>
      <label className="flex items-center gap-1.5 text-sm font-medium text-zinc-300 mb-1.5">
        {T[LABEL_MAP[key]][lang]}
        {isLocked(key) && <span className="text-xs text-zinc-600 font-normal">(pre-filled)</span>}
      </label>
      {rows ? (
        <textarea className={inputClass(key)} rows={rows} value={values[key]}
          readOnly={isLocked(key)}
          onChange={e => !isLocked(key) && set(key, e.target.value)} dir={isRtl ? 'rtl' : 'ltr'} />
      ) : (
        <input type={type} className={inputClass(key)} value={values[key]}
          readOnly={isLocked(key)}
          onChange={e => !isLocked(key) && set(key, e.target.value)} dir={isRtl ? 'rtl' : 'ltr'}
          inputMode={type === 'tel' ? 'tel' : type === 'email' ? 'email' : type === 'number' ? 'numeric' : undefined} />
      )}
      {errors[key] && <p className="text-xs text-red-400 mt-1">{errors[key]}</p>}
    </div>
  )

  return (
    <div className={`min-h-screen bg-[#09090b] text-white ${isRtl ? 'rtl' : 'ltr'}`} dir={isRtl ? 'rtl' : 'ltr'}>
      <div className="max-w-md mx-auto px-4 py-8 pb-20" ref={formRef}>

        {/* DEV skip banner */}
        {isDev && (
          <div className="mb-6 flex items-center justify-between gap-3 px-4 py-3 rounded-xl bg-amber-500/10 border border-amber-500/30">
            <span className="text-xs text-amber-400 font-medium">Dev mode</span>
            <button
              onClick={() => onComplete({ dev: true })}
              className="px-3 py-1.5 rounded-lg bg-amber-500 text-white text-xs font-bold"
            >
              Skip Form →
            </button>
          </div>
        )}

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

        {/* Step label */}
        <motion.p className="text-center text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-4"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
          {T.stepLabel[lang]}
        </motion.p>

        {/* Header */}
        <motion.div className="text-center mb-10" initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.1 }}>
          <h1 className="text-2xl font-bold tracking-tight mb-1">{T.header[lang]}</h1>
          <p className="text-sm text-zinc-500 mt-2">{T.subtitle[lang]}</p>
        </motion.div>

        {/* Personal Info Fields */}
        <motion.div className="space-y-4 mb-8" variants={fadeUp} initial="hidden" animate="visible" custom={0}>
          {renderField('full_name')}
          {renderField('phone', 'tel')}
          {renderField('email', 'email')}
          {renderField('address', 'text', 2)}
          {renderField('drivers_license_number')}
        </motion.div>

        {/* Vehicle Section */}
        <motion.div className="mb-8" variants={fadeUp} initial="hidden" animate="visible" custom={1}>
          <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider mb-4">{T.vehicleSection[lang]}</h2>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              {renderField('vehicle_make')}
              {renderField('vehicle_model')}
            </div>
            <div className="grid grid-cols-3 gap-3">
              {renderField('vehicle_year', 'number')}
              {renderField('vehicle_plate')}
              {renderField('vehicle_color')}
            </div>
          </div>
        </motion.div>

        {/* Emergency Contact Section */}
        <motion.div className="mb-10" variants={fadeUp} initial="hidden" animate="visible" custom={2}>
          <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider mb-4">{T.emergencySection[lang]}</h2>
          <div className="space-y-4">
            {renderField('emergency_name')}
            {renderField('emergency_phone', 'tel')}
          </div>
        </motion.div>

        {/* DL Upload */}
        <motion.div className="mb-10" variants={fadeUp} initial="hidden" animate="visible" custom={3}>
          <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider mb-1">{T.dlPhoto[lang]}</h2>
          <p className="text-xs text-zinc-500 mb-3">{T.dlPhotoHint[lang]}</p>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,.pdf"
            capture="environment"
            className="hidden"
            onChange={e => setDlFile(e.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className={`w-full border-2 border-dashed rounded-xl px-4 py-5 flex items-center justify-center gap-3 transition-colors min-h-[64px]
              ${dlFile ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-white/10 bg-white/3 hover:border-white/20 hover:bg-white/5'}`}
          >
            {dlFile ? (
              <><CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" /><span className="text-sm text-emerald-300 font-medium truncate">{T.dlPhotoDone[lang]} — {dlFile.name}</span></>
            ) : (
              <><Upload className="w-5 h-5 text-zinc-400 shrink-0" /><span className="text-sm text-zinc-400">{T.dlPhotoBtn[lang]}</span></>
            )}
          </button>
        </motion.div>

        {/* Submit */}
        <motion.div variants={fadeUp} initial="hidden" animate="visible" custom={4}>
          <button onClick={handleSubmit} disabled={submitting}
            className="w-full px-6 py-3 min-h-[48px] rounded-xl bg-blue-500 hover:bg-blue-400 disabled:bg-blue-500/50 disabled:cursor-not-allowed text-white font-semibold transition-colors flex items-center justify-center gap-2">
            {submitting ? (
              <><Loader2 className="w-4 h-4 animate-spin" />{T.submitting[lang]}</>
            ) : (
              T.submit[lang]
            )}
          </button>
          {submitError && <p className="text-sm text-red-400 text-center mt-3">{submitError}</p>}
        </motion.div>

      </div>
    </div>
  )
}
