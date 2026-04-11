'use client'
import { useEffect, useRef } from 'react'
import { gsap } from 'gsap'

interface Props {
  value: number
  prefix?: string
  suffix?: string
  decimals?: number
  duration?: number
  className?: string
}

/**
 * AnimatedNumber — lightweight inline number animator.
 * Animates from 0 → value on mount (no IntersectionObserver).
 * Use this for values that are always visible on load (e.g. hero stats).
 * Use AnimatedCounter for values that may be below the fold.
 */
export default function AnimatedNumber({ value, prefix = '', suffix = '', decimals = 0, duration = 1.2, className }: Props) {
  const ref = useRef<HTMLSpanElement>(null)
  const obj = useRef({ val: 0 })

  useEffect(() => {
    if (!ref.current || isNaN(value)) return

    obj.current.val = 0
    gsap.to(obj.current, {
      val: value,
      duration,
      ease: 'power2.out',
      onUpdate: () => {
        if (ref.current) {
          const formatted = decimals > 0
            ? obj.current.val.toFixed(decimals)
            : Math.round(obj.current.val).toLocaleString()
          ref.current.textContent = prefix + formatted + suffix
        }
      }
    })
  }, [value, prefix, suffix, decimals, duration])

  return (
    <span ref={ref} className={className}>
      {prefix}{isNaN(value) ? '—' : (decimals > 0 ? value.toFixed(decimals) : value.toLocaleString())}{suffix}
    </span>
  )
}
