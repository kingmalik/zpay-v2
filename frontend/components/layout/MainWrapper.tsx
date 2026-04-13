'use client'

import { usePathname } from 'next/navigation'

export default function MainWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const isPublic = pathname === '/login' || pathname.startsWith('/join') || pathname.startsWith('/training') || pathname.startsWith('/contract')

  return (
    <main className={isPublic ? 'min-h-screen' : 'min-h-screen pt-14 pb-20 md:pb-6 px-4 md:px-6'}>
      {children}
    </main>
  )
}
