'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronRight, X, Phone } from 'lucide-react'

type Lang = 'en' | 'ar' | 'am'

const DRIVER_TOUR_KEY = 'zpay_driver_tour_v1'
const LANG_KEY = 'zpay_join_lang'

const LANGS: { code: Lang; flag: string; name: string; native: string }[] = [
  { code: 'en', flag: '🇺🇸', name: 'English', native: 'English' },
  { code: 'ar', flag: '🇸🇦', name: 'Arabic', native: 'العربية' },
  { code: 'am', flag: '🇪🇹', name: 'Amharic', native: 'አማርኛ' },
]

const T = {
  choose_lang: { en: 'Choose your language', ar: 'اختر لغتك', am: 'ቋንቋ ይምረጡ' },
  lang_subtitle: {
    en: 'All steps will be shown in your language',
    ar: 'ستظهر جميع الخطوات بلغتك',
    am: 'ሁሉም ደረጃዎች በቋንቋዎ ይታያሉ',
  },
  get_started: { en: 'Get Started', ar: 'ابدأ الآن', am: 'ጀምር' },
  step1_title: { en: 'Your onboarding checklist', ar: 'قائمة مراحل التأهيل', am: 'የምዝገባ ዝርዝርዎ' },
  step1_body: {
    en: 'Complete each step in order. This page updates automatically as your status changes.',
    ar: 'أكمل كل خطوة بالترتيب. تتحدث هذه الصفحة تلقائياً مع تغيير حالتك.',
    am: 'እያንዳንዱን ደረጃ በቅደም ተከተል ያጠናቅቁ። ሁኔታዎ ሲቀየር ይህ ገጽ ራሱ ይዘምናል።',
  },
  step2_title: { en: 'Start here', ar: 'ابدأ هنا', am: 'ከዚህ ይጀምሩ' },
  step2_body: {
    en: 'This is your current step. Follow the instructions and tap the action button.',
    ar: 'هذه خطوتك الحالية. اتبع التعليمات واضغط على زر الإجراء.',
    am: 'ይህ አሁን ያለዎት ደረጃ ነው። መመሪያዎቹን ተከተሉ እና የድርጊት ቁልፉን ይጫኑ።',
  },
  step3_title: { en: 'Need help?', ar: 'تحتاج مساعدة؟', am: 'እርዳታ ይፈልጋሉ?' },
  step3_body: {
    en: 'Questions about any step? Call or text us anytime.',
    ar: 'أسئلة حول أي خطوة؟ اتصل بنا أو أرسل رسالة في أي وقت.',
    am: 'ስለ ማንኛውም ደረጃ ጥያቄ አለዎት? በማንኛውም ጊዜ ይደውሉ ወይም ይጻፉ።',
  },
  next: { en: 'Next', ar: 'التالي', am: 'ቀጣይ' },
  done: { en: 'Got it!', ar: 'فهمت!', am: 'ገባኝ!' },
  back: { en: 'Back', ar: 'رجوع', am: 'ተመለስ' },
}

interface TooltipPos {
  top: number
  left: number
  arrowSide: 'top' | 'bottom'
  arrowLeft: number
}

const PAD = 10
const TW = 300

function calcPos(target: string): TooltipPos | null {
  const el = document.querySelector(`[data-driver-tour="${target}"]`)
  if (!el) return null
  const r = el.getBoundingClientRect()
  const vw = window.innerWidth
  const vh = window.innerHeight
  const below = r.bottom + PAD + 10 + 200 < vh || r.top < vh / 2
  const top = below ? r.bottom + PAD + 10 : r.top - PAD - 10 - 190
  const idealLeft = r.left + r.width / 2 - TW / 2
  const left = Math.max(12, Math.min(idealLeft, vw - TW - 12))
  const arrowLeft = Math.max(18, Math.min(r.left + r.width / 2 - left, TW - 18))
  return { top, left, arrowSide: below ? 'top' : 'bottom', arrowLeft }
}

interface Props {
  lang: Lang
  setLang: (l: Lang) => void
}

