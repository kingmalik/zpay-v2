'use client'

import { motion } from 'framer-motion'
import { Check, ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

interface WorkflowStepperProps {
  steps: string[]
  currentStep: number
  className?: string
  /** Admin-only: called with the step index when an admin clicks a step bubble. */
  onStepClick?: (stepIndex: number) => void
}

export default function WorkflowStepper({ steps, currentStep, className, onStepClick }: WorkflowStepperProps) {
  const isClickable = typeof onStepClick === 'function'
  const lastStep = steps.length - 1
  const isFirst = currentStep === 0
  const isLast = currentStep === lastStep

  return (
    <div className={cn('flex items-center w-full', isClickable ? 'gap-2' : '', className)}>
      {/* Left arrow — admin only */}
      {isClickable && (
        <button
          type="button"
          disabled={isFirst}
          onClick={() => onStepClick(currentStep - 1)}
          title="Previous step"
          aria-label="Previous step"
          className={cn(
            'flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-full border transition-all duration-150',
            isFirst
              ? 'border-white/10 text-white/20 cursor-not-allowed'
              : 'border-white/20 text-white/60 hover:border-[#667eea]/60 hover:text-[#667eea] hover:shadow-md hover:shadow-[#667eea]/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#667eea]/60',
          )}
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
      )}

      {steps.map((step, i) => {
        const isComplete = i < currentStep
        const isCurrent = i === currentStep
        const isPending = i > currentStep

        const bubble = (
          <div className="flex flex-col items-center gap-1.5 relative">
            <motion.div
              initial={false}
              animate={{
                scale: isCurrent ? 1.1 : 1,
                backgroundColor: isComplete
                  ? 'rgb(16 185 129)' // emerald-500
                  : isCurrent
                  ? 'rgb(102 126 234)' // zpay-accent
                  : 'rgb(255 255 255 / 0.1)',
              }}
              transition={{ duration: 0.3 }}
              className={cn(
                'w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 z-10 transition-shadow',
                isComplete && 'border-emerald-500 text-white',
                isCurrent && 'border-[#667eea] text-white shadow-lg shadow-[#667eea]/30',
                isPending && 'border-white/20 text-white/40',
                isClickable && !isCurrent && 'cursor-pointer hover:border-[#667eea]/60 hover:shadow-md hover:shadow-[#667eea]/20',
                isClickable && isCurrent && 'cursor-default',
              )}
            >
              {isComplete ? (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                >
                  <Check className="w-4 h-4" />
                </motion.div>
              ) : (
                <span>{i + 1}</span>
              )}
            </motion.div>
            <span
              className={cn(
                'text-[10px] font-medium whitespace-nowrap absolute -bottom-5',
                isComplete && 'text-emerald-400',
                isCurrent && 'text-[#667eea]',
                isPending && 'text-white/30',
                isClickable && !isCurrent && 'cursor-pointer',
              )}
            >
              {step}
            </span>
          </div>
        )

        return (
          <div key={step} className="flex items-center flex-1 last:flex-none">
            {isClickable && !isCurrent ? (
              <button
                type="button"
                onClick={() => onStepClick(i)}
                className="flex flex-col items-center gap-1.5 relative bg-transparent border-0 p-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#667eea]/60 rounded-full"
                aria-label={`Go to ${step} step`}
                title={`Jump to ${step} (admin only)`}
              >
                {bubble}
              </button>
            ) : (
              bubble
            )}

            {i < steps.length - 1 && (
              <div className="flex-1 mx-2 h-0.5 rounded-full overflow-hidden bg-white/10">
                <motion.div
                  initial={false}
                  animate={{ width: isComplete ? '100%' : '0%' }}
                  transition={{ duration: 0.4, delay: 0.1 }}
                  className="h-full bg-emerald-500 rounded-full"
                />
              </div>
            )}
          </div>
        )
      })}

      {/* Right arrow — admin only */}
      {isClickable && (
        <button
          type="button"
          disabled={isLast}
          onClick={() => onStepClick(currentStep + 1)}
          title="Next step"
          aria-label="Next step"
          className={cn(
            'flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-full border transition-all duration-150',
            isLast
              ? 'border-white/10 text-white/20 cursor-not-allowed'
              : 'border-white/20 text-white/60 hover:border-[#667eea]/60 hover:text-[#667eea] hover:shadow-md hover:shadow-[#667eea]/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#667eea]/60',
          )}
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      )}
    </div>
  )
}
