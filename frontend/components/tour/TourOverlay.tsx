'use client'

import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, ChevronLeft, ChevronRight } from 'lucide-react'
import { useTour } from './TourContext'

const PAD = 12
const TOOLTIP_W = 320

interface TooltipPos {
  top: number
  left: number
  arrowSide: 'top' | 'bottom'
  arrowLeft: number
}

function calcTooltipPos(r: DOMRect): TooltipPos {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const spaceBelow = vh - r.bottom - PAD - 16
  const spaceAbove = r.top - PAD - 16
  const below = spaceBelow > 180 || spaceBelow >= spaceAbove

  const top = below ? r.bottom + PAD + 10 : r.top - PAD - 10 - 200
  const idealLeft = r.left + r.width / 2 - TOOLTIP_W / 2
  const left = Math.max(16, Math.min(idealLeft, vw - TOOLTIP_W - 16))
  // Arrow points to center of target, clamped inside tooltip
  const arrowLeft = Math.max(20, Math.min(r.left + r.width / 2 - left, TOOLTIP_W - 20))

  return { top, left, arrowSide: below ? 'top' : 'bottom', arrowLeft }
}

export default function TourOverlay() {
  const { active, stepIndex, step, totalSteps, targetRect, next, prev, skip } = useTour()
  const [pos, setPos] = useState<TooltipPos | null>(null)

  useEffect(() => {
    if (targetRect) setPos(calcTooltipPos(targetRect))
  }, [targetRect])

  if (!active || !step) return null
  const r = targetRect

  return (
    <div className="fixed inset-0 z-[9999] pointer-events-none">
      {/* Spotlight — 4 dark panels */}
      {r && (
        <>
          {/* top */}
          <div className="absolute pointer-events-auto"
            style={{ top: 0, left: 0, right: 0, height: Math.max(0, r.top - PAD), background: 'rgba(0,0,0,0.65)' }}
            onClick={skip} />
          {/* bottom */}
          <div className="absolute pointer-events-auto"
            style={{ top: r.bottom + PAD, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.65)' }}
            onClick={skip} />
          {/* left */}
          <div className="absolute pointer-events-auto"
            style={{ top: r.top - PAD, left: 0, width: Math.max(0, r.left - PAD), height: r.height + PAD * 2, background: 'rgba(0,0,0,0.65)' }}
            onClick={skip} />
          {/* right */}
          <div className="absolute pointer-events-auto"
            style={{ top: r.top - PAD, left: r.right + PAD, right: 0, height: r.height + PAD * 2, background: 'rgba(0,0,0,0.65)' }}
            onClick={skip} />
          {/* spotlight ring */}
          <div className="absolute rounded-xl pointer-events-none" style={{
            top: r.top - PAD, left: r.left - PAD,
            width: r.width + PAD * 2, height: r.height + PAD * 2,
            border: '2px solid rgba(102,126,234,0.8)',
            boxShadow: '0 0 0 1px rgba(102,126,234,0.15), 0 0 28px rgba(102,126,234,0.25)',
          }} />
        </>
      )}

      {/* Tooltip card */}
      <AnimatePresence mode="wait">
        {r && pos && (
          <motion.div
            key={stepIndex}
            initial={{ opacity: 0, y: pos.arrowSide === 'top' ? -10 : 10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="absolute pointer-events-auto"
            style={{ top: pos.top, left: pos.left, width: TOOLTIP_W }}
          >
            {/* Arrow — above tooltip (points down to element below) */}
            {pos.arrowSide === 'top' && (
              <div className="absolute -top-[7px] w-3.5 h-3.5 rotate-45 dark:bg-zinc-900 bg-white dark:border-white/[0.08] border-gray-200 border-t border-l"
                style={{ left: pos.arrowLeft - 7 }} />
            )}

            <div className="dark:bg-zinc-900/95 bg-white border dark:border-white/[0.08] border-gray-200 rounded-2xl shadow-2xl p-4">
              {/* Step counter + close */}
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold tracking-widest uppercase dark:text-white/30 text-gray-400">
                  {stepIndex + 1} of {totalSteps}
                </span>
                <button onClick={skip} className="dark:text-white/30 text-gray-400 dark:hover:text-white/60 hover:text-gray-600 transition-colors cursor-pointer p-0.5 rounded">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>

              <h3 className="font-semibold dark:text-white text-gray-900 mb-1.5 text-[15px]">{step.title}</h3>
              <p className="text-sm dark:text-white/55 text-gray-500 leading-relaxed mb-4">{step.body}</p>

              {/* Progress bar dots */}
              <div className="flex items-center gap-1.5 mb-4">
                {Array.from({ length: totalSteps }).map((_, i) => (
                  <div key={i} className={`h-[3px] rounded-full transition-all duration-300 ${
                    i === stepIndex ? 'w-5 bg-[#667eea]' : i < stepIndex ? 'w-2 bg-[#667eea]/40' : 'w-2 dark:bg-white/15 bg-gray-200'
                  }`} />
                ))}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2">
                {stepIndex > 0 && (
                  <button onClick={prev}
                    className="flex items-center gap-0.5 px-2.5 py-1.5 rounded-lg text-xs dark:text-white/50 text-gray-500 dark:hover:bg-white/[0.06] hover:bg-gray-100 transition-colors cursor-pointer">
                    <ChevronLeft className="w-3.5 h-3.5" />
                    Back
                  </button>
                )}
                <div className="flex-1" />
                <button onClick={skip}
                  className="text-xs dark:text-white/30 text-gray-400 dark:hover:text-white/60 hover:text-gray-600 transition-colors cursor-pointer px-1">
                  Skip tour
                </button>
                <button onClick={next}
                  className="flex items-center gap-1 px-3.5 py-1.5 rounded-lg text-xs font-medium bg-[#667eea] hover:bg-[#5b6fd4] text-white transition-colors cursor-pointer">
                  {stepIndex === totalSteps - 1 ? 'Done' : 'Next'}
                  {stepIndex < totalSteps - 1 && <ChevronRight className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* Arrow — below tooltip (points up to element above) */}
            {pos.arrowSide === 'bottom' && (
              <div className="absolute -bottom-[7px] w-3.5 h-3.5 rotate-45 dark:bg-zinc-900 bg-white dark:border-white/[0.08] border-gray-200 border-b border-r"
                style={{ left: pos.arrowLeft - 7 }} />
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
