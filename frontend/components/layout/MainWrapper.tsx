'use client'

import { usePathname } from 'next/navigation'

export default function MainWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const isLogin = pathname === '/login'

  return (
    <main className={isLogin ? 'min-h-screen' : 'min-h-screen pt-14 pb-20 md:pb-6 px-4 md:px-6'}>
      {children}
    </main>
  )
}
