'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function SimulateRedirect() {
  const router = useRouter()
  useEffect(() => { router.replace('/dispatch/manage') }, [router])
  return null
}
