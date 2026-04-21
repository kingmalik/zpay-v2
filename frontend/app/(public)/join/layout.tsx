'use client'

import { useEffect } from 'react'

export default function JoinLayout({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    document.body.style.backgroundColor = '#09090b'
    return () => {
      document.body.style.backgroundColor = ''
    }
  }, [])

  return <>{children}</>
}
