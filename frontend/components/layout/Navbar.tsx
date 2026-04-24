'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useTheme } from 'next-themes'
import { motion, AnimatePresence } from 'framer-motion'
import {
  LayoutDashboard, Users, Truck, FileText, Settings,
  Sun, Moon, LogOut, ChevronDown, Menu, X,
  Monitor, Navigation2, Puzzle, Building2,
  GitBranch, BookOpen, Bell, UserPlus,
  DollarSign, Mail, RefreshCw, Globe, User as UserIcon,
  ClipboardList, AlertTriangle, AlertCircle, CheckCircle2, X as XIcon, Activity
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCurrentUser } from '@/hooks/useCurrentUser'

type HealthIssue = {
  severity: 'error' | 'warning'
  type: string
  title: string
  detail: string
  batch_id: number | null
}

type HealthData = {
  ok: boolean
  error_count: number
  warning_count: number
  issues: HealthIssue[]
}

function useHealth() {
  const [data, setData] = useState<HealthData | null>(null)

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch('/api/data/health')
      if (res.ok) setData(await res.json())
    } catch {}
  }, [])

  useEffect(() => {
    fetch_()
    const id = setInterval(fetch_, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [fetch_])

  return { data, refresh: fetch_ }
}

type NavItem = {
  label: string
  href?: string
  icon: React.ReactNode
  children?: { label: string; href: string; icon: React.ReactNode }[]
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', href: '/', icon: <LayoutDashboard className="w-4 h-4" /> },
  {
    label: 'Dispatch',
    icon: <Truck className="w-4 h-4" />,
    children: [
      { label: 'Live Dispatch', href: '/dispatch', icon: <Navigation2 className="w-4 h-4" /> },
      { label: 'Trip Monitor', href: '/dispatch/monitor', icon: <Monitor className="w-4 h-4" /> },
      { label: 'Manage', href: '/dispatch/manage', icon: <Puzzle className="w-4 h-4" /> },
      { label: 'EverDriven', href: '/dispatch/everdriven', icon: <Building2 className="w-4 h-4" /> },
    ],
  },
  {
    label: 'Payroll',
    icon: <FileText className="w-4 h-4" />,
    children: [
      { label: 'Workflow', href: '/payroll/workflow', icon: <GitBranch className="w-4 h-4" /> },
      { label: 'Upload Files', href: '/upload', icon: <Truck className="w-4 h-4" /> },
      { label: 'Summary', href: '/payroll', icon: <FileText className="w-4 h-4" /> },
      { label: 'Batch Overview', href: '/summary', icon: <DollarSign className="w-4 h-4" /> },
      { label: 'History', href: '/payroll/history', icon: <BookOpen className="w-4 h-4" /> },
      { label: 'YTD', href: '/ytd', icon: <DollarSign className="w-4 h-4" /> },
      { label: 'Reconciliation', href: '/reconciliation', icon: <RefreshCw className="w-4 h-4" /> },
    ],
  },
  {
    label: 'People',
    icon: <Users className="w-4 h-4" />,
    children: [
      { label: 'All Drivers', href: '/people', icon: <Users className="w-4 h-4" /> },
      { label: 'Onboarding', href: '/onboarding', icon: <UserPlus className="w-4 h-4" /> },
      { label: 'Language Settings', href: '/drivers/language', icon: <Globe className="w-4 h-4" /> },
    ],
  },
  { label: 'Tasks', href: '/tasks', icon: <ClipboardList className="w-4 h-4" /> },
  { label: 'SOPs', href: '/sops', icon: <BookOpen className="w-4 h-4" /> },
  { label: 'Health', href: '/health', icon: <Activity className="w-4 h-4" /> },
  {
    label: 'Settings',
    icon: <Settings className="w-4 h-4" />,
    children: [
      { label: 'My Profile', href: '/settings/profile', icon: <UserIcon className="w-4 h-4" /> },
      { label: 'Team', href: '/settings/team', icon: <Users className="w-4 h-4" /> },
      { label: 'Rates', href: '/admin/rates', icon: <DollarSign className="w-4 h-4" /> },
      { label: 'Email Schedule', href: '/admin/email-schedule', icon: <Mail className="w-4 h-4" /> },
      { label: 'Paychex Sync', href: '/admin/paychex-sync', icon: <RefreshCw className="w-4 h-4" /> },
      { label: 'Email Templates', href: '/email-templates', icon: <Mail className="w-4 h-4" /> },
    ],
  },
]

const MOBILE_TABS = [
  { label: 'Home', href: '/', icon: <LayoutDashboard className="w-5 h-5" /> },
  { label: 'Tasks', href: '/tasks', icon: <ClipboardList className="w-5 h-5" /> },
  { label: 'Dispatch', href: '/dispatch', icon: <Truck className="w-5 h-5" /> },
  { label: 'Payroll', href: '/payroll', icon: <FileText className="w-5 h-5" /> },
  { label: 'People', href: '/people', icon: <Users className="w-5 h-5" /> },
]

// Simplified nav for operator (Mom) — only payroll-relevant pages
const OPERATOR_NAV_ITEMS: NavItem[] = [
  {
    label: 'Payroll',
    icon: <FileText className="w-4 h-4" />,
    children: [
      { label: 'Workflow', href: '/payroll/workflow', icon: <GitBranch className="w-4 h-4" /> },
      { label: 'Upload Files', href: '/upload', icon: <Truck className="w-4 h-4" /> },
      { label: 'Summary', href: '/payroll', icon: <FileText className="w-4 h-4" /> },
      { label: 'History', href: '/payroll/history', icon: <BookOpen className="w-4 h-4" /> },
    ],
  },
  {
    label: 'People',
    icon: <Users className="w-4 h-4" />,
    children: [
      { label: 'All Drivers', href: '/people', icon: <Users className="w-4 h-4" /> },
    ],
  },
]

const OPERATOR_MOBILE_TABS = [
  { label: 'Payroll', href: '/payroll/workflow', icon: <FileText className="w-5 h-5" /> },
  { label: 'Upload', href: '/upload', icon: <Truck className="w-5 h-5" /> },
  { label: 'History', href: '/payroll/history', icon: <BookOpen className="w-5 h-5" /> },
  { label: 'People', href: '/people', icon: <Users className="w-5 h-5" /> },
]

function DropdownMenu({ item, isOpen, onToggle }: { item: NavItem; isOpen: boolean; onToggle: () => void }) {
  const pathname = usePathname()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        if (isOpen) onToggle()
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [isOpen, onToggle])

  const isActive = item.children?.some(c => pathname === c.href || pathname.startsWith(c.href))

  return (
    <div ref={ref} className="relative">
      <button
        onClick={onToggle}
        className={cn(
          'flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors duration-150 cursor-pointer',
          isActive
            ? 'dark:text-[#fafafa] text-gray-900 dark:bg-white/[0.08] bg-gray-100'
            : 'dark:text-white/50 text-gray-500 dark:hover:text-[#fafafa] hover:text-gray-900 dark:hover:bg-white/[0.07] hover:bg-gray-100'
        )}
      >
        {item.icon}
        {item.label}
        <ChevronDown className={cn('w-3 h-3 transition-transform duration-150', isOpen && 'rotate-180')} />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.97 }}
            transition={{ duration: 0.15 }}
            className="absolute top-full left-0 mt-1.5 min-w-[180px] rounded-xl py-1 z-[999] dark:bg-[#111113] bg-white border dark:border-white/[0.08] border-gray-200 shadow-lg"
          >
            {item.children?.map(child => (
              <Link
                key={child.href}
                href={child.href}
                onClick={onToggle}
                className={cn(
                  'flex items-center gap-2.5 px-3 py-2 text-sm transition-colors duration-150',
                  pathname === child.href
                    ? 'dark:text-[#fafafa] text-gray-900 dark:bg-white/[0.08] bg-gray-100'
                    : 'dark:text-white/50 text-gray-500 dark:hover:text-[#fafafa] hover:text-gray-900 dark:hover:bg-white/[0.07] hover:bg-gray-50'
                )}
              >
                <span className="dark:text-white/30 text-gray-400">{child.icon}</span>
                {child.label}
              </Link>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default function Navbar() {
  const pathname = usePathname()
  const router = useRouter()
  const { resolvedTheme, setTheme } = useTheme()
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [healthOpen, setHealthOpen] = useState(false)
  const { data: health } = useHealth()
  const { isOperator } = useCurrentUser()
  const issueCount = health ? health.error_count + health.warning_count : 0

  const activeNavItems = isOperator ? OPERATOR_NAV_ITEMS : NAV_ITEMS
  const activeMobileTabs = isOperator ? OPERATOR_MOBILE_TABS : MOBILE_TABS

  useEffect(() => setMounted(true), [])

  if (pathname === '/login' || pathname.startsWith('/join') || pathname.startsWith('/training') || pathname.startsWith('/contract')) return null

  async function handleLogout() {
    await fetch('/api/auth/logout')
    router.push('/login')
    router.refresh()
  }

  return (
    <>
      {/* Desktop nav */}
      <nav className="hidden md:flex fixed top-0 left-0 right-0 z-50 h-14 border-b dark:border-white/[0.08] border-gray-200 items-center px-4 gap-1 dark:bg-[#09090b]/95 bg-white/95 backdrop-blur-sm">
        {/* Logo */}
        <Link href="/" className="mr-4 flex items-center gap-2">
          <span className="text-lg font-bold gradient-text">Z-Pay</span>
        </Link>

        {/* Nav items */}
        <div className="flex items-center gap-0.5 flex-1">
          {activeNavItems.map(item =>
            item.href ? (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors duration-150',
                  pathname === item.href
                    ? 'dark:text-[#fafafa] text-gray-900 dark:bg-white/[0.08] bg-gray-100'
                    : 'dark:text-white/50 text-gray-500 dark:hover:text-[#fafafa] hover:text-gray-900 dark:hover:bg-white/[0.07] hover:bg-gray-100'
                )}
              >
                {item.icon}
                {item.label}
              </Link>
            ) : (
              <DropdownMenu
                key={item.label}
                item={item}
                isOpen={openMenu === item.label}
                onToggle={() => setOpenMenu(openMenu === item.label ? null : item.label)}
              />
            )
          )}
        </div>

        {/* Right controls */}
        <div className="flex items-center gap-1">
          {/* Health bell */}
          <div className="relative">
            <button
              onClick={() => setHealthOpen(o => !o)}
              className="p-2 rounded-lg dark:text-white/40 text-gray-400 dark:hover:text-[#fafafa] hover:text-gray-700 dark:hover:bg-white/[0.07] hover:bg-gray-100 transition-colors duration-150 cursor-pointer relative"
              aria-label="System health"
            >
              <Bell className={cn('w-4 h-4', issueCount > 0 && 'text-red-400')} />
              {issueCount > 0 && (
                <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-red-500" />
              )}
              {health?.ok && (
                <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-emerald-500" />
              )}
            </button>

            <AnimatePresence>
              {healthOpen && (
                <motion.div
                  initial={{ opacity: 0, y: 6, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 6, scale: 0.97 }}
                  transition={{ duration: 0.15 }}
                  className="absolute top-full right-0 mt-2 w-80 rounded-xl z-[999] dark:bg-[#111113] bg-white border dark:border-white/[0.08] border-gray-200 shadow-xl overflow-hidden"
                >
                  <div className="flex items-center justify-between px-4 py-3 border-b dark:border-white/[0.08] border-gray-100">
                    <span className="text-sm font-semibold dark:text-white text-gray-900">System Health</span>
                    <button onClick={() => setHealthOpen(false)} className="dark:text-white/30 text-gray-400 hover:text-gray-600 cursor-pointer">
                      <XIcon className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  <div className="max-h-96 overflow-y-auto">
                    {!health && (
                      <div className="px-4 py-6 text-center text-sm dark:text-white/30 text-gray-400">Checking...</div>
                    )}
                    {health?.ok && (
                      <div className="flex items-center gap-3 px-4 py-4">
                        <CheckCircle2 className="w-5 h-5 text-emerald-500 flex-shrink-0" />
                        <div>
                          <p className="text-sm font-medium dark:text-white text-gray-900">Everything looks good</p>
                          <p className="text-xs dark:text-white/40 text-gray-500 mt-0.5">No issues detected</p>
                        </div>
                      </div>
                    )}
                    {health && !health.ok && health.issues.map((issue, i) => (
                      <div key={i} className={cn(
                        'flex gap-3 px-4 py-3 border-b last:border-0 dark:border-white/[0.06] border-gray-50',
                        issue.severity === 'error' ? 'dark:bg-red-500/5 bg-red-50/50' : 'dark:bg-amber-500/5 bg-amber-50/50'
                      )}>
                        {issue.severity === 'error'
                          ? <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
                          : <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                        }
                        <div className="min-w-0">
                          <p className="text-sm font-medium dark:text-white text-gray-900">{issue.title}</p>
                          <p className="text-xs dark:text-white/40 text-gray-500 mt-0.5 truncate">{issue.detail}</p>
                          {issue.batch_id && (
                            <a
                              href={`/payroll/history/${issue.batch_id}`}
                              className="text-xs text-[#667eea] hover:underline mt-1 inline-block"
                              onClick={() => setHealthOpen(false)}
                            >
                              View batch →
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {mounted && (
            <button
              onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
              className="p-2 rounded-lg dark:text-white/40 text-gray-400 dark:hover:text-[#fafafa] hover:text-gray-700 dark:hover:bg-white/[0.07] hover:bg-gray-100 transition-colors duration-150 cursor-pointer"
              aria-label="Toggle theme"
            >
              {resolvedTheme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          )}
          <button
            onClick={handleLogout}
            className="p-2 rounded-lg dark:text-white/40 text-gray-400 hover:text-red-400 hover:bg-red-500/10 transition-colors duration-150 cursor-pointer"
            aria-label="Sign out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </nav>

      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-50 h-12 border-b dark:border-white/[0.08] border-gray-200 flex items-center justify-between px-4 dark:bg-[#09090b]/95 bg-white/95 backdrop-blur-sm">
        <span className="text-base font-bold gradient-text">Z-Pay</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setHealthOpen(o => !o)}
            className="p-1.5 rounded-lg dark:text-white/40 text-gray-400 transition-colors cursor-pointer relative"
            aria-label="System health"
          >
            <Bell className={cn('w-4 h-4', issueCount > 0 && 'text-red-400')} />
            {issueCount > 0 && <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-red-500" />}
            {health?.ok && <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-emerald-500" />}
          </button>
          {mounted && (
            <button
              onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
              className="p-1.5 rounded-lg dark:text-white/40 text-gray-400 dark:hover:text-[#fafafa] hover:text-gray-700 transition-colors cursor-pointer"
            >
              {resolvedTheme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          )}
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            className="p-1.5 rounded-lg dark:text-white/40 text-gray-400 dark:hover:text-[#fafafa] hover:text-gray-700 transition-colors cursor-pointer"
          >
            {mobileOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Mobile drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, x: '100%' }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: '100%' }}
            transition={{ type: 'spring', damping: 30, stiffness: 300 }}
            className="md:hidden fixed inset-0 z-30 dark:bg-[#09090b]/97 bg-white/97 backdrop-blur-sm pt-12 overflow-y-auto"
          >
            <div className="p-4 space-y-1">
              {activeNavItems.map(item => (
                <div key={item.label}>
                  {item.href ? (
                    <Link
                      href={item.href}
                      onClick={() => setMobileOpen(false)}
                      className={cn(
                        'flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-colors duration-150',
                        pathname === item.href
                          ? 'bg-[#667eea]/15 dark:text-[#fafafa] text-gray-900'
                          : 'dark:text-white/50 text-gray-500 dark:hover:text-[#fafafa] hover:text-gray-900 dark:hover:bg-white/[0.07] hover:bg-gray-100'
                      )}
                    >
                      {item.icon}
                      {item.label}
                    </Link>
                  ) : (
                    <div>
                      <div className="px-4 py-2 text-xs dark:text-white/30 text-gray-400 uppercase tracking-wider font-semibold">{item.label}</div>
                      {item.children?.map(child => (
                        <Link
                          key={child.href}
                          href={child.href}
                          onClick={() => setMobileOpen(false)}
                          className={cn(
                            'flex items-center gap-3 px-6 py-2.5 rounded-xl text-sm transition-colors duration-150',
                            pathname === child.href
                              ? 'bg-[#667eea]/15 dark:text-[#fafafa] text-gray-900'
                              : 'dark:text-white/40 text-gray-400 dark:hover:text-[#fafafa] hover:text-gray-900 dark:hover:bg-white/[0.07] hover:bg-gray-50'
                          )}
                        >
                          <span className="dark:text-white/25 text-gray-300">{child.icon}</span>
                          {child.label}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              <div className="pt-4 border-t dark:border-white/[0.08] border-gray-200">
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-3 px-4 py-3 rounded-xl text-sm text-red-400 hover:bg-red-500/10 w-full transition-colors cursor-pointer"
                >
                  <LogOut className="w-4 h-4" />
                  Sign out
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Mobile bottom tab bar */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 border-t dark:border-white/[0.08] border-gray-200 flex dark:bg-[#09090b]/95 bg-white/95 backdrop-blur-sm">
        {activeMobileTabs.map(tab => (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              'flex-1 flex flex-col items-center gap-1 py-2 text-xs font-medium transition-colors duration-150',
              pathname === tab.href || (tab.href !== '/' && pathname.startsWith(tab.href))
                ? 'text-[#667eea]'
                : 'dark:text-white/35 text-gray-400 dark:hover:text-white/60 hover:text-gray-600'
            )}
          >
            {tab.icon}
            {tab.label}
          </Link>
        ))}
      </nav>
    </>
  )
}
