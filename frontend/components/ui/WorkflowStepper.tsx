'use client'

import { motion } from 'framer-motion'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

interface WorkflowStepperProps {
  steps: string[]
  currentStep: number
  className?: string
}

export default function WorkflowStepper({ steps, currentStep, className }: WorkflowStepperProps) {
  return (
    <div className={cn('flex items-center w-full', className)}>
      {steps.map((step, i) => {
        const isComplete = i < currentStep
        const isCurrent = i === currentStep
        const isPending = i > currentStep

        return (
          <div key={step} className="flex items-center flex-1 last:flex-none">
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
                  'w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 z-10',
                  isComplete && 'border-emerald-500 text-white',
                  isCurrent && 'border-[#667eea] text-white shadow-lg shadow-[#667eea]/30',
                  isPending && 'border-white/20 text-white/40',
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
                )}
              >
                {step}
              </span>
            </div>

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
    </div>
  )
}
