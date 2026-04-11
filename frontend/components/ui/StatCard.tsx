import { motion } from 'framer-motion'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { cn } from '@/lib/utils'

interface StatCardProps {
  label: string
  value: string | number | React.ReactNode
  icon?: React.ReactNode
  trend?: number // percent change, positive or negative
  trendLabel?: string
  color?: 'default' | 'success' | 'warning' | 'danger' | 'info'
  className?: string
  index?: number // for stagger animation
}

const colorMap = {
  default: 'text-[#667eea] bg-[#667eea]/10',
  success: 'text-emerald-500 bg-emerald-500/10',
  warning: 'text-amber-500 bg-amber-500/10',
  danger: 'text-red-500 bg-red-500/10',
  info: 'text-blue-500 bg-blue-500/10',
}

export default function StatCard({
  label, value, icon, trend, trendLabel, color = 'default', className, index = 0,
}: StatCardProps) {
  const iconColors = colorMap[color]

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: index * 0.06 }}
      className={cn(
        'rounded-xl p-5 transition-all duration-150',
        'dark:bg-white/[0.04] dark:border dark:border-white/[0.08]',
        'bg-white border border-gray-200 shadow-sm',
        'dark:hover:bg-white/[0.07]',
        className
      )}
    >
      <div className="flex items-start justify-between mb-3">
        <p className="text-sm font-medium dark:text-white/50 text-gray-500">{label}</p>
        {icon && (
          <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center', iconColors)}>
            {icon}
          </div>
        )}
      </div>
      <p className="text-2xl font-bold dark:text-[#fafafa] text-gray-900 tabular-nums">{value}</p>
      {trend !== undefined && (
        <div className="flex items-center gap-1 mt-2">
          {trend >= 0 ? (
            <TrendingUp className="w-3.5 h-3.5 text-emerald-500" />
          ) : (
            <TrendingDown className="w-3.5 h-3.5 text-red-500" />
          )}
          <span className={cn('text-xs font-medium', trend >= 0 ? 'text-emerald-500' : 'text-red-500')}>
            {trend >= 0 ? '+' : ''}{trend.toFixed(1)}%
          </span>
          {trendLabel && (
            <span className="text-xs dark:text-white/40 text-gray-400">{trendLabel}</span>
          )}
        </div>
      )}
    </motion.div>
  )
}
