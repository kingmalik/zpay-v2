'use client'

import { useEffect } from 'react'
import { reportZPayError } from './ErrorBoundary'

/**
 * Catches JS errors that happen outside React's render cycle:
 * - Uncaught exceptions (window.onerror)
 * - Unhandled promise rejections
 * Mount once in root layout.
 */
export default function GlobalErrorCapture() {
  useEffect(() => {
    const handleError = (event: ErrorEvent) => {
      reportZPayError({
        type: 'uncaught_exception',
        message: event.message || 'Unknown error',
        stack: event.error?.stack ?? '',
        url: window.location.href,
      })
    }

    const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason
      reportZPayError({
        type: 'unhandled_promise',
        message: reason?.message ?? String(reason) ?? 'Unhandled promise rejection',
        stack: reason?.stack ?? '',
        url: window.location.href,
      })
    }

    window.addEventListener('error', handleError)
    window.addEventListener('unhandledrejection', handleUnhandledRejection)

    return () => {
      window.removeEventListener('error', handleError)
      window.removeEventListener('unhandledrejection', handleUnhandledRejection)
    }
  }, [])

  return null
}
