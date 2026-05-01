export default function ReliabilitySkeleton() {
  return (
    <div className="rounded-xl dark:bg-white/[0.03] bg-white border dark:border-white/[0.08] border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="border-b dark:border-white/[0.08] border-gray-100 px-4 py-3 flex gap-4">
        {Array.from({ length: 11 }).map((_, i) => (
          <div
            key={i}
            className="h-3 rounded-full dark:bg-white/10 bg-gray-200 animate-pulse"
            style={{ width: i === 0 ? 120 : i === 10 ? 40 : 56 }}
          />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-4 px-4 py-3.5 border-b last:border-0 dark:border-white/[0.05] border-gray-50"
          style={{ opacity: 1 - i * 0.09 }}
        >
          <div className="h-3 w-28 rounded-full dark:bg-white/8 bg-gray-100 animate-pulse" />
          <div className="h-5 w-16 rounded-full dark:bg-white/8 bg-gray-100 animate-pulse" />
          {Array.from({ length: 8 }).map((_, j) => (
            <div key={j} className="h-3 w-12 rounded-full dark:bg-white/5 bg-gray-100 animate-pulse" />
          ))}
        </div>
      ))}
    </div>
  )
}
