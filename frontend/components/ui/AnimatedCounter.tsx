'use client'
import { useEffect, useRef } from 'react'
import { gsap } from 'gsap'

interface Props {
  value: number
  prefix?: string  // e.g. "$"
  suffix?: string  // e.g. "%" or " rides"
  decimals?: number
  duration?: number
}

export default function AnimatedCounter({ value, prefix = '', suffix = '', decimals = 0, duration = 1.5 }: Props) {
  const ref = useRef<HTMLSpanElement>(null)
  const obj = useRef({ val: 0 })

  useEffect(() => {
    if (!ref.current || isNaN(value)) return

    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return
      observer.disconnect()

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
    }, { threshold: 0.1 })

    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [value, prefix, suffix, decimals, duration])

  return (
    <span ref={ref}>
      {prefix}{isNaN(value) ? '—' : (decimals > 0 ? value.toFixed(decimals) : value.toLocaleString())}{suffix}
    </span>
  )
}
