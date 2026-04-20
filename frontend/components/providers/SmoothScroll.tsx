'use client'
import { useEffect } from 'react'
import { usePathname } from 'next/navigation'

const PUBLIC_PREFIXES = ['/login', '/join', '/training', '/contract']

function isIOS() {
  if (typeof navigator === 'undefined') return false
  return /iPad|iPhone|iPod/.test(navigator.userAgent) && !(window as unknown as Record<string, unknown>).MSStream
}

export default function SmoothScroll({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const isPublic = PUBLIC_PREFIXES.some(p => pathname.startsWith(p))

  useEffect(() => {
    // Skip on iOS — Lenis conflicts with Safari's native momentum scroll
    if (isPublic || isIOS()) return

    let lenis: { raf: (t: number) => void; destroy: () => void } | null = null
    let rafId: number

    import('lenis').then(({ default: Lenis }) => {
      lenis = new Lenis({
        duration: 1.2,
        easing: (t: number) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
        smoothWheel: true,
      })
      function raf(time: number) {
        lenis!.raf(time)
        rafId = requestAnimationFrame(raf)
      }
      rafId = requestAnimationFrame(raf)
    }).catch(() => {})

    return () => {
      cancelAnimationFrame(rafId)
      lenis?.destroy()
    }
  }, [isPublic])

  return <>{children}</>
}
