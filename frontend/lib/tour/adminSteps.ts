import type { TourStep } from './types'

export const ADMIN_TOUR_KEY = 'zpay_admin_tour_v1'

export const ADMIN_STEPS: TourStep[] = [
  {
    id: 'dashboard-stats',
    route: '/',
    target: 'dashboard-stats',
    title: 'Your daily overview',
    body: 'Revenue, rides, profit, and margin — updated in real time.',
  },
  {
    id: 'upload-zone',
    route: '/upload',
    target: 'upload-zone',
    title: 'Import ride files',
    body: 'Start every payroll cycle here. Upload Acumen (Excel) or EverDriven (PDF) files.',
  },
  {
    id: 'payroll-list',
    route: '/payroll/history',
    target: 'payroll-list',
    title: 'Run & track payroll',
    body: 'Review batches, approve, and send driver pay stubs.',
  },
  {
    id: 'people-table',
    route: '/people',
    target: 'people-table',
    title: 'Driver directory',
    body: 'Every driver, their status, rates, and earnings history.',
  },
  {
    id: 'tasks-board',
    route: '/tasks',
    target: 'tasks-board',
    title: 'Team ops queue',
    body: 'Assign tasks, set priority, track what needs to get done.',
  },
  {
    id: 'alerts-list',
    route: '/alerts',
    target: 'alerts-list',
    title: 'Flagged issues',
    body: 'Unmatched rates, withheld balances, inactive drivers — all in one place.',
  },
]
