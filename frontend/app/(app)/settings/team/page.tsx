'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Users, Plus, Pencil, X, Shield, UserCog, UserCircle,
  KeyRound, Ban, Check, AlertCircle,
} from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import EmptyState from '@/components/ui/EmptyState'

type Role = 'admin' | 'operator' | 'associate'

interface TeamUser {
  user_id: number
  username: string
  full_name: string
  display_name: string
  role: Role
  email?: string | null
  phone?: string | null
  language: string
  color: string
  initials: string
  avatar_url?: string | null
  active: boolean
  created_at?: string | null
  last_login_at?: string | null
}

interface Me {
  role?: Role
  source?: string
}

const ROLE_META: Record<Role, { label: string; icon: React.ReactNode; color: string }> = {
  admin: { label: 'Admin', icon: <Shield className="w-3 h-3" />, color: 'text-purple-500' },
  operator: { label: 'Operator', icon: <UserCog className="w-3 h-3" />, color: 'text-[#667eea]' },
  associate: { label: 'Associate', icon: <UserCircle className="w-3 h-3" />, color: 'text-emerald-500' },
}

export default function TeamSettingsPage() {
  const [me, setMe] = useState<Me | null>(null)
  const [users, setUsers] = useState<TeamUser[]>([])
  const [loading, setLoading] = useState(true)
  const [forbidden, setForbidden] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [editUser, setEditUser] = useState<TeamUser | null>(null)
  const [pwUser, setPwUser] = useState<TeamUser | null>(null)

  const load = useCallback(async () => {
    try {
      const [meData, list] = await Promise.all([
        api.get<Me>('/users/me'),
        api.get<TeamUser[]>('/users'),
      ])
      setMe(meData)
      setUsers(list)
    } catch (e: unknown) {
      const msg = (e as Error).message || ''
      if (msg.includes('403') || msg.toLowerCase().includes('forbidden')) {
        setForbidden(true)
      } else {
        setErr(msg || 'Failed to load team')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const isAdmin = me?.role === 'admin'

  async function onDeactivate(u: TeamUser) {
    if (!confirm(`Deactivate ${u.display_name}? They will no longer be able to log in.`)) return
    try {
      await api.post(`/users/${u.user_id}/deactivate`)
      load()
    } catch (e: unknown) {
      alert((e as Error).message || 'Failed')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner />
      </div>
    )
  }

  if (forbidden) {
    return (
      <div className="max-w-xl mx-auto px-4 py-20">
        <EmptyState
          icon={<Shield className="w-8 h-8" />}
          title="Admin only"
          subtitle="Only admins can manage the team. Ask Malik to update your role."
        />
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="max-w-4xl mx-auto px-4 py-6 md:py-10 space-y-6"
    >
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold dark:text-white text-gray-900 flex items-center gap-2">
            <Users className="w-6 h-6" />
            Team
          </h1>
          <p className="text-sm dark:text-white/50 text-gray-500">
            Manage who can log in and what they can see.
          </p>
        </div>
        {isAdmin && (
          <button
            onClick={() => setCreateOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-[#667eea] hover:bg-[#5b6fd4] text-white transition-colors duration-150 cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            Add member
          </button>
        )}
      </header>

      {err && (
        <div className="flex gap-2 p-3 rounded-lg border border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{err}</span>
        </div>
      )}

      {users.length === 0 ? (
        <EmptyState
          icon={<Users className="w-8 h-8" />}
          title="No team members yet"
          subtitle={isAdmin ? 'Add your first team member to get started.' : ''}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {users.map((u) => {
            const meta = ROLE_META[u.role] || ROLE_META.associate
            return (
              <GlassCard key={u.user_id} className={!u.active ? 'opacity-50' : ''}>
                <div className="flex items-start gap-3">
                  <div
                    className="w-12 h-12 rounded-full flex-shrink-0 flex items-center justify-center font-bold text-white text-base"
                    style={{ backgroundColor: u.color || '#4facfe' }}
                  >
                    {u.initials || '?'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="font-semibold dark:text-white text-gray-900 truncate">
                        {u.display_name}
                      </div>
                      {!u.active && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-500">
                          INACTIVE
                        </span>
                      )}
                    </div>
                    <div className="text-xs dark:text-white/50 text-gray-500 truncate">
                      @{u.username}
                    </div>
                    <div
                      className={`mt-1 inline-flex items-center gap-1 text-xs font-medium ${meta.color}`}
                    >
                      {meta.icon}
                      {meta.label}
                    </div>
                    {u.email && (
                      <div className="mt-2 text-xs dark:text-white/60 text-gray-600 truncate">
                        {u.email}
                      </div>
                    )}
                    {u.phone && (
                      <div className="text-xs dark:text-white/60 text-gray-600">
                        {u.phone}
                      </div>
                    )}
                  </div>
                </div>
                {isAdmin && (
                  <div className="flex gap-2 mt-4 pt-3 border-t dark:border-white/[0.08] border-gray-100">
                    <IconBtn onClick={() => setEditUser(u)} title="Edit">
                      <Pencil className="w-3.5 h-3.5" />
                    </IconBtn>
                    <IconBtn onClick={() => setPwUser(u)} title="Reset password">
                      <KeyRound className="w-3.5 h-3.5" />
                    </IconBtn>
                    {u.active && (
                      <IconBtn onClick={() => onDeactivate(u)} title="Deactivate" danger>
                        <Ban className="w-3.5 h-3.5" />
                      </IconBtn>
                    )}
                  </div>
                )}
              </GlassCard>
            )
          })}
        </div>
      )}

      <AnimatePresence>
        {createOpen && (
          <CreateUserModal
            onClose={() => setCreateOpen(false)}
            onCreated={() => {
              setCreateOpen(false)
              load()
            }}
          />
        )}
        {editUser && (
          <EditUserModal
            user={editUser}
            onClose={() => setEditUser(null)}
            onSaved={() => {
              setEditUser(null)
              load()
            }}
          />
        )}
        {pwUser && (
          <ResetPasswordModal
            user={pwUser}
            onClose={() => setPwUser(null)}
            onSaved={() => setPwUser(null)}
          />
        )}
      </AnimatePresence>
    </motion.div>
  )
}

/* ── Modals ────────────────────────────────────────────────── */

function Modal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.96, y: 8 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.96, y: 8 }}
        transition={{ duration: 0.15 }}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md dark:bg-[#111113] bg-white border dark:border-white/[0.08] border-gray-200 rounded-2xl shadow-xl"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b dark:border-white/[0.08] border-gray-100">
          <h3 className="font-semibold dark:text-white text-gray-900">{title}</h3>
          <button
            onClick={onClose}
            className="p-1 rounded-lg dark:text-white/50 text-gray-400 dark:hover:bg-white/[0.07] hover:bg-gray-100 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </motion.div>
    </motion.div>
  )
}

function CreateUserModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: () => void
}) {
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState<Role>('associate')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setSaving(true)
    try {
      await api.post('/users', {
        username: username.toLowerCase().trim(),
        full_name: fullName,
        role,
        password,
        email: email || null,
        phone: phone || null,
      })
      onCreated()
    } catch (e: unknown) {
      setErr((e as Error).message || 'Create failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="Add team member" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <Input label="Username" value={username} onChange={setUsername} required />
        <Input label="Full name" value={fullName} onChange={setFullName} required />
        <div>
          <span className="text-xs font-medium dark:text-white/60 text-gray-600 mb-1.5 block">
            Role
          </span>
          <div className="grid grid-cols-3 gap-2">
            {(['admin', 'operator', 'associate'] as Role[]).map((r) => (
              <button
                type="button"
                key={r}
                onClick={() => setRole(r)}
                className={`px-3 py-2 rounded-lg text-xs font-medium border transition-all cursor-pointer ${
                  role === r
                    ? 'border-[#667eea] bg-[#667eea]/10 text-[#667eea]'
                    : 'dark:border-white/[0.1] border-gray-200 dark:text-white/60 text-gray-600 dark:hover:bg-white/[0.04] hover:bg-gray-50'
                }`}
              >
                {ROLE_META[r].label}
              </button>
            ))}
          </div>
        </div>
        <Input
          label="Initial password"
          value={password}
          onChange={setPassword}
          type="password"
          required
          minLength={8}
        />
        <Input label="Email (optional)" value={email} onChange={setEmail} type="email" />
        <Input label="Phone (optional)" value={phone} onChange={setPhone} type="tel" />
        {err && (
          <div className="text-sm text-red-500 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" />
            {err}
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm font-medium dark:text-white/60 text-gray-600 dark:hover:bg-white/[0.07] hover:bg-gray-100 cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-[#667eea] hover:bg-[#5b6fd4] text-white disabled:opacity-50 transition-colors duration-150 cursor-pointer"
          >
            {saving ? 'Creating…' : 'Create'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

function EditUserModal({
  user,
  onClose,
  onSaved,
}: {
  user: TeamUser
  onClose: () => void
  onSaved: () => void
}) {
  const [fullName, setFullName] = useState(user.full_name)
  const [displayName, setDisplayName] = useState(user.display_name)
  const [role, setRole] = useState<Role>(user.role)
  const [email, setEmail] = useState(user.email || '')
  const [phone, setPhone] = useState(user.phone || '')
  const [active, setActive] = useState(user.active)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setSaving(true)
    try {
      await api.patch(`/users/${user.user_id}`, {
        full_name: fullName,
        display_name: displayName,
        role,
        email: email || null,
        phone: phone || null,
        active,
      })
      onSaved()
    } catch (e: unknown) {
      setErr((e as Error).message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={`Edit ${user.display_name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <Input label="Full name" value={fullName} onChange={setFullName} required />
        <Input label="Display name" value={displayName} onChange={setDisplayName} required />
        <div>
          <span className="text-xs font-medium dark:text-white/60 text-gray-600 mb-1.5 block">
            Role
          </span>
          <div className="grid grid-cols-3 gap-2">
            {(['admin', 'operator', 'associate'] as Role[]).map((r) => (
              <button
                type="button"
                key={r}
                onClick={() => setRole(r)}
                className={`px-3 py-2 rounded-lg text-xs font-medium border transition-all cursor-pointer ${
                  role === r
                    ? 'border-[#667eea] bg-[#667eea]/10 text-[#667eea]'
                    : 'dark:border-white/[0.1] border-gray-200 dark:text-white/60 text-gray-600 dark:hover:bg-white/[0.04] hover:bg-gray-50'
                }`}
              >
                {ROLE_META[r].label}
              </button>
            ))}
          </div>
        </div>
        <Input label="Email" value={email} onChange={setEmail} type="email" />
        <Input label="Phone" value={phone} onChange={setPhone} type="tel" />
        <label className="flex items-center gap-2 pt-1 cursor-pointer">
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
            className="rounded"
          />
          <span className="text-sm dark:text-white/80 text-gray-700">Active</span>
        </label>
        {err && (
          <div className="text-sm text-red-500 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" />
            {err}
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm font-medium dark:text-white/60 text-gray-600 dark:hover:bg-white/[0.07] hover:bg-gray-100 cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-[#667eea] hover:bg-[#5b6fd4] text-white disabled:opacity-50 transition-colors duration-150 cursor-pointer"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

function ResetPasswordModal({
  user,
  onClose,
  onSaved,
}: {
  user: TeamUser
  onClose: () => void
  onSaved: () => void
}) {
  const [pw, setPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    if (pw.length < 8) {
      setErr('Password must be at least 8 characters.')
      return
    }
    if (pw !== confirm) {
      setErr('Passwords do not match.')
      return
    }
    setSaving(true)
    try {
      await api.post(`/users/${user.user_id}/reset-password`, { new_password: pw })
      setDone(true)
      setTimeout(onSaved, 900)
    } catch (e: unknown) {
      setErr((e as Error).message || 'Reset failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={`Reset password for ${user.display_name}`} onClose={onClose}>
      {done ? (
        <div className="flex items-center gap-2 text-emerald-500 py-4">
          <Check className="w-5 h-5" />
          Password updated.
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <Input label="New password" value={pw} onChange={setPw} type="password" required minLength={8} />
          <Input label="Confirm password" value={confirm} onChange={setConfirm} type="password" required minLength={8} />
          {err && (
            <div className="text-sm text-red-500 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              {err}
            </div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm font-medium dark:text-white/60 text-gray-600 dark:hover:bg-white/[0.07] hover:bg-gray-100 cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-[#667eea] hover:bg-[#5b6fd4] text-white disabled:opacity-50 transition-colors duration-150 cursor-pointer"
            >
              {saving ? 'Saving…' : 'Set password'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}

/* ── Small bits ────────────────────────────────────────────── */

function Input({
  label,
  value,
  onChange,
  type = 'text',
  required,
  minLength,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  required?: boolean
  minLength?: number
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium dark:text-white/60 text-gray-600 mb-1.5 block">
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        minLength={minLength}
        className="w-full px-3 py-2 rounded-lg text-sm dark:bg-white/[0.04] bg-white border dark:border-white/[0.1] border-gray-200 dark:text-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#667eea]/50"
      />
    </label>
  )
}

function IconBtn({
  onClick,
  title,
  children,
  danger,
}: {
  onClick: () => void
  title: string
  children: React.ReactNode
  danger?: boolean
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`p-2 rounded-lg text-xs transition-colors cursor-pointer ${
        danger
          ? 'text-red-500 hover:bg-red-500/10'
          : 'dark:text-white/60 text-gray-600 dark:hover:bg-white/[0.07] hover:bg-gray-100'
      }`}
    >
      {children}
    </button>
  )
}
