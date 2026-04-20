'use client'
import { useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'

export default function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const prevPath = useRef<string | null>(null)

  useEffect(() => {
    if (prevPath.current === pathname) return
    prevPath.current = pathname
    if (pathname.startsWith('/join')) return

    // Ensure page is always visible — guard against GSAP stall on iOS
    const el = document.querySelector<HTMLElement>('.page-content')
    if (!el) return
    el.style.opacity = '1'
    el.style.transform = 'none'

    try {
      import('gsap').then(({ gsap }) => {
        gsap.fromTo(
          el,
          { opacity: 0, y: 16 },
          { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out', clearProps: 'all' }
        )
      }).catch(() => {
        el.style.opacity = '1'
        el.style.transform = 'none'
      })
    } catch {
      el.style.opacity = '1'
      el.style.transform = 'none'
    }
  }, [pathname])

  return <>{children}</>
}
