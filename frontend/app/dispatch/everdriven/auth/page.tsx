'use client'

import { useState, FormEvent } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Loader2, Lock, Mail } from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'

export default function EverDrivenAuthPage() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.post('/dispatch/everdriven/auth', { email, password })
      router.push('/dispatch/everdriven')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-md mx-auto py-12 px-4">
      <div className="flex items-center gap-3 mb-8">
        <Link href="/dispatch/everdriven" className="p-2 rounded-xl dark:hover:bg-white/8 hover:bg-gray-100 transition-all dark:text-white/50 text-gray-500 cursor-pointer">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <h1 className="text-xl font-bold dark:text-white text-gray-900">EverDriven Login</h1>
      </div>

      <GlassCard>
        <div className="flex items-center gap-2 mb-6">
          <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-cyan-500/15 text-cyan-400 border border-cyan-500/30">EverDriven</span>
          <p className="text-sm dark:text-white/50 text-gray-500">Re-authenticate to pull dispatch data</p>
        </div>

        {error && (
          <div className="mb-4 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">{error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs dark:text-white/50 text-gray-500 mb-1.5">Email</label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
              <input type="email" value={email} onChange={e => setEmail(e.target.value)} required placeholder="your@email.com"
                className="w-full pl-9 pr-4 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
            </div>
          </div>
          <div>
            <label className="block text-xs dark:text-white/50 text-gray-500 mb-1.5">Password</label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 dark:text-white/30 text-gray-400" />
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} required placeholder="••••••••"
                className="w-full pl-9 pr-4 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
            </div>
          </div>
          <button type="submit" disabled={loading || !email || !password}
            className="w-full py-3 rounded-xl text-white font-medium text-sm transition-all cursor-pointer disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #06b6d4, #667eea)' }}>
            {loading ? <span className="flex items-center justify-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />Connecting...</span> : 'Connect EverDriven'}
          </button>
        </form>
      </GlassCard>
    </div>
  )
}
