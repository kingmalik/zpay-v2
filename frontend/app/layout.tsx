import type { Metadata, Viewport } from 'next'
import { ThemeProvider } from 'next-themes'
import Navbar from '@/components/layout/Navbar'
import MainWrapper from '@/components/layout/MainWrapper'
import './globals.css'

export const metadata: Metadata = {
  title: 'Z-Pay — Payroll & Dispatch',
  description: 'Payroll and dispatch management for Maz Services Transportation',
  manifest: '/manifest.json',
}

export const viewport: Viewport = {
  themeColor: '#667eea',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className="h-full">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet" />
      </head>
      <body className="h-full antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem={false}
          disableTransitionOnChange={false}
        >
          <Navbar />
          <MainWrapper>
            {children}
          </MainWrapper>
        </ThemeProvider>
      </body>
    </html>
  )
}
