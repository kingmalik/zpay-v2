'use client'

import { useState, useRef, useEffect } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useTheme } from 'next-themes'
import { motion, AnimatePresence } from 'framer-motion'
import {
  LayoutDashboard, Users, Truck, FileText, BarChart2, Settings,
  Sun, Moon, LogOut, ChevronDown, Menu, X,
  Monitor, Navigation2, Puzzle, Building2,
  TrendingUp, Brain, Calendar, BookOpen,
  GitBranch, Activity, Bell, CheckSquare,
  DollarSign, Mail, RefreshCw, Shield, UserPlus, ClipboardList
} from 'lucide-react'
import { cn } from '@/lib/utils'

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
      { label: 'Summary', href: '/payroll', icon: <FileText className="w-4 h-4" /> },
      { label: 'History', href: '/payroll/history', icon: <BookOpen className="w-4 h-4" /> },
      { label: 'Upload Files', href: '/upload', icon: <Truck className="w-4 h-4" /> },
    ],
  },
  { label: 'People', href: '/people', icon: <Users className="w-4 h-4" /> },
  { label: 'Onboarding', href: '/onboarding', icon: <UserPlus className="w-4 h-4" /> },
  { label: 'Ops Board', href: '/ops', icon: <ClipboardList className="w-4 h-4" /> },
  {
    label: 'Analytics',
    icon: <BarChart2 className="w-4 h-4" />,
    children: [
      { label: 'Analytics', href: '/analytics', icon: <BarChart2 className="w-4 h-4" /> },
      { label: 'Insights', href: '/insights', icon: <TrendingUp className="w-4 h-4" /> },
      { label: 'Intelligence', href: '/intelligence', icon: <Brain className="w-4 h-4" /> },
      { label: 'YTD', href: '/ytd', icon: <Calendar className="w-4 h-4" /> },
      { label: 'Rides', href: '/rides', icon: <Navigation2 className="w-4 h-4" /> },
    ],
  },
  {
    label: 'Ops',
    icon: <Shield className="w-4 h-4" />,
    children: [
      { label: 'Reconciliation', href: '/reconciliation', icon: <GitBranch className="w-4 h-4" /> },
      { label: 'Activity', href: '/activity', icon: <Activity className="w-4 h-4" /> },
      { label: 'Alerts', href: '/alerts', icon: <Bell className="w-4 h-4" /> },
      { label: 'Validate', href: '/validate', icon: <CheckSquare className="w-4 h-4" /> },
    ],
  },
  {
    label: 'Admin',
    icon: <Settings className="w-4 h-4" />,
    children: [
      { label: 'Rates', href: '/admin/rates', icon: <DollarSign className="w-4 h-4" /> },
      { label: 'Email Schedule', href: '/admin/email-schedule', icon: <Mail className="w-4 h-4" /> },
      { label: 'Paychex Sync', href: '/admin/paychex-sync', icon: <RefreshCw className="w-4 h-4" /> },
      { label: 'Email Templates', href: '/email-templates', icon: <Mail className="w-4 h-4" /> },
    ],
  },
]

