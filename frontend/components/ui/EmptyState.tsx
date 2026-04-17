import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  icon?: React.ReactNode
  title: string
  subtitle?: string
  action?: {
    label: string
    onClick: () => void
  }
  className?: string
}

export default function EmptyState({ icon, title, subtitle, action, className }: EmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn('flex flex-col items-center justify-center py-16 text-center', className)}
    >
      {icon && (
        <div className="w-16 h-16 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center mb-4 text-white/20">
          {icon}
        </div>
      )}
      <h3 className="text-base font-semibold dark:text-white/70 text-gray-600 mb-1">{title}</h3>
      {subtitle && <p className="text-sm dark:text-white/40 text-gray-400 max-w-xs">{subtitle}</p>}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-4 px-4 py-2 text-sm bg-[#667eea] hover:bg-[#5b6fd4] text-white font-medium rounded-lg transition-colors duration-150 cursor-pointer"
        >
          {action.label}
        </button>
      )}
    </motion.div>
  )
}
