'use client'

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { User, Mail, Phone, Globe, Lock, Check, AlertCircle, RotateCcw } from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { useTour } from '@/components/tour/TourContext'

interface Me {
  user_id?: number
  username?: string
  full_name?: string
  display_name?: string
  email?: string | null
  phone?: string | null
  language?: string
  role?: string
  color?: string
  initials?: string
  avatar_url?: string | null
  source?: string
}

const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'am', label: 'Amharic' },
  { code: 'ar', label: 'Arabic' },
  { code: 'es', label: 'Spanish' },
]

export default function ProfileSettingsPage() {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  const [fullName, setFullName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [language, setLanguage] = useState('en')

  const { startTour } = useTour()

  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwSaving, setPwSaving] = useState(false)
  const [pwMsg, setPwMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  useEffect(() => {
    (async () => {
      try {
        const data = await api.get<Me>('/users/me')
        setMe(data)
        setFullName(data.full_name || '')
        setDisplayName(data.display_name || '')
        setEmail(data.email || '')
        setPhone(data.phone || '')
        setLanguage(data.language || 'en')
      } catch (e: unknown) {
        setMsg({ kind: 'err', text: (e as Error).message || 'Failed to load profile' })
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const envFallback = me?.source === 'env_fallback'

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault()
    setMsg(null)
    setSaving(true)
    try {
      const data = await api.patch<Me>('/users/me', {
        full_name: fullName,
        display_name: displayName,
        email: email || null,
        phone: phone || null,
        language,
      })
      setMe(data)
      setMsg({ kind: 'ok', text: 'Profile saved.' })
    } catch (e: unknown) {
      setMsg({ kind: 'err', text: (e as Error).message || 'Save failed' })
    } finally {
      setSaving(false)
    }
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault()
    setPwMsg(null)
    if (newPw.length < 8) {
      setPwMsg({ kind: 'err', text: 'New password must be at least 8 characters.' })
      return
    }
    if (newPw !== confirmPw) {
      setPwMsg({ kind: 'err', text: 'Passwords do not match.' })
      return
    }
    setPwSaving(true)
    try {
      await api.post('/users/me/password', {
        current_password: currentPw,
        new_password: newPw,
      })
      setPwMsg({ kind: 'ok', text: 'Password updated.' })
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
    } catch (e: unknown) {
      setPwMsg({ kind: 'err', text: (e as Error).message || 'Change failed' })
    } finally {
      setPwSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="max-w-2xl mx-auto px-4 py-6 md:py-10 space-y-6"
    >
      <header className="space-y-1">
        <h1 className="text-2xl md:text-3xl font-bold dark:text-white text-gray-900">
          Profile
        </h1>
        <p className="text-sm dark:text-white/50 text-gray-500">
          Your account details. Visible on the team page.
        </p>
      </header>

      {/* Identity header */}
      <GlassCard>
        <div className="flex items-center gap-4">
          <div
            className="w-14 h-14 rounded-full flex items-center justify-center font-bold text-white text-lg"
            style={{ backgroundColor: me?.color || '#4facfe' }}
          >
            {me?.initials || '?'}
          </div>
          <div>
            <div className="font-semibold dark:text-white text-gray-900">
              {me?.display_name || me?.username}
            </div>
            <div className="text-xs dark:text-white/50 text-gray-500">
              @{me?.username} · {(me?.role || '').toUpperCase()}
            </div>
          </div>
        </div>
      </GlassCard>

      {envFallback && (
        <div className="flex gap-2 p-3 rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <div>
            Your account is still env-managed. Ask an admin to migrate your user
            to the database so you can edit your profile.
          </div>
        </div>
      )}

      {/* Profile form */}
      <form onSubmit={saveProfile}>
        <GlassCard>
          <h2 className="font-semibold dark:text-white text-gray-900 mb-4">
            Account details
          </h2>

          <div className="space-y-4">
            <Field label="Full name" icon={<User className="w-4 h-4" />}>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                disabled={envFallback}
                className={inputCls}
                required
              />
            </Field>

            <Field label="Display name" icon={<User className="w-4 h-4" />}>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                disabled={envFallback}
                className={inputCls}
                required
              />
            </Field>

            <Field label="Email" icon={<Mail className="w-4 h-4" />}>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={envFallback}
                className={inputCls}
                placeholder="optional"
              />
            </Field>

            <Field label="Phone" icon={<Phone className="w-4 h-4" />}>
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                disabled={envFallback}
                className={inputCls}
                placeholder="optional"
              />
            </Field>

            <Field label="Language" icon={<Globe className="w-4 h-4" />}>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                disabled={envFallback}
                className={inputCls}
              >
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <div className="flex items-center justify-end gap-3 mt-6">
            {msg && (
              <span
                className={`text-sm ${
                  msg.kind === 'ok'
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-red-600 dark:text-red-400'
                }`}
              >
                {msg.text}
              </span>
            )}
            <button
              type="submit"
              disabled={saving || envFallback}
              className={primaryBtn}
            >
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </GlassCard>
      </form>

      {/* Password */}
      <form onSubmit={changePassword}>
        <GlassCard>
          <h2 className="font-semibold dark:text-white text-gray-900 mb-1 flex items-center gap-2">
            <Lock className="w-4 h-4" />
            Change password
          </h2>
          <p className="text-xs dark:text-white/50 text-gray-500 mb-4">
            Minimum 8 characters.
          </p>
          <div className="space-y-4">
            <Field label="Current password">
              <input
                type="password"
                value={currentPw}
                onChange={(e) => setCurrentPw(e.target.value)}
                disabled={envFallback}
                className={inputCls}
                required
              />
            </Field>
            <Field label="New password">
              <input
                type="password"
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                disabled={envFallback}
                className={inputCls}
                required
                minLength={8}
              />
            </Field>
            <Field label="Confirm new password">
              <input
                type="password"
                value={confirmPw}
                onChange={(e) => setConfirmPw(e.target.value)}
                disabled={envFallback}
                className={inputCls}
                required
                minLength={8}
              />
            </Field>
          </div>
          <div className="flex items-center justify-end gap-3 mt-6">
            {pwMsg && (
              <span
                className={`text-sm flex items-center gap-1 ${
                  pwMsg.kind === 'ok'
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-red-600 dark:text-red-400'
                }`}
              >
                {pwMsg.kind === 'ok' && <Check className="w-3 h-3" />}
                {pwMsg.text}
              </span>
            )}
            <button
              type="submit"
              disabled={pwSaving || envFallback}
              className={primaryBtn}
            >
              {pwSaving ? 'Updating…' : 'Update password'}
            </button>
          </div>
        </GlassCard>
      </form>

      {/* Restart tour */}
      <GlassCard>
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="font-semibold dark:text-white text-gray-900 text-sm">App tour</h2>
            <p className="text-xs dark:text-white/50 text-gray-500 mt-0.5">Replay the guided walkthrough of Z-Pay.</p>
          </div>
          <button
            onClick={startTour}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium dark:bg-white/[0.06] bg-gray-100 dark:text-white/70 text-gray-700 dark:hover:bg-white/[0.10] hover:bg-gray-200 transition-colors cursor-pointer whitespace-nowrap"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Restart tour
          </button>
        </div>
      </GlassCard>
    </motion.div>
  )
}

function Field({
  label,
  icon,
  children,
}: {
  label: string
  icon?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="flex items-center gap-1.5 text-xs font-medium dark:text-white/60 text-gray-600 mb-1.5">
        {icon}
        {label}
      </span>
      {children}
    </label>
  )
}

const inputCls =
  'w-full px-3 py-2 rounded-lg text-sm dark:bg-white/[0.04] bg-white border dark:border-white/[0.1] border-gray-200 dark:text-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#667eea]/50 disabled:opacity-50 disabled:cursor-not-allowed'

const primaryBtn =
  'px-4 py-2 rounded-lg text-sm font-medium bg-[#667eea] hover:bg-[#5b6fd4] text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-150 cursor-pointer'
