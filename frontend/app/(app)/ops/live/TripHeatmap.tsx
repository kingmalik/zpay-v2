'use client'

import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Grid3x3, RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

interface HeatmapData {
  days: string[]
  hours: number[]
  matrix: number[][]
  peak_count: number
  window_start: string
  window_end: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Map a normalised intensity [0,1] to an oklch-based color string */
function intensityColor(ratio: number): string {
  if (ratio === 0) return 'transparent'
  // Low → indigo tint, high → vivid indigo
  const alpha = 0.12 + ratio * 0.82
  return `rgba(102, 126, 234, ${alpha.toFixed(2)})`
}

/** Format an hour integer as "6 AM" / "12 PM" etc */
function hourLabel(h: number): string {
  if (h === 0) return '12a'
  if (h === 12) return '12p'
  return h < 12 ? `${h}a` : `${h - 12}p`
}

// Hours to show tick labels for (every 3rd, plus midnight/noon)
const LABELED_HOURS = new Set([0, 3, 6, 9, 12, 15, 18, 21])

// ── Component ─────────────────────────────────────────────────────────────────

export default function TripHeatmap() {
  const [data, setData] = useState<HeatmapData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tooltip, setTooltip] = useState<{ day: string; hour: number; count: number } | null>(null)

  const fetch = useCallback(() => {
    setLoading(true)
    api.get<HeatmapData>('/ops-dashboard/heatmap')
      .then(d => { setData(d); setError(null) })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load heatmap'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    fetch()
    // Refresh every 5 minutes — heatmap is not real-time critical
    const id = setInterval(fetch, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [fetch])

  if (loading && !data) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-8 flex items-center justify-center">
        <RefreshCw className="w-4 h-4 text-white/20 animate-spin" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-5 text-xs text-red-400">
        {error ?? 'No data'}
      </div>
    )
  }

  const peak = data.peak_count || 1

  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4 space-y-3">
      {/* Meta row */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest font-bold text-white/25">
          {data.window_start} → {data.window_end}
        </span>
        {tooltip && (
          <motion.span
            key={`${tooltip.day}-${tooltip.hour}`}
            initial={{ opacity: 0, y: -2 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-xs text-white/65 tabular-nums"
          >
            {tooltip.day} {hourLabel(tooltip.hour)} — {tooltip.count} trip{tooltip.count !== 1 ? 's' : ''}
          </motion.span>
        )}
      </div>

      {/* Grid */}
      <div className="overflow-x-auto">
        <div
          className="grid"
          style={{
            display: 'grid',
            gridTemplateColumns: `28px repeat(24, 1fr)`,
            gap: 2,
            minWidth: 520,
          }}
        >
          {/* Hour axis header row */}
          <div /> {/* empty corner */}
          {data.hours.map(h => (
            <div
              key={h}
              className="h-4 flex items-center justify-center"
            >
              {LABELED_HOURS.has(h) && (
                <span className="text-[8px] text-white/20 tabular-nums leading-none">
                  {hourLabel(h)}
                </span>
              )}
            </div>
          ))}

          {/* Data rows — one per day */}
          {data.days.map((dayLabel, dayIdx) => (
            <>
              {/* Day label */}
              <div
                key={`label-${dayIdx}`}
                className="flex items-center justify-end pr-2"
                style={{ height: 20 }}
              >
                <span className="text-[10px] text-white/30 font-medium">{dayLabel}</span>
              </div>

              {/* 24 cells */}
              {data.hours.map(h => {
                const count = data.matrix[dayIdx]?.[h] ?? 0
                const ratio = peak > 0 ? count / peak : 0
                const bg = intensityColor(ratio)

                return (
                  <motion.div
                    key={`${dayIdx}-${h}`}
                    className={cn(
                      'rounded-sm cursor-default transition-all duration-150',
                      count > 0 ? 'hover:scale-125 hover:z-10' : '',
                    )}
                    style={{
                      height: 20,
                      background: bg,
                      border: count > 0 ? '1px solid rgba(102,126,234,0.25)' : '1px solid rgba(255,255,255,0.04)',
                    }}
                    onMouseEnter={() => setTooltip({ day: dayLabel, hour: h, count })}
                    onMouseLeave={() => setTooltip(null)}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: (dayIdx * 24 + h) * 0.001 }}
                  />
                )
              })}
            </>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-2 pt-1">
        <span className="text-[10px] text-white/20">0</span>
        <div
          className="h-2 rounded-sm flex-1"
          style={{
            background: 'linear-gradient(to right, rgba(102,126,234,0.12), rgba(102,126,234,0.94))',
          }}
        />
        <span className="text-[10px] text-white/20">{peak}</span>
        <Grid3x3 className="w-3 h-3 text-white/15 ml-1" />
      </div>
    </div>
  )
}