const MOBILE_TABS = [
  { label: 'Home', href: '/', icon: <LayoutDashboard className="w-5 h-5" /> },
  { label: 'Dispatch', href: '/dispatch', icon: <Truck className="w-5 h-5" /> },
  { label: 'Payroll', href: '/payroll', icon: <FileText className="w-5 h-5" /> },
  { label: 'People', href: '/people', icon: <Users className="w-5 h-5" /> },
  { label: 'More', href: '/analytics', icon: <BarChart2 className="w-5 h-5" /> },
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
          'flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer',
          isActive
            ? 'dark:text-white text-gray-900 dark:bg-white/10 bg-gray-100'
            : 'dark:text-white/60 text-gray-500 dark:hover:text-white hover:text-gray-900 dark:hover:bg-white/8 hover:bg-gray-100'
        )}
      >
        {item.icon}
        {item.label}
        <ChevronDown className={cn('w-3 h-3 transition-transform', isOpen && 'rotate-180')} />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.96 }}
            transition={{ duration: 0.15 }}
            className="absolute top-full left-0 mt-1 min-w-[180px] rounded-xl shadow-lg py-1 z-[999] bg-white dark:bg-[#1a1f2e] border border-gray-200 dark:border-white/10"
          >
            {item.children?.map(child => (
              <Link
                key={child.href}
                href={child.href}
                onClick={onToggle}
                className={cn(
                  'flex items-center gap-2.5 px-3 py-2 text-sm transition-colors',
                  pathname === child.href
                    ? 'dark:text-white text-gray-900 dark:bg-white/10 bg-gray-100'
                    : 'dark:text-white/60 text-gray-500 dark:hover:text-white hover:text-gray-900 dark:hover:bg-white/8 hover:bg-gray-50'
                )}
              >
                <span className="dark:text-white/40 text-gray-400">{child.icon}</span>
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

  useEffect(() => setMounted(true), [])

  if (pathname === '/login') return null

  async function handleLogout() {
    await fetch('/api/auth/logout')
    router.push('/login')
    router.refresh()
  }

  return (
    <>
      {/* Desktop nav */}
      <nav className="hidden md:flex fixed top-0 left-0 right-0 z-50 h-14 border-b dark:border-white/10 border-gray-200 items-center px-4 gap-1 bg-white dark:bg-[#0f1219]/95 backdrop-blur-xl">
        {/* Logo */}
        <Link href="/" className="mr-4 flex items-center gap-2">
          <span className="text-lg font-bold gradient-text">Z-Pay</span>
        </Link>

        {/* Nav items */}
        <div className="flex items-center gap-0.5 flex-1">
          {NAV_ITEMS.map(item =>
            item.href ? (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-all',
                  pathname === item.href
                    ? 'dark:text-white text-gray-900 dark:bg-white/10 bg-gray-100'
                    : 'dark:text-white/60 text-gray-500 dark:hover:text-white hover:text-gray-900 dark:hover:bg-white/8 hover:bg-gray-100'
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
        <div className="flex items-center gap-2">
          {mounted && (
            <button
              onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
              className="p-2 rounded-lg dark:text-white/50 text-gray-400 dark:hover:text-white hover:text-gray-700 dark:hover:bg-white/8 hover:bg-gray-100 transition-all cursor-pointer"
              aria-label="Toggle theme"
            >
              {resolvedTheme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          )}
          <button
            onClick={handleLogout}
            className="p-2 rounded-lg dark:text-white/50 text-gray-400 hover:text-red-400 hover:bg-red-500/10 transition-all cursor-pointer"
            aria-label="Sign out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </nav>

      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-50 h-12 border-b dark:border-white/10 border-gray-200 flex items-center justify-between px-4 bg-white dark:bg-[#0f1219]/95 backdrop-blur-xl">
        <span className="text-base font-bold gradient-text">Z-Pay</span>
        <div className="flex items-center gap-2">
          {mounted && (
            <button
              onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
              className="p-1.5 rounded-lg dark:text-white/50 text-gray-400 dark:hover:text-white hover:text-gray-700 transition-colors cursor-pointer"
            >
              {resolvedTheme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          )}
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            className="p-1.5 rounded-lg dark:text-white/50 text-gray-400 dark:hover:text-white hover:text-gray-700 transition-colors cursor-pointer"
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
            className="md:hidden fixed inset-0 z-30 dark:bg-[#0f1219]/95 bg-white/95 backdrop-blur-xl pt-12 overflow-y-auto"
          >
            <div className="p-4 space-y-1">
              {NAV_ITEMS.map(item => (
                <div key={item.label}>
                  {item.href ? (
                    <Link
                      href={item.href}
                      onClick={() => setMobileOpen(false)}
                      className={cn(
                        'flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all',
                        pathname === item.href
                          ? 'bg-[#667eea]/20 dark:text-white text-gray-900'
                          : 'dark:text-white/60 text-gray-500 dark:hover:text-white hover:text-gray-900 dark:hover:bg-white/8 hover:bg-gray-100'
                      )}
                    >
                      {item.icon}
                      {item.label}
                    </Link>
                  ) : (
                    <div>
                      <div className="px-4 py-2 text-xs dark:text-white/30 text-gray-400 uppercase tracking-wider">{item.label}</div>
                      {item.children?.map(child => (
                        <Link
                          key={child.href}
                          href={child.href}
                          onClick={() => setMobileOpen(false)}
                          className={cn(
                            'flex items-center gap-3 px-6 py-2.5 rounded-xl text-sm transition-all',
                            pathname === child.href
                              ? 'bg-[#667eea]/20 dark:text-white text-gray-900'
                              : 'dark:text-white/50 text-gray-400 dark:hover:text-white hover:text-gray-900 dark:hover:bg-white/8 hover:bg-gray-50'
                          )}
                        >
                          <span className="dark:text-white/30 text-gray-300">{child.icon}</span>
                          {child.label}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              <div className="pt-4 border-t dark:border-white/10 border-gray-200">
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-3 px-4 py-3 rounded-xl text-sm text-red-400 hover:bg-red-500/10 w-full transition-all cursor-pointer"
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
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 border-t dark:border-white/10 border-gray-200 flex bg-white dark:bg-[#0f1219]/95 backdrop-blur-xl">
        {MOBILE_TABS.map(tab => (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              'flex-1 flex flex-col items-center gap-1 py-2 text-xs font-medium transition-colors',
              pathname === tab.href || (tab.href !== '/' && pathname.startsWith(tab.href))
                ? 'text-[#667eea]'
                : 'dark:text-white/40 text-gray-400 dark:hover:text-white/70 hover:text-gray-600'
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
