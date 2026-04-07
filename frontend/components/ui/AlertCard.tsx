'use client'

import { AlertTriangle, AlertCircle, Info, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface AlertCardProps {
  severity: 'warning' | 'error' | 'info'
  title: string
  description?: string
  action?: React.ReactNode
  onDismiss?: () => void
  className?: string
}

const config = {
  warning: {
    icon: AlertTriangle,
    bg: 'bg-amber-500/10 border-amber-500/30',
    iconColor: 'text-amber-400',
    titleColor: 'text-amber-300',
  },
  error: {
    icon: AlertCircle,
    bg: 'bg-red-500/10 border-red-500/30',
    iconColor: 'text-red-400',
    titleColor: 'text-red-300',
  },
  info: {
    icon: Info,
    bg: 'bg-blue-500/10 border-blue-500/30',
    iconColor: 'text-blue-400',
    titleColor: 'text-blue-300',
  },
}

export default function AlertCard({ severity, title, description, action, onDismiss, className }: AlertCardProps) {
  const { icon: Icon, bg, iconColor, titleColor } = config[severity]

  return (
    <div className={cn('rounded-xl border p-3 flex items-start gap-3', bg, className)}>
      <Icon className={cn('w-5 h-5 mt-0.5 shrink-0', iconColor)} />
      <div className="flex-1 min-w-0">
        <p className={cn('text-sm font-medium', titleColor)}>{title}</p>
        {description && <p className="text-xs text-white/50 mt-0.5">{description}</p>}
        {action && <div className="mt-2">{action}</div>}
      </div>
      {onDismiss && (
        <button onClick={onDismiss} className="text-white/30 hover:text-white/60 transition-colors">
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  )
}
