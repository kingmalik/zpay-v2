'use client'

import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ShieldCheck, ExternalLink, CheckCircle2, AlertTriangle, Loader2, Info, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import GlassCard from '@/components/ui/GlassCard'
import { useCurrentUser } from '@/hooks/useCurrentUser'
import { useRouter } from 'next/navigation'

// Paychex URLs per company
const PAYCHEX_URLS: Record<string, string> = {
  acumen:
    'https://myapps.paychex.com/landing_remote/login.do?app=PAYROLL_HTML&clients=00M9LQF7M4UGHU3FIGTH',
  maz: 'https://myapps.paychex.com/landing_remote/login.do?app=PAYROLL_HTML',
}

type Company = 'acumen' | 'maz'

interface SessionStatus {
  has_session: boolean
  captured_at: string | null
  source: string | null
}

interface CaptureResult {
  ok: boolean
  company: string
  cookie_count: number
  cookie_names: string[]
  missing_critical: string[]
  warning: string | null
}

type StepState = 'idle' | 'popup_open' | 'capturing' | 'done' | 'error'

export default function PaychexReauthPage() {
  const { isAdmin, loading: userLoading } = useCurrentUser()
  const router = useRouter()
  const [company, setCompany] = useState<Company>('acumen')
  const [step, setStep] = useState<StepState>('idle')
  const [result, setResult] = useState<CaptureResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sessionStatuses, setSessionStatuses] = useState<Record<string, SessionStatus>>({})
  const popupRef = useRef<Window | null>(null)

  // Redirect non-admins away
  useEffect(() => {
    if (!userLoading && !isAdmin) {
      router.replace('/')
    }
  }, [userLoading, isAdmin, router])

  // Load current session status on mount
  useEffect(() => {
    fetch('/api/v1/api/data/paychex-bot/session-status', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setSessionStatuses(d) })
      .catch(() => {})
  }, [])

  function openPopup() {
    const url = PAYCHEX_URLS[company]
    const popup = window.open(
      url,
      'paychex-reauth',
      'width=1100,height=750,menubar=no,toolbar=no,location=yes,scrollbars=yes',
    )
    if (!popup) {
      toast.error('Popup blocked — allow popups for this site and try again.')
      return
    }
    popupRef.current = popup
    setStep('popup_open')
    setResult(null)
    setError(null)
  }

  async function captureSession() {
    setStep('capturing')
    setError(null)

    // Attempt to read cookies from the popup
    // This only works if the popup is still on a paychex.com page that shares
    // the same domain-context (it won't — it's cross-origin, so document.cookie
    // read from popup will be blocked by same-origin policy).
    // Instead, we read the cookies from THIS window's document.cookie for any
    // paychex.com cookies that have been set (rare via redirects), and we also
    // instruct the user to copy-paste their cookie string if needed.
    // The primary path: the parent window does NOT get cross-origin popup cookies.
    // We send whatever we have from the postMessage listener below.
    // If nothing arrived via postMessage, we surface a clear instruction.
    const cookiesFromMessage = pendingCookiesRef.current
    if (!cookiesFromMessage) {
      // No cookies received via postMessage yet — inform user
      setStep('popup_open')
      toast.error(
        'No cookies received yet. Complete sign-in in the popup, then click "Capture my session" again. ' +
        'If this keeps failing, Paychex may require HttpOnly cookies (session capture via popup cannot help in that case).',
      )
      return
    }

    try {
      const res = await fetch(`/api/v1/api/data/paychex-bot/capture/${company}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cookies: cookiesFromMessage }),
      })
      const data: CaptureResult = await res.json()
      if (!res.ok || !data.ok) {
        throw new Error((data as { error?: string }).error ?? 'Capture failed')
      }
      setResult(data)
      setStep('done')
      pendingCookiesRef.current = null
      // Refresh session status
      fetch('/api/v1/api/data/paychex-bot/session-status', { credentials: 'include' })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) setSessionStatuses(d) })
        .catch(() => {})
      toast.success(`${company === 'acumen' ? 'Acumen' : 'Maz'} session captured — ${data.cookie_count} cookies stored.`)
      if (data.warning) toast.warning(data.warning, { duration: 8000 })
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Unknown error'
      setError(msg)
      setStep('error')
      toast.error(`Capture failed: ${msg}`)
    }
  }

  // Listen for postMessage from the popup (once Paychex sends us cookies)
  const pendingCookiesRef = useRef<string | null>(null)

  useEffect(() => {
    function onMessage(e: MessageEvent) {
      // Accept messages from Paychex origins or our own origin (for debugging)
      const allowed = [
        'https://myapps.paychex.com',
        'https://paychex.com',
        window.location.origin,
      ]
      if (!allowed.some(o => e.origin.startsWith(o.replace('*', '')))) return
      if (e.data?.type === 'zpay_cookie_capture' && typeof e.data.cookies === 'string') {
        pendingCookiesRef.current = e.data.cookies
        toast.success('Cookies received from popup — click "Capture my session" now.')
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])

  function reset() {
    setStep('idle')
    setResult(null)
    setError(null)
    pendingCookiesRef.current = null
    if (popupRef.current && !popupRef.current.closed) {
      popupRef.current.close()
    }
    popupRef.current = null
  }

  if (userLoading) return null

  const companyLabel = company === 'acumen' ? 'Acumen (Google SSO)' : 'Maz (Standard)'
  const currentStatus = sessionStatuses[company]

  return (
    <div className="max-w-2xl mx-auto space-y-6 py-8 px-4">
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-xl dark:bg-white/[0.06] bg-gray-100 mt-0.5">
          <ShieldCheck className="w-5 h-5 text-[#667eea]" />
        </div>
        <div>
          <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">Paychex Session Capture</h1>
          <p className="text-sm dark:text-white/40 text-gray-500 mt-0.5">
            Sign in through the Paychex popup to capture a fresh session for the bot.
          </p>
        </div>
      </div>

      {/* Company selector */}
      <GlassCard>
        <p className="text-xs font-semibold dark:text-white/40 text-gray-400 uppercase tracking-wider mb-3">
          Select Company
        </p>
        <div className="flex gap-3">
          {(['acumen', 'maz'] as Company[]).map(c => {
            const s = sessionStatuses[c]
            return (
              <button
                key={c}
                onClick={() => { setCompany(c); reset() }}
                className={[
                  'flex-1 rounded-xl border px-4 py-3 text-left transition-all duration-150 cursor-pointer',
                  company === c
                    ? 'border-[#667eea] dark:bg-[#667eea]/10 bg-blue-50'
                    : 'dark:border-white/[0.08] border-gray-200 dark:hover:border-white/20 hover:border-gray-300',
                ].join(' ')}
              >
                <p className={['font-semibold text-sm', company === c ? 'text-[#667eea]' : 'dark:text-white/70 text-gray-700'].join(' ')}>
                  {c === 'acumen' ? 'Acumen' : 'Maz'}
                </p>
                <p className="text-xs dark:text-white/30 text-gray-400 mt-0.5">
                  {c === 'acumen' ? 'Google SSO — expires ~30 min' : 'Standard login'}
                </p>
                {s && (
                  <p className={['text-xs mt-1.5 font-medium', s.has_session ? 'text-emerald-400' : 'dark:text-white/30 text-gray-400'].join(' ')}>
                    {s.has_session
                      ? `Session active${s.captured_at ? ` · ${new Date(s.captured_at).toLocaleTimeString()}` : ''}`
                      : 'No session stored'}
                  </p>
                )}
              </button>
            )
          })}
        </div>
      </GlassCard>

      {/* Instructions */}
      <GlassCard>
        <div className="flex gap-2.5 mb-4">
          <Info className="w-4 h-4 text-[#06b6d4] mt-0.5 shrink-0" />
          <div className="space-y-1">
            <p className="text-sm font-semibold dark:text-white/80 text-gray-700">How this works</p>
            <ol className="text-sm dark:text-white/50 text-gray-500 space-y-1 list-decimal list-inside">
              <li>Click <strong className="dark:text-white/70 text-gray-600">Open Paychex popup</strong> — Paychex login opens in a new window.</li>
              <li>Sign in with the <strong className="dark:text-white/70 text-gray-600">{company === 'acumen' ? 'malikmilion' : 'malaaaya'}</strong> account, complete MFA, and land on the Paychex dashboard.</li>
              <li>Return here and click <strong className="dark:text-white/70 text-gray-600">Capture my session</strong>.</li>
            </ol>
          </div>
        </div>

        <div className="flex gap-2.5 p-3 rounded-lg dark:bg-amber-500/[0.08] bg-amber-50 border dark:border-amber-500/20 border-amber-200">
          <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
          <p className="text-xs dark:text-amber-300/70 text-amber-700">
            <strong>HttpOnly limitation:</strong> Paychex sets some session tokens as HttpOnly — JavaScript cannot read those.
            The first capture attempt will reveal which cookies are visible. If the bot still fails, the session relies on
            HttpOnly tokens and a different approach will be needed.
          </p>
        </div>
      </GlassCard>

      {/* Action area */}
      <GlassCard>
        <AnimatePresence mode="wait">
          {step === 'idle' && (
            <motion.div
              key="idle"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-4 py-4"
            >
              <button
                onClick={openPopup}
                className="flex items-center gap-2.5 px-6 py-3 rounded-xl text-sm font-semibold text-white transition-all hover:opacity-90 cursor-pointer"
                style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
              >
                <ExternalLink className="w-4 h-4" />
                Open Paychex popup — {companyLabel}
              </button>
            </motion.div>
          )}

          {step === 'popup_open' && (
            <motion.div
              key="popup_open"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="space-y-4"
            >
              <div className="flex items-center gap-2.5 p-3 rounded-lg dark:bg-white/[0.04] bg-gray-50">
                <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <p className="text-sm dark:text-white/70 text-gray-600">
                  Popup is open. Sign in as <strong>{company === 'acumen' ? 'malikmilion' : 'malaaaya'}</strong> and land on the Paychex dashboard, then come back here.
                </p>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={captureSession}
                  className="flex-1 flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:opacity-90 cursor-pointer"
                  style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
                >
                  <ShieldCheck className="w-4 h-4" />
                  Capture my session
                </button>
                <button
                  onClick={() => { openPopup() }}
                  className="px-4 py-2.5 rounded-xl text-sm font-medium dark:text-white/50 text-gray-500 dark:hover:text-white/80 dark:hover:bg-white/[0.06] hover:bg-gray-100 transition-colors cursor-pointer"
                >
                  Reopen popup
                </button>
                <button
                  onClick={reset}
                  className="px-4 py-2.5 rounded-xl text-sm font-medium dark:text-white/30 text-gray-400 dark:hover:text-white/60 dark:hover:bg-white/[0.04] hover:bg-gray-50 transition-colors cursor-pointer"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          )}

          {step === 'capturing' && (
            <motion.div
              key="capturing"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center justify-center gap-3 py-6"
            >
              <Loader2 className="w-5 h-5 text-[#667eea] animate-spin" />
              <p className="text-sm dark:text-white/60 text-gray-500">Storing cookies…</p>
            </motion.div>
          )}

          {step === 'done' && result && (
            <motion.div
              key="done"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="space-y-4"
            >
              <div className="flex items-start gap-3 p-4 rounded-xl dark:bg-emerald-500/[0.08] bg-emerald-50 border dark:border-emerald-500/20 border-emerald-200">
                <CheckCircle2 className="w-5 h-5 text-emerald-400 mt-0.5 shrink-0" />
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-emerald-400">
                    Session captured — {result.cookie_count} cookies stored
                  </p>
                  <p className="text-xs dark:text-white/40 text-gray-500">
                    Cookie names: {result.cookie_names.join(', ') || 'none'}
                  </p>
                </div>
              </div>

              {result.missing_critical.length > 0 && (
                <div className="flex items-start gap-2.5 p-3 rounded-lg dark:bg-amber-500/[0.08] bg-amber-50 border dark:border-amber-500/20 border-amber-200">
                  <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-xs font-semibold text-amber-400 mb-0.5">HttpOnly cookies not captured:</p>
                    <p className="text-xs dark:text-amber-300/60 text-amber-700">
                      {result.missing_critical.join(', ')}
                    </p>
                    <p className="text-xs dark:text-amber-300/50 text-amber-600 mt-1">
                      These are set HttpOnly by Paychex and cannot be read by JavaScript.
                      Run the bot — if it fails at login, session capture cannot solve the SSO problem via this method.
                    </p>
                  </div>
                </div>
              )}

              <div className="flex gap-3">
                <button
                  onClick={reset}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium dark:text-white/50 text-gray-500 dark:hover:bg-white/[0.06] hover:bg-gray-100 transition-colors cursor-pointer"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Capture again
                </button>
              </div>
            </motion.div>
          )}

          {step === 'error' && (
            <motion.div
              key="error"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-4"
            >
              <div className="flex items-start gap-2.5 p-3 rounded-lg dark:bg-red-500/[0.08] bg-red-50 border dark:border-red-500/20 border-red-200">
                <AlertTriangle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
                <p className="text-xs text-red-400">{error}</p>
              </div>
              <button
                onClick={reset}
                className="px-4 py-2.5 rounded-xl text-sm font-medium dark:text-white/50 text-gray-500 dark:hover:bg-white/[0.06] hover:bg-gray-100 transition-colors cursor-pointer"
              >
                Try again
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </GlassCard>

      {/* Session status table */}
      {Object.keys(sessionStatuses).length > 0 && (
        <GlassCard padding={false}>
          <div className="p-4 border-b dark:border-white/[0.08] border-gray-100">
            <h3 className="text-sm font-semibold dark:text-white/70 text-gray-700">Current Sessions</h3>
          </div>
          <div className="divide-y dark:divide-white/[0.06] divide-gray-100">
            {Object.entries(sessionStatuses).map(([co, s]) => (
              <div key={co} className="px-4 py-3 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium dark:text-white/80 text-gray-700 capitalize">{co}</p>
                  {s.captured_at && (
                    <p className="text-xs dark:text-white/30 text-gray-400 mt-0.5">
                      Captured {new Date(s.captured_at).toLocaleString()}
                    </p>
                  )}
                </div>
                <span className={[
                  'inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full',
                  s.has_session
                    ? 'dark:bg-emerald-500/10 bg-emerald-50 text-emerald-500'
                    : 'dark:bg-white/[0.06] bg-gray-100 dark:text-white/30 text-gray-400',
                ].join(' ')}>
                  <span className={['w-1.5 h-1.5 rounded-full', s.has_session ? 'bg-emerald-400' : 'dark:bg-white/20 bg-gray-300'].join(' ')} />
                  {s.has_session ? 'Active' : 'None'}
                </span>
              </div>
            ))}
          </div>
        </GlassCard>
      )}
    </div>
  )
}
