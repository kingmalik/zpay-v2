'use client'

import { useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Sparkles, Send, Loader2, CheckCircle2, X, AlertTriangle } from 'lucide-react'

interface ProposedAction {
  ride_id: number
  service_name: string
  ride_date: string
  current_driver: string | null
  target_person_id: number
  target_driver: string
  summary: string
  notes: string
}

interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  action?: ProposedAction | null
  confirmed?: boolean
}

const SUGGESTIONS = [
  'Move Rahim\'s Rose Hill ride tomorrow to Kedria',
  'Who can cover Mark Twain AM?',
  'Find unassigned Helen Keller rides this week',
]

export default function DispatchAgent() {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [history, setHistory] = useState<unknown[]>([])
  const [loading, setLoading] = useState(false)
  const [confirmingId, setConfirmingId] = useState<number | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  async function send(text: string) {
    const msg = text.trim()
    if (!msg || loading) return

    setMessages(prev => [...prev, { role: 'user', text: msg }])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch('/api/data/dispatch/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ message: msg, history }),
      })
      const data = await res.json()

      if (data.error) {
        setMessages(prev => [...prev, { role: 'assistant', text: `Error: ${data.error}` }])
      } else {
        setMessages(prev => [...prev, {
          role: 'assistant',
          text: data.reply || '',
          action: data.proposed_action || null,
        }])
        setHistory(data.history || [])
      }
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', text: `Network error: ${String(err)}` }])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 10)
    }
  }

  async function confirmAction(msgIdx: number, action: ProposedAction) {
    setConfirmingId(action.ride_id)
    try {
      const res = await fetch(`/api/data/rides/${action.ride_id}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ person_id: action.target_person_id }),
      })
      const data = await res.json()
      if (data.ok) {
        setMessages(prev => prev.map((m, i) => i === msgIdx ? { ...m, confirmed: true } : m))
      } else {
        setMessages(prev => [...prev, { role: 'assistant', text: `Assignment failed: ${data.error || 'unknown'}` }])
      }
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', text: `Network error: ${String(err)}` }])
    } finally {
      setConfirmingId(null)
    }
  }

  function cancelAction(msgIdx: number) {
    setMessages(prev => prev.map((m, i) => i === msgIdx ? { ...m, action: null, text: `${m.text} (cancelled)` } : m))
  }

  return (
    <div className="rounded-2xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.03] bg-white overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/5 transition-all cursor-pointer"
      >
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#667eea] to-[#764ba2] flex items-center justify-center">
          <Sparkles className="w-4 h-4 text-white" />
        </div>
        <div className="flex-1 text-left">
          <p className="font-semibold text-sm dark:text-white text-gray-900">Dispatch Agent</p>
          <p className="text-xs dark:text-white/40 text-gray-500">
            {messages.length > 0 ? `${messages.length} messages` : 'Ask in plain English'}
          </p>
        </div>
        <span className="text-xs dark:text-white/40 text-gray-400">{open ? 'Close' : 'Open'}</span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="border-t dark:border-white/10 border-gray-200"
          >
            <div className="p-4 space-y-3">
              {messages.length === 0 && (
                <div className="space-y-2">
                  <p className="text-xs dark:text-white/50 text-gray-500 font-medium">Try:</p>
                  {SUGGESTIONS.map(s => (
                    <button
                      key={s}
                      onClick={() => send(s)}
                      className="w-full text-left text-sm px-3 py-2 rounded-lg dark:bg-white/5 bg-gray-50 dark:hover:bg-white/10 hover:bg-gray-100 dark:text-white/70 text-gray-600 transition-all cursor-pointer"
                    >
                      "{s}"
                    </button>
                  ))}
                </div>
              )}

              <div className="space-y-2 max-h-[400px] overflow-y-auto">
                {messages.map((m, i) => (
                  <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[85%] px-3 py-2 rounded-xl text-sm ${
                      m.role === 'user'
                        ? 'bg-[#667eea] text-white'
                        : 'dark:bg-white/5 bg-gray-100 dark:text-white/90 text-gray-800'
                    }`}>
                      <p className="whitespace-pre-wrap">{m.text}</p>

                      {m.action && !m.confirmed && (
                        <div className="mt-3 p-3 rounded-lg dark:bg-black/30 bg-white border dark:border-white/10 border-gray-200 space-y-2">
                          <div className="text-xs dark:text-white/50 text-gray-500 uppercase tracking-wide">Proposed reassignment</div>
                          <div className="text-sm font-semibold dark:text-white text-gray-900">{m.action.service_name}</div>
                          <div className="text-xs dark:text-white/60 text-gray-600">{m.action.ride_date}</div>
                          <div className="flex items-center gap-2 text-sm">
                            <span className="dark:text-white/50 text-gray-500">{m.action.current_driver || 'Unassigned'}</span>
                            <span className="dark:text-white/30 text-gray-400">→</span>
                            <span className="font-semibold dark:text-white text-gray-900">{m.action.target_driver}</span>
                          </div>
                          {m.action.notes && (
                            <div className="flex items-start gap-1.5 text-xs text-amber-500">
                              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                              <span>{m.action.notes}</span>
                            </div>
                          )}
                          <div className="flex gap-2 pt-1">
                            <button
                              onClick={() => confirmAction(i, m.action!)}
                              disabled={confirmingId === m.action.ride_id}
                              className="flex-1 px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white text-xs font-semibold cursor-pointer transition-all flex items-center justify-center gap-1.5"
                            >
                              {confirmingId === m.action.ride_id
                                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                : <CheckCircle2 className="w-3.5 h-3.5" />}
                              Confirm
                            </button>
                            <button
                              onClick={() => cancelAction(i)}
                              className="px-3 py-1.5 rounded-lg dark:bg-white/10 bg-gray-200 dark:hover:bg-white/15 hover:bg-gray-300 dark:text-white/80 text-gray-700 text-xs font-semibold cursor-pointer transition-all flex items-center gap-1.5"
                            >
                              <X className="w-3.5 h-3.5" />
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}

                      {m.confirmed && (
                        <div className="mt-2 flex items-center gap-1.5 text-xs text-emerald-500">
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          Applied
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {loading && (
                  <div className="flex justify-start">
                    <div className="px-3 py-2 rounded-xl dark:bg-white/5 bg-gray-100">
                      <Loader2 className="w-4 h-4 animate-spin dark:text-white/60 text-gray-500" />
                    </div>
                  </div>
                )}
              </div>

              <div className="flex gap-2 pt-2">
                <input
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') send(input) }}
                  placeholder="Move Rahim's 8am Tuesday ride to Dawit…"
                  disabled={loading}
                  className="flex-1 px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 placeholder:dark:text-white/30 placeholder:text-gray-400 focus:outline-none focus:border-[#667eea]/60"
                />
                <button
                  onClick={() => send(input)}
                  disabled={loading || !input.trim()}
                  className="px-4 py-2 rounded-xl bg-[#667eea] hover:bg-[#5568d3] disabled:opacity-50 text-white text-sm font-semibold cursor-pointer transition-all flex items-center gap-1.5"
                >
                  <Send className="w-3.5 h-3.5" />
                  Send
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
