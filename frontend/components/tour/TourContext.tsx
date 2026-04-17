'use client'

import { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { ADMIN_STEPS, ADMIN_TOUR_KEY } from '@/lib/tour/adminSteps'
import type { TourStep } from '@/lib/tour/types'

interface TourContextValue {
  active: boolean
  stepIndex: number
  step: TourStep | null
  totalSteps: number
  targetRect: DOMRect | null
  next: () => void
  prev: () => void
  skip: () => void
  startTour: () => void
}

const TourContext = createContext<TourContextValue | null>(null)

export function useTour() {
  const ctx = useContext(TourContext)
  if (!ctx) throw new Error('useTour must be used within TourProvider')
  return ctx
}

export function TourProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [active, setActive] = useState(false)
  const [stepIndex, setStepIndex] = useState(0)
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const step = active ? (ADMIN_STEPS[stepIndex] ?? null) : null

  // Fire on first visit
  useEffect(() => {
    if (!localStorage.getItem(ADMIN_TOUR_KEY)) {
      const t = setTimeout(() => { setActive(true); setStepIndex(0) }, 1200)
      return () => clearTimeout(t)
    }
  }, [])

  const findTarget = useCallback((target: string) => {
    if (pollRef.current) clearTimeout(pollRef.current)
    setTargetRect(null)
    let attempts = 0
    const poll = () => {
      const el = document.querySelector(`[data-tour="${target}"]`)
      if (el) {
        el.scrollIntoView({ block: 'center', behavior: 'smooth' })
        // Allow scroll to settle before measuring
        setTimeout(() => setTargetRect(el.getBoundingClientRect()), 350)
      } else if (attempts < 25) {
        attempts++
        pollRef.current = setTimeout(poll, 150)
      }
    }
    poll()
  }, [])

  // Navigate to step route then find element
  useEffect(() => {
    if (!active || !step) return
    if (pathname !== step.route) {
      router.push(step.route)
      return
    }
    findTarget(step.target)
    return () => { if (pollRef.current) clearTimeout(pollRef.current) }
  }, [active, stepIndex, pathname]) // eslint-disable-line react-hooks/exhaustive-deps

  // Recalculate on resize
  useEffect(() => {
    if (!active || !step || pathname !== step.route) return
    const update = () => {
      const el = document.querySelector(`[data-tour="${step.target}"]`)
      if (el) setTargetRect(el.getBoundingClientRect())
    }
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [active, step, pathname])

  const next = useCallback(() => {
    if (stepIndex < ADMIN_STEPS.length - 1) {
      setStepIndex(i => i + 1)
    } else {
      setActive(false)
      localStorage.setItem(ADMIN_TOUR_KEY, '1')
    }
  }, [stepIndex])

  const prev = useCallback(() => {
    if (stepIndex > 0) setStepIndex(i => i - 1)
  }, [stepIndex])

  const skip = useCallback(() => {
    setActive(false)
    localStorage.setItem(ADMIN_TOUR_KEY, '1')
  }, [])

  const startTour = useCallback(() => {
    localStorage.removeItem(ADMIN_TOUR_KEY)
    setStepIndex(0)
    setTargetRect(null)
    setActive(true)
  }, [])

  return (
    <TourContext.Provider value={{ active, stepIndex, step, totalSteps: ADMIN_STEPS.length, targetRect, next, prev, skip, startTour }}>
      {children}
    </TourContext.Provider>
  )
}
