import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: 'class',
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        zpay: {
          bg: '#0f1219',
          surface: 'rgba(255,255,255,0.05)',
          border: 'rgba(255,255,255,0.10)',
          accent: '#667eea',
          'accent-light': '#7c93f0',
          success: '#10B981',
          warning: '#F59E0B',
          danger: '#EF4444',
          info: '#3B82F6',
          fa: '#6366f1',
          ed: '#06b6d4',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['Fira Code', 'SF Mono', 'monospace'],
      },
      backgroundImage: {
        'gradient-zpay': 'linear-gradient(135deg, #667eea 0%, #06b6d4 50%, #10B981 100%)',
        'gradient-card': 'linear-gradient(135deg, rgba(102,126,234,0.15) 0%, rgba(6,182,212,0.05) 100%)',
      },
      backdropBlur: {
        xs: '2px',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'spin-slow': 'spin 3s linear infinite',
      },
      boxShadow: {
        'glass': '0 8px 32px rgba(0,0,0,0.4)',
        'glass-hover': '0 16px 48px rgba(102,126,234,0.2)',
        'card': '0 4px 24px rgba(0,0,0,0.3)',
      },
    },
  },
  plugins: [],
}

export default config
