import { cn } from '@/lib/utils'

interface PageHeaderProps {
  title: string
  subtitle?: string
  icon?: React.ReactNode
  actions?: React.ReactNode
  className?: string
}

export default function PageHeader({ title, subtitle, icon, actions, className }: PageHeaderProps) {
  return (
    <div className={cn('flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3', className)}>
      <div className="flex items-start gap-3">
        {icon && (
          <div className="w-9 h-9 rounded-xl dark:bg-white/[0.06] bg-gray-100 flex items-center justify-center flex-shrink-0 dark:text-white/60 text-gray-500 mt-0.5">
            {icon}
          </div>
        )}
        <div>
          <h1 className="text-2xl font-bold dark:text-white text-gray-900 leading-tight">{title}</h1>
          {subtitle && (
            <p className="text-sm dark:text-white/50 text-gray-500 mt-0.5">{subtitle}</p>
          )}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2 sm:flex-shrink-0">{actions}</div>}
    </div>
  )
}
