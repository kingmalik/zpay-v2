import { cn } from '@/lib/utils'

type BadgeVariant = 'fa' | 'ed' | 'active' | 'inactive' | 'warning' | 'danger' | 'success' | 'info' | 'draft' | 'final' | 'default'

interface BadgeProps {
  variant?: BadgeVariant
  children: React.ReactNode
  className?: string
  dot?: boolean
}

const variants: Record<BadgeVariant, string> = {
  fa: 'bg-indigo-500/15 text-indigo-400 border border-indigo-500/30',
  ed: 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30',
  active: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30',
  success: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30',
  inactive: 'bg-gray-500/15 text-gray-400 border border-gray-500/30',
  warning: 'bg-amber-500/15 text-amber-400 border border-amber-500/30',
  danger: 'bg-red-500/15 text-red-400 border border-red-500/30',
  info: 'bg-blue-500/15 text-blue-400 border border-blue-500/30',
  draft: 'bg-amber-500/15 text-amber-400 border border-amber-500/30',
  final: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30',
  default: 'bg-white/10 text-white/70 border border-white/20',
}

export default function Badge({ variant = 'default', children, className, dot }: BadgeProps) {
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium', variants[variant], className)}>
      {dot && <span className={cn('w-1.5 h-1.5 rounded-full', {
        'bg-indigo-400': variant === 'fa',
        'bg-cyan-400': variant === 'ed',
        'bg-emerald-400': variant === 'active' || variant === 'success' || variant === 'final',
        'bg-gray-400': variant === 'inactive',
        'bg-amber-400': variant === 'warning' || variant === 'draft',
        'bg-red-400': variant === 'danger',
        'bg-blue-400': variant === 'info',
      })} />}
      {children}
    </span>
  )
}
