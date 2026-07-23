'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ClipboardPaste, ListTree, PhoneCall } from 'lucide-react'
import HomeGapNag from './HomeGapNag'
import IntakePanel from './IntakePanel'
import RosterPanel from './RosterPanel'
import CoveragePanel from './CoveragePanel'

type TabKey = 'intake' | 'rosters' | 'coverage'

const TABS: { key: TabKey; label: string; icon: React.ReactNode }[] = [
  { key: 'intake', label: 'New Ride', icon: <ClipboardPaste className="w-3.5 h-3.5" /> },
  { key: 'rosters', label: 'Rosters', icon: <ListTree className="w-3.5 h-3.5" /> },
  { key: 'coverage', label: 'Coverage', icon: <PhoneCall className="w-3.5 h-3.5" /> },
]

export default function AssignmentHelperPage() {
  const [tab, setTab] = useState<TabKey>('intake')

  return (
    <div className="max-w-5xl mx-auto space-y-5 py-6 px-4">
      <div>
        <h1 className="text-2xl font-bold dark:text-white text-gray-900">Assignment Helper</h1>
        <p className="text-sm dark:text-white/45 text-gray-500 mt-0.5">
          New rides, standing backups, and who covers when someone calls out.
        </p>
      </div>

      <HomeGapNag />

      <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100 w-fit">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={[
              'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer',
              tab === t.key
                ? 'dark:bg-white/10 bg-white dark:text-white text-gray-900 shadow-sm'
                : 'dark:text-white/40 text-gray-400 dark:hover:text-white/60 hover:text-gray-600',
            ].join(' ')}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.15 }}
        >
          {tab === 'intake' && <IntakePanel />}
          {tab === 'rosters' && <RosterPanel />}
          {tab === 'coverage' && <CoveragePanel />}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
