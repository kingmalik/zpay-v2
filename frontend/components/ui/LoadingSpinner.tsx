import { cn } from '@/lib/utils'

interface LoadingSpinnerProps {
  className?: string
  size?: 'sm' | 'md' | 'lg'
  fullPage?: boolean
}

const sizeMap = { sm: 'w-5 h-5', md: 'w-8 h-8', lg: 'w-12 h-12' }

export default function LoadingSpinner({ className, size = 'md', fullPage }: LoadingSpinnerProps) {
  const spinner = (
    <div
      className={cn(
        'rounded-full border-2 border-transparent animate-spin',
        sizeMap[size],
        className
      )}
      style={{ borderTopColor: '#667eea', borderRightColor: '#06b6d4' }}
      role="status"
      aria-label="Loading"
    />
  )

  if (fullPage) {
    return (
      <div className="min-h-[400px] flex flex-col items-center justify-center gap-3">
        {spinner}
        <p className="text-sm dark:text-white/40 text-gray-400">Loading...</p>
      </div>
    )
  }

  return spinner
}
