'use client'

import { useEffect, useState } from 'react'

export interface CurrentUser {
  user_id: number | null
  username: string
  display_name: string | null
  full_name: string | null
  role: 'admin' | 'operator' | 'associate' | string
  color: string | null
  initials: string | null
}

export function useCurrentUser() {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/v1/users/me', { credentials: 'include' })
      .then(r => (r.ok ? r.json() : null))
      .then(data => { if (data) setUser(data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return { user, loading, isOperator: user?.role === 'operator', isAdmin: user?.role === 'admin' }
}
