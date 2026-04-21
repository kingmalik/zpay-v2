'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Copy, Check, Trash2 } from 'lucide-react'
import type { SessionChange, Company } from './useDispatchSession'

interface SessionSummaryProps {
  date: string
  changes: SessionChange[]
  onRemove: (id: string) => void
  onClear: () => void
  onClose: () => void
}

const COMPANY_LABEL: Record<Company, string> = {
  firstalt: 'FirstAlt (Acumen)',
  everdriven: 'EverDriven',
  both: 'Both Companies',
  unknown: 'Unknown Company',
}

const TYPE_LABEL: Record<string, string> = {
  cover: 'Cover',
  emergency: '🚨 EMERGENCY Cover',
  swap: 'Swap',
  reshuffle: 'Reshuffle',
  assign: 'New Ride',
  leave: 'Leave Coverage',
}

function formatDateLabel(date: string) {
  try {
    return new Date(date + 'T12:00:00').toLocaleDateString('en-US', {
      weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
    })
  } catch {
    return date
  }
}

function changesToText(changes: SessionChange[], company?: Company): string {
  const filtered = company ? changes.filter(c => c.company === company || c.company === 'both' || c.company === 'unknown') : changes
  return filtered
    .map((c, i) => `${i + 1}. ${TYPE_LABEL[c.type] || c.type}: ${c.description}\n   ${c.detail}`)
    .join('\n\n')
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button onClick={copy}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
        dark:bg-white/8 bg-gray-100 dark:hover:bg-white/12 hover:bg-gray-200
        dark:text-white/60 text-gray-600 transition-all cursor-pointer">
      {copied ? <><Check className="w-3 h-3 text-emerald-400" /> Copied</> : <><Copy className="w-3 h-3" /> Copy</>}
    </button>
  )
}

export default function SessionSummary({ date, changes, onRemove, onClear, onClose }: SessionSummaryProps) {
  const companies: Company[] = ['everdriven', 'firstalt', 'both', 'unknown']
  const byCompany = companies.reduce<Partial<Record<Company, SessionChange[]>>>((acc, co) => {
    const list = changes.filter(c => c.company === co)
    if (list.length > 0) acc[co] = list
    return acc
  }, {})

  const allText = `DISPATCH CHANGES — ${formatDateLabel(date)}\n\n` +
    Object.entries(byCompany)
      .map(([co, list]) => `── ${COMPANY_LABEL[co as Company].toUpperCase()} ──\n${changesToText(list as SessionChange[])}`)
      .join('\n\n')

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        {/* Backdrop */}
        <motion.div
          key="backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        />

        {/* Modal */}
        <motion.div
          key="modal"
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 10 }}
          transition={{ type: 'spring', damping: 22, stiffness: 300 }}
          className="relative w-full max-w-lg max-h-[85vh] flex flex-col rounded-2xl
            dark:bg-[#12121e] bg-white
            border dark:border-white/10 border-gray-200
            shadow-2xl overflow-hidden z-10"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b dark:border-white/8 border-gray-100">
            <div>
              <p className="text-sm font-bold dark:text-white text-gray-900">Dispatch Changes</p>
              <p className="text-xs dark:text-white/40 text-gray-400 mt-0.5">{formatDateLabel(date)} · {changes.length} change{changes.length !== 1 ? 's' : ''}</p>
            </div>
            <div className="flex items-center gap-2">
              <CopyButton text={allText} />
              <button onClick={onClose}
                className="p-1.5 rounded-lg dark:hover:bg-white/8 hover:bg-gray-100 transition-all cursor-pointer">
                <X className="w-4 h-4 dark:text-white/50 text-gray-500" />
              </button>
            </div>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-6">
            {Object.entries(byCompany).map(([co, list]) => (
              <div key={co}>
                <div className="flex items-center justify-between mb-3">
                  <p className="text-xs font-bold uppercase tracking-widest dark:text-white/40 text-gray-400">
                    {COMPANY_LABEL[co as Company]}
                  </p>
                  <CopyButton text={`── ${COMPANY_LABEL[co as Company].toUpperCase()} ──\n${changesToText(list as SessionChange[])}`} />
                </div>
                <div className="space-y-2">
                  {(list as SessionChange[]).map((c, i) => (
                    <div key={c.id}
                      className="group flex items-start gap-3 px-3 py-3 rounded-xl
                        dark:bg-white/4 bg-gray-50 border dark:border-white/6 border-gray-100">
                      <span className="flex-shrink-0 w-5 h-5 rounded-full dark:bg-white/8 bg-gray-200
                        flex items-center justify-center text-xs font-bold dark:text-white/50 text-gray-500 mt-0.5">
                        {i + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-semibold dark:text-white/80 text-gray-700 leading-snug">
                          <span className="dark:text-white/40 text-gray-400 mr-1">{TYPE_LABEL[c.type]}:</span>
                          {c.description}
                        </p>
                        <p className="text-xs dark:text-white/40 text-gray-400 mt-0.5 leading-snug">{c.detail}</p>
                      </div>
                      <button onClick={() => onRemove(c.id)}
                        className="opacity-0 group-hover:opacity-100 p-1 rounded-lg
                          dark:hover:bg-white/8 hover:bg-gray-200 transition-all cursor-pointer flex-shrink-0">
                        <Trash2 className="w-3.5 h-3.5 dark:text-white/30 text-gray-400" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {changes.length === 0 && (
              <p className="text-sm dark:text-white/30 text-gray-400 text-center py-8">No changes in this session.</p>
            )}
          </div>

          {/* Footer */}
          {changes.length > 0 && (
            <div className="px-5 py-4 border-t dark:border-white/8 border-gray-100">
              <button onClick={onClear}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold
                  dark:bg-white/6 bg-gray-100 dark:hover:bg-white/10 hover:bg-gray-200
                  dark:text-white/60 text-gray-600 transition-all cursor-pointer">
                <Trash2 className="w-4 h-4" />
                Done — Clear Session
              </button>
              <p className="text-xs dark:text-white/25 text-gray-400 text-center mt-2">
                Session saved to log automatically
              </p>
            </div>
          )}
        </motion.div>
      </div>
    </AnimatePresence>
  )
}
