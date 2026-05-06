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

  // During loading: default to full (admin) nav — never flash operator-only items for admin.
  // isOperator is only true once we have a confirmed response with role='operator'.
  const isOperator = !loading && user?.role === 'operator'
  const isAdmin = !loading && user?.role === 'admin'

  return { user, loading, isOperator, isAdmin }
}
