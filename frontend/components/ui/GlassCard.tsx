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
        'rounded-xl transition-all duration-150',
        // Dark mode: flat bordered card, no blur
        'dark:bg-white/[0.04] dark:border dark:border-white/[0.08]',
        // Light mode: white card
        'bg-white border border-gray-200 shadow-sm',
        hover && 'dark:hover:bg-white/[0.07] dark:hover:border-white/[0.12] hover:shadow-md cursor-pointer',
        padding && 'p-5',
        className
      )}
    >
      {children}
    </div>
  )
}
