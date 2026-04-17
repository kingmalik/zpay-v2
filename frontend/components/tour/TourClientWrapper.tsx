'use client'

import { TourProvider } from './TourContext'
import TourOverlay from './TourOverlay'

export default function TourClientWrapper({ children }: { children: React.ReactNode }) {
  return (
    <TourProvider>
      {children}
      <TourOverlay />
    </TourProvider>
  )
}
