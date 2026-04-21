'use client'

import { motion, AnimatePresence } from 'framer-motion'
import { ClipboardList, Trash2 } from 'lucide-react'

interface SessionBarProps {
  changeCount: number
  onViewSummary: () => void
  onClear: () => void
}

export default function SessionBar({ changeCount, onViewSummary, onClear }: SessionBarProps) {
  return (
    <AnimatePresence>
      {changeCount > 0 && (
        <motion.div
          key="session-bar"
          initial={{ y: 80, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 80, opacity: 0 }}
          transition={{ type: 'spring', damping: 22, stiffness: 260 }}
          className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-5 py-3 rounded-2xl
            dark:bg-[#1a1a2e]/95 bg-white/95 backdrop-blur-xl
            border dark:border-white/10 border-gray-200
            shadow-xl shadow-black/20"
        >
          <div className="flex items-center gap-2">
            <span className="flex items-center justify-center w-6 h-6 rounded-full bg-[#667eea] text-white text-xs font-bold">
              {changeCount}
            </span>
            <span className="text-sm font-medium dark:text-white/80 text-gray-700 whitespace-nowrap">
              {changeCount === 1 ? 'change' : 'changes'} this session
            </span>
          </div>

          <div className="w-px h-5 dark:bg-white/10 bg-gray-200" />

          <button
            onClick={onViewSummary}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold
              bg-[#667eea] hover:bg-[#5a6fd6] text-white transition-all cursor-pointer"
          >
            <ClipboardList className="w-3.5 h-3.5" />
            View Summary
          </button>

          <button
            onClick={onClear}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold
              dark:bg-white/8 bg-gray-100 dark:hover:bg-white/12 hover:bg-gray-200
              dark:text-white/60 text-gray-600 transition-all cursor-pointer"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Clear
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
