import { redirect } from 'next/navigation'

/**
 * Root route for authenticated users.
 * Permanently redirect to the daily ops dashboard.
 */
export default function RootPage() {
  redirect('/dashboard')
}
