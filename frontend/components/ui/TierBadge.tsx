import { cn } from '@/lib/utils'

export type Tier = 'gold' | 'silver' | 'bronze' | 'probation' | 'no_activity'

interface TierBadgeProps {
  tier: Tier | string
  className?: string
  compact?: boolean   // omit label, show only icon + short text
}

// Tier order constant — used externally by pages that sort drivers
export const TIER_ORDER: Record<string, number> = {
  gold: 1,
  silver: 2,
  bronze: 3,
  probation: 4,
  no_activity: 5,
}

const TIER_CONFIG: Record<string, {
  label: string
  shortLabel: string
  dotClass: string
  badgeClass: string
}> = {
  gold: {
    label: 'Gold',
    shortLabel: 'G',
    dotClass: 'bg-amber-400',
    badgeClass: 'bg-amber-500/[0.12] text-amber-400 border border-amber-500/[0.25] dark:bg-amber-500/[0.10] dark:border-amber-500/[0.20]',
  },
  silver: {
    label: 'Silver',
    shortLabel: 'S',
    dotClass: 'bg-slate-400',
    badgeClass: 'bg-slate-400/[0.12] text-slate-400 border border-slate-400/[0.25] dark:bg-slate-400/[0.10] dark:border-slate-400/[0.20]',
  },
  bronze: {
    label: 'Bronze',
    shortLabel: 'B',
    dotClass: 'bg-orange-500',
    badgeClass: 'bg-orange-500/[0.12] text-orange-400 border border-orange-500/[0.25] dark:bg-orange-500/[0.10] dark:border-orange-500/[0.20]',
  },
  probation: {
    label: 'Probation',
    shortLabel: 'P',
    dotClass: 'bg-red-500',
    badgeClass: 'bg-red-500/[0.10] text-red-400 border border-red-500/[0.20] dark:bg-red-500/[0.08] dark:border-red-500/[0.18]',
  },
  no_activity: {
    label: 'No data',
    shortLabel: '—',
    dotClass: 'bg-gray-500',
    badgeClass: 'dark:bg-white/[0.04] dark:text-white/30 dark:border-white/[0.10] bg-gray-100 text-gray-400 border border-gray-200',
  },
}

const FALLBACK = TIER_CONFIG.no_activity

export default function TierBadge({ tier, className, compact = false }: TierBadgeProps) {
  const config = TIER_CONFIG[tier] ?? FALLBACK

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
        config.badgeClass,
        className,
      )}
      title={config.label}
    >
      <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', config.dotClass)} />
      {compact ? config.shortLabel : config.label}
    </span>
  )
}
