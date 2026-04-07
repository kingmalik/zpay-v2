import { cn } from '@/lib/utils'

interface GlassCardProps {
  children: React.ReactNode
  className?: string
  hover?: boolean
  padding?: boolean
}

export default function GlassCard({ children, className, hover = false, padding = true }: GlassCardProps) {
  return (
    <div
      className={cn(
        'rounded-2xl transition-all duration-200',
        // Dark mode: glass
        'dark:bg-white/5 dark:backdrop-blur-xl dark:border dark:border-white/10 dark:shadow-glass',
        // Light mode: white card
        'bg-white border border-gray-200 shadow-card',
        hover && 'dark:hover:bg-white/8 dark:hover:border-white/20 dark:hover:shadow-glass-hover hover:shadow-lg cursor-pointer',
        padding && 'p-5',
        className
      )}
    >
      {children}
    </div>
  )
}
