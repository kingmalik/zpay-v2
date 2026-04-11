'use client'
import { useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { gsap } from 'gsap'

export default function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const prevPath = useRef<string | null>(null)

  useEffect(() => {
    if (prevPath.current === pathname) return
    prevPath.current = pathname

    // Skip animation for /join pages (driver portal — no animations per spec)
    if (pathname.startsWith('/join')) return

    gsap.fromTo(
      '.page-content',
      { opacity: 0, y: 16 },
      { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out', clearProps: 'all' }
    )
  }, [pathname])

  return <>{children}</>
}