export default function DriverTour({ lang, setLang }: Props) {
  const [step, setStep] = useState<-1 | 0 | 1 | 2 | 3>(-1) // -1 = not shown
  const [pos, setPos] = useState<TooltipPos | null>(null)
  const [selectedLang, setSelectedLang] = useState<Lang>(lang)

  useEffect(() => {
    if (!localStorage.getItem(DRIVER_TOUR_KEY)) {
      const savedLang = localStorage.getItem(LANG_KEY) as Lang | null
      if (savedLang) {
        setLang(savedLang)
        setSelectedLang(savedLang)
      }
      const t = setTimeout(() => setStep(0), 800)
      return () => clearTimeout(t)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const goStep = useCallback((s: 1 | 2 | 3) => {
    setStep(s)
    const targets: Record<1 | 2 | 3, string> = {
      1: 'driver-checklist',
      2: 'driver-current-step',
      3: 'driver-help',
    }
    let attempts = 0
    const poll = () => {
      const p = calcPos(targets[s])
      if (p) {
        setPos(p)
      } else if (attempts < 15) {
        attempts++
        setTimeout(poll, 150)
      }
    }
    setTimeout(poll, 100)
  }, [])

  const confirmLang = useCallback(() => {
    setLang(selectedLang)
    localStorage.setItem(LANG_KEY, selectedLang)
    goStep(1)
  }, [selectedLang, setLang, goStep])

  const next = useCallback(() => {
    if (step === 1) goStep(2)
    else if (step === 2) goStep(3)
    else {
      setStep(-1)
      localStorage.setItem(DRIVER_TOUR_KEY, '1')
    }
  }, [step, goStep])

  const skip = useCallback(() => {
    setStep(-1)
    localStorage.setItem(DRIVER_TOUR_KEY, '1')
  }, [])

  if (step === -1) return null

  const isRtl = lang === 'ar'

  // Step 0: Language picker modal
  if (step === 0) {
    return (
      <AnimatePresence>
        <motion.div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80 px-4"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        >
          <motion.div
            className="w-full max-w-sm bg-zinc-900 border border-white/10 rounded-3xl p-6 shadow-2xl"
            initial={{ scale: 0.9, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
          >
            {/* Decorative top accent */}
            <div className="w-10 h-1 bg-[#667eea] rounded-full mb-5" />

            <h2 className="text-xl font-bold text-white mb-1">
              {T.choose_lang.en} · {T.choose_lang.ar} · {T.choose_lang.am}
            </h2>
            <p className="text-sm text-zinc-500 mb-6">{T.lang_subtitle[selectedLang]}</p>

            <div className="space-y-2.5 mb-6">
              {LANGS.map(l => (
                <button
                  key={l.code}
                  onClick={() => setSelectedLang(l.code)}
                  className={`w-full flex items-center gap-4 px-4 py-3.5 rounded-2xl border transition-all cursor-pointer text-left ${
                    selectedLang === l.code
                      ? 'bg-[#667eea]/15 border-[#667eea]/50 scale-[1.02]'
                      : 'bg-white/[0.03] border-white/[0.06] hover:bg-white/[0.06]'
                  }`}
                >
                  <span className="text-3xl">{l.flag}</span>
                  <div>
                    <div className="font-semibold text-white text-sm">{l.native}</div>
                    <div className="text-xs text-zinc-500">{l.name}</div>
                  </div>
                  {selectedLang === l.code && (
                    <div className="ml-auto w-5 h-5 rounded-full bg-[#667eea] flex items-center justify-center">
                      <div className="w-2 h-2 rounded-full bg-white" />
                    </div>
                  )}
                </button>
              ))}
            </div>

            <button
              onClick={confirmLang}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-2xl bg-[#667eea] hover:bg-[#5b6fd4] text-white font-semibold text-sm transition-colors cursor-pointer"
              dir={selectedLang === 'ar' ? 'rtl' : 'ltr'}
            >
              {T.get_started[selectedLang]}
              <ChevronRight className="w-4 h-4" />
            </button>
          </motion.div>
        </motion.div>
      </AnimatePresence>
    )
  }

  // Steps 1–3: spotlight tooltips
  const stepData = {
    1: { title: T.step1_title[lang], body: T.step1_body[lang], target: 'driver-checklist' },
    2: { title: T.step2_title[lang], body: T.step2_body[lang], target: 'driver-current-step' },
    3: { title: T.step3_title[lang], body: T.step3_body[lang], target: 'driver-help' },
  }[step as 1 | 2 | 3]

  const r = stepData?.target
    ? document.querySelector(`[data-driver-tour="${stepData.target}"]`)?.getBoundingClientRect()
    : null

  return (
    <div className="fixed inset-0 z-[9999] pointer-events-none" dir={isRtl ? 'rtl' : 'ltr'}>
      {r && (
        <>
          <div className="absolute pointer-events-auto" onClick={skip}
            style={{ top: 0, left: 0, right: 0, height: Math.max(0, r.top - PAD), background: 'rgba(0,0,0,0.7)' }} />
          <div className="absolute pointer-events-auto" onClick={skip}
            style={{ top: r.bottom + PAD, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.7)' }} />
          <div className="absolute pointer-events-auto" onClick={skip}
            style={{ top: r.top - PAD, left: 0, width: Math.max(0, r.left - PAD), height: r.height + PAD * 2, background: 'rgba(0,0,0,0.7)' }} />
          <div className="absolute pointer-events-auto" onClick={skip}
            style={{ top: r.top - PAD, left: r.right + PAD, right: 0, height: r.height + PAD * 2, background: 'rgba(0,0,0,0.7)' }} />
          <div className="absolute rounded-xl pointer-events-none" style={{
            top: r.top - PAD, left: r.left - PAD,
            width: r.width + PAD * 2, height: r.height + PAD * 2,
            border: '2px solid rgba(102,126,234,0.8)',
            boxShadow: '0 0 28px rgba(102,126,234,0.3)',
          }} />
        </>
      )}

      <AnimatePresence mode="wait">
        {pos && stepData && (
          <motion.div
            key={step}
            initial={{ opacity: 0, y: pos.arrowSide === 'top' ? -8 : 8, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="absolute pointer-events-auto"
            style={{ top: pos.top, left: pos.left, width: TW }}
          >
            {pos.arrowSide === 'top' && (
              <div className="absolute -top-[7px] w-3.5 h-3.5 rotate-45 bg-zinc-800 border-white/[0.08] border-t border-l"
                style={{ left: pos.arrowLeft - 7 }} />
            )}

            <div className="bg-zinc-800/95 border border-white/[0.08] rounded-2xl shadow-2xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold tracking-widest uppercase text-white/30">
                  {step} / 3
                </span>
                <button onClick={skip} className="text-white/30 hover:text-white/60 transition-colors cursor-pointer p-0.5">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <h3 className="font-semibold text-white mb-1.5 text-[15px]">{stepData.title}</h3>
              <p className="text-sm text-zinc-400 leading-relaxed mb-4">{stepData.body}</p>

              <div className="flex items-center gap-1.5 mb-4">
                {[1, 2, 3].map(i => (
                  <div key={i} className={`h-[3px] rounded-full transition-all duration-300 ${
                    i === step ? 'w-5 bg-[#667eea]' : i < step ? 'w-2 bg-[#667eea]/40' : 'w-2 bg-white/15'
                  }`} />
                ))}
              </div>

              <div className="flex items-center gap-2" dir={isRtl ? 'rtl' : 'ltr'}>
                <div className="flex-1" />
                <button onClick={skip} className="text-xs text-white/30 hover:text-white/60 transition-colors cursor-pointer px-1">
                  {T.back[lang]}
                </button>
                <button onClick={next}
                  className="flex items-center gap-1 px-3.5 py-1.5 rounded-lg text-xs font-medium bg-[#667eea] hover:bg-[#5b6fd4] text-white transition-colors cursor-pointer">
                  {step === 3 ? T.done[lang] : T.next[lang]}
                  {step < 3 && <ChevronRight className={`w-3.5 h-3.5 ${isRtl ? 'rotate-180' : ''}`} />}
                </button>
              </div>
            </div>

            {pos.arrowSide === 'bottom' && (
              <div className="absolute -bottom-[7px] w-3.5 h-3.5 rotate-45 bg-zinc-800 border-white/[0.08] border-b border-r"
                style={{ left: pos.arrowLeft - 7 }} />
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
