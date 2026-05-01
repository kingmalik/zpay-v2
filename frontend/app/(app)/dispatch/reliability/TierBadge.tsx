import { cn } from '@/lib/utils'

interface TierBadgeProps {
  tier: string
  label: string
  className?: string
}

// Matches the app's palette: /dispatch/manage uses emerald for best, amber for warnings
// Gold → amber (top tier), Silver → slate, Bronze → orange, Probation → red, No Activity → gray
const TIER_STYLES: Record<string, { pill: string; dot: string }> = {
  gold:        { pill: 'bg-amber-500/15 text-amber-400 border-amber-500/30',   dot: 'bg-amber-400' },
  silver:      { pill: 'bg-slate-500/15 text-slate-400 border-slate-500/30',   dot: 'bg-slate-400' },
  bronze:      { pill: 'bg-orange-500/15 text-orange-400 border-orange-500/30', dot: 'bg-orange-400' },
  probation:   { pill: 'bg-red-500/15 text-red-400 border-red-500/30',          dot: 'bg-red-400' },
  no_activity: { pill: 'bg-gray-500/15 text-gray-400 border-gray-500/30',       dot: 'bg-gray-400' },
}

const DEFAULT_STYLE = { pill: 'bg-gray-500/15 text-gray-400 border-gray-500/30', dot: 'bg-gray-400' }

export default function TierBadge({ tier, label, className }: TierBadgeProps) {
  const style = TIER_STYLES[tier] ?? DEFAULT_STYLE
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border',
      style.pill,
      className
    )}>
      <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', style.dot)} />
      {label}
    </span>
  )
}
