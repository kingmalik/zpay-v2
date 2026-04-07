'use client'

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { api } from '@/lib/api'
import { formatDate, formatTime } from '@/lib/utils'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface ActivityEntry {
  id?: string | number
  user?: string
  action?: string
  entity_type?: string
  description?: string
  timestamp?: string
  entity_id?: string | number
}

const userColors: Record<string, string> = {
  malik: 'from-[#667eea] to-[#06b6d4]',
  mom: 'from-[#F59E0B] to-[#EC4899]',
  admin: 'from-[#10B981] to-[#06b6d4]',
}

export default function ActivityPage() {
  const [entries, setEntries] = useState<ActivityEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [user, setUser] = useState('all')
  const [users, setUsers] = useState<string[]>([])

  useEffect(() => {
    api.get<ActivityEntry[]>('/api/data/activity').then(data => {
      setEntries(data)
      const uniqueUsers = [...new Set(data.map(e => e.user || 'unknown').filter(Boolean))]
      setUsers(uniqueUsers)
    }).catch(console.error).finally(() => setLoading(false))
  }, [])

  const filtered = user === 'all' ? entries : entries.filter(e => e.user === user)

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-3xl mx-auto space-y-5 py-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold dark:text-white text-gray-900">Activity</h1>
          <p className="text-sm dark:text-white/40 text-gray-400 mt-0.5">{filtered.length} entries</p>
        </div>

        {/* User filter */}
        <select
          value={user}
          onChange={e => setUser(e.target.value)}
          className="px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60"
        >
          <option value="all">All Users</option>
          {users.map(u => <option key={u} value={u}>{u}</option>)}
        </select>
      </div>

      {/* Timeline */}
      <div className="relative">
        {/* Vertical line */}
        <div className="absolute left-5 top-0 bottom-0 w-0.5 dark:bg-white/8 bg-gray-200" />

        <div className="space-y-4">
          {filtered.map((entry, i) => {
            const u = (entry.user || 'unknown').toLowerCase()
            const gradient = userColors[u] || 'from-gray-500 to-gray-600'
            return (
              <motion.div
                key={entry.id || i}
                initial={{ opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.03 }}
                className="flex gap-4 pl-12 relative"
              >
                {/* Avatar */}
                <div className={`absolute left-0 w-10 h-10 rounded-full bg-gradient-to-br ${gradient} flex items-center justify-center text-white text-xs font-bold flex-shrink-0 z-10 ring-2 dark:ring-[#0f1219] ring-[#f0f2f8]`}>
                  {(entry.user || '?')[0].toUpperCase()}
                </div>

                {/* Card */}
                <div className="flex-1 dark:bg-white/5 bg-white border dark:border-white/8 border-gray-200 rounded-xl p-4">
                  <div className="flex items-start justify-between gap-2 mb-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold dark:text-white text-gray-800">{entry.user || 'Unknown'}</span>
                      <span className="text-xs px-2 py-0.5 rounded-full dark:bg-white/8 bg-gray-100 dark:text-white/50 text-gray-600">{entry.action || 'action'}</span>
                      {entry.entity_type && (
                        <span className="text-xs dark:text-white/30 text-gray-400">{entry.entity_type}</span>
                      )}
                    </div>
                    <span className="text-xs dark:text-white/30 text-gray-400 whitespace-nowrap flex-shrink-0">
                      {formatDate(entry.timestamp)} {formatTime(entry.timestamp)}
                    </span>
                  </div>
                  {entry.description && (
                    <p className="text-sm dark:text-white/60 text-gray-600">{entry.description}</p>
                  )}
                  {entry.entity_id && (
                    <p className="text-xs dark:text-white/20 text-gray-400 mt-1 font-mono">#{entry.entity_id}</p>
                  )}
                </div>
              </motion.div>
            )
          })}
          {filtered.length === 0 && (
            <div className="text-center py-12 dark:text-white/30 text-gray-400">No activity found</div>
          )}
        </div>
      </div>
    </div>
  )
}
