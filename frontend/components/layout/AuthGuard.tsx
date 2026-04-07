'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { Loader2 } from 'lucide-react'

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    // Middleware handles server-side redirect; this is a client-side safety net
    const hasCookie = document.cookie.includes('session=')
    if (!hasCookie && pathname !== '/login') {
      router.replace(`/login?redirect=${encodeURIComponent(pathname)}`)
    } else {
      setChecking(false)
    }
  }, [pathname, router])

  if (checking && pathname !== '/login') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0f1219]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 text-[#667eea] animate-spin" />
          <p className="text-white/40 text-sm">Loading Z-Pay...</p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
