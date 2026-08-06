'use client'

import { Accessibility, Armchair, Baby, ShieldCheck, Users } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { RequiresFlags } from './types'

const REQUIREMENT_META: { key: keyof RequiresFlags; label: string; icon: React.ReactNode }[] = [
  { key: 'wheelchair', label: 'Wheelchair', icon: <Accessibility className="w-3.5 h-3.5" /> },
  { key: 'car_seat', label: 'Car seat', icon: <Baby className="w-3.5 h-3.5" /> },
  { key: 'booster', label: 'Booster', icon: <Armchair className="w-3.5 h-3.5" /> },
  { key: 'harness', label: 'Harness', icon: <ShieldCheck className="w-3.5 h-3.5" /> },
  { key: 'monitor', label: 'Monitor', icon: <Users className="w-3.5 h-3.5" /> },
]

interface RequirementIconsProps {
  requires: RequiresFlags | undefined | null
  className?: string
}

export default function RequirementIcons({ requires, className }: RequirementIconsProps) {
  const active = REQUIREMENT_META.filter(r => requires?.[r.key])
  if (active.length === 0) return null

  return (
    <div className={cn('flex items-center gap-1', className)}>
      {active.map(r => (
        <span
          key={r.key}
          title={r.label}
          className="flex items-center justify-center w-5 h-5 rounded-md dark:bg-[#667eea]/15 bg-[#667eea]/10 text-[#667eea]"
        >
          {r.icon}
        </span>
      ))}
    </div>
  )
}

export { REQUIREMENT_META }
