'use client'

import Link from 'next/link'
import { motion } from 'framer-motion'
import {
  GitCompare, TrendingUp, Activity, Bell,
  Users, User, ChevronRight,
} from 'lucide-react'

interface SettingsLink {
  href: string
  label: string
  description: string
  icon: React.ReactNode
  color: string
}

const SETTINGS_LINKS: SettingsLink[] = [
  {
    href: '/reconciliation',
    label: 'Reconciliation',
    description: 'FirstAlt vs Maz cross-check — accuracy auditing',
    icon: <GitCompare className="w-5 h-5" />,
    color: 'from-blue-500/20 to-blue-600/10 border-blue-500/25 text-blue-400',
  },
  {
    href: '/ytd',
    label: 'Year to Date',
    description: 'Driver earnings summary for tax season',
    icon: <TrendingUp className="w-5 h-5" />,
    color: 'from-emerald-500/20 to-emerald-600/10 border-emerald-500/25 text-emerald-400',
  },
  {
    href: '/activity',
    label: 'Activity Log',
    description: 'Audit trail — who did what and when',
    icon: <Activity className="w-5 h-5" />,
    color: 'from-purple-500/20 to-purple-600/10 border-purple-500/25 text-purple-400',
  },
  {
    href: '/alerts',
    label: 'Alerts',
    description: 'System notifications and flagged issues',
    icon: <Bell className="w-5 h-5" />,
    color: 'from-amber-500/20 to-amber-600/10 border-amber-500/25 text-amber-400',
  },
  {
    href: '/people/audit',
    label: 'Driver Audit',
    description: 'Duplicate detection and data cleanup',
    icon: <Users className="w-5 h-5" />,
    color: 'from-red-500/20 to-red-600/10 border-red-500/25 text-red-400',
  },
  {
    href: '/settings/profile',
    label: 'My Profile',
    description: 'Personal account settings',
    icon: <User className="w-5 h-5" />,
    color: 'from-gray-500/20 to-gray-600/10 border-gray-500/25 dark:text-white/60 text-gray-500',
  },
]

export default function SettingsPage() {
  return (
    <div className="max-w-2xl mx-auto py-10 space-y-6">
      <div>
        <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">Settings</h1>
        <p className="text-sm dark:text-white/40 text-gray-500 mt-1">
          Tools you won&apos;t need every day — auditing, forensics, and account settings.
        </p>
      </div>

      <div className="space-y-2">
        {SETTINGS_LINKS.map((item, i) => (
          <motion.div
            key={item.href}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
          >
            <Link
              href={item.href}
              className="flex items-center gap-4 p-4 rounded-xl border dark:bg-white/[0.03] bg-white dark:border-white/[0.08] border-gray-200 dark:hover:bg-white/[0.06] hover:bg-gray-50 transition-all group"
            >
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center bg-gradient-to-br border ${item.color}`}>
                {item.icon}
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-sm dark:text-white text-gray-900">{item.label}</p>
                <p className="text-xs dark:text-white/40 text-gray-500 mt-0.5">{item.description}</p>
              </div>
              <ChevronRight className="w-4 h-4 dark:text-white/20 text-gray-300 group-hover:dark:text-white/50 group-hover:text-gray-500 transition-colors flex-shrink-0" />
            </Link>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
