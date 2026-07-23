'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { ClipboardPaste, Copy, Check, AlertTriangle, Accessibility, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { formatCurrency, formatPercent } from '@/lib/utils'
import SuggestionList from './SuggestionList'
import DecisionPanel from './DecisionPanel'
import IntakeHistory from './IntakeHistory'
import { IntakeResponse, ParsedRide, Pricing, DriverSuggestion, SuggestResponse, daysToText } from './types'

const RESUGGEST_DEBOUNCE_MS = 600

function PricingBanner({ pricing }: { pricing: Pricing }) {
  const base = (
    <p className="text-sm dark:text-white/70 text-gray-700">
      Predicted driver rate <span className="font-semibold">{formatCurrency(pricing.predicted_rate)}</span>
      <span className="mx-1.5 dark:text-white/20 text-gray-300">·</span>
      Margin <span className={`font-semibold ${pricing.margin >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
        {formatCurrency(pricing.margin)}
      </span>
      <span className="dark:text-white/40 text-gray-400"> ({formatPercent(pricing.margin_pct)})</span>
    </p>
  )

  return (
    <div className="space-y-2">
      <div className="rounded-2xl px-4 py-3 dark:bg-white/[0.03] bg-gray-50 border dark:border-white/8 border-gray-200">
        {base}
      </div>

      {pricing.unprofitable && (
        <div className="flex items-start gap-2 rounded-2xl px-4 py-3 bg-red-500/10 border border-red-500/25">
          <AlertTriangle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
          <p className="text-sm text-red-500 font-medium">Thin margin — this ride loses money at the usual rate</p>
        </div>
      )}

      {pricing.manual_review && (
        <div className="flex items-start gap-2 rounded-2xl px-4 py-3 bg-amber-500/10 border border-amber-500/25">
          <Accessibility className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
          <p className="text-sm text-amber-500 font-medium">
            Wheelchair route — manual pricing, suggested full pass-through of{' '}
            {pricing.pass_through_suggestion != null ? formatCurrency(pricing.pass_through_suggestion) : '—'}
          </p>
        </div>
      )}
    </div>
  )
}

function ParsedCard({ parsed, onChange }: { parsed: ParsedRide; onChange: (next: ParsedRide) => void }) {
  const set = <K extends keyof ParsedRide>(key: K, value: ParsedRide[K]) => onChange({ ...parsed, [key]: value })

  const inputCls = 'w-full px-2.5 py-1.5 rounded-lg text-sm dark:bg-white/5 bg-white border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 focus:outline-none focus:border-[#667eea]/60'
  const labelCls = 'block text-[11px] font-medium dark:text-white/40 text-gray-400 mb-1'

  return (
    <div className="rounded-2xl border dark:border-white/8 border-gray-200 dark:bg-white/[0.02] bg-white p-4 space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <div className="col-span-2">
          <label className={labelCls}>School</label>
          <input className={inputCls} value={parsed.school} onChange={e => set('school', e.target.value)} />
        </div>
        <div>
          <label className={labelCls}>Direction</label>
          <select className={inputCls} value={parsed.direction} onChange={e => set('direction', e.target.value)}>
            <option value="IB">IB</option>
            <option value="OB">OB</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>Number</label>
          <input className={inputCls} value={parsed.number} onChange={e => set('number', e.target.value)} />
        </div>
        <div>
          <label className={labelCls}>Miles</label>
          <input
            type="number" step="0.1" className={inputCls} value={parsed.miles}
            onChange={e => set('miles', parseFloat(e.target.value) || 0)}
          />
        </div>
        <div>
          <label className={labelCls}>Pay</label>
          <input
            type="number" step="0.01" className={inputCls} value={parsed.net_pay}
            onChange={e => set('net_pay', parseFloat(e.target.value) || 0)}
          />
        </div>
        <div>
          <label className={labelCls}>Days</label>
          <input className={inputCls} value={daysToText(parsed.days)} onChange={e => set('days', e.target.value)} />
        </div>
        <div>
          <label className={labelCls}>Start time</label>
          <input className={inputCls} value={parsed.start_time} onChange={e => set('start_time', e.target.value)} />
        </div>
      </div>

      <div className="flex items-center justify-between">
        <button
          onClick={() => set('wheelchair', !parsed.wheelchair)}
          className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border cursor-pointer transition-all ${
            parsed.wheelchair
              ? 'bg-amber-500/15 text-amber-500 border-amber-500/30'
              : 'dark:bg-white/5 bg-gray-100 dark:text-white/40 text-gray-400 dark:border-white/10 border-gray-200'
          }`}
        >
          <Accessibility className="w-3.5 h-3.5" />
          {parsed.wheelchair ? 'Wheelchair route' : 'Not wheelchair'}
        </button>
        {parsed.is_odt && (
          <span className="text-[11px] font-semibold dark:text-white/40 text-gray-400 uppercase tracking-wide">ODT</span>
        )}
      </div>

      {parsed.notes && (
        <p className="text-xs dark:text-white/40 text-gray-400 italic border-t dark:border-white/5 border-gray-100 pt-2">
          {parsed.notes}
        </p>
      )}
    </div>
  )
}

function ReplyDraftBox({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      // clipboard permission denied — she can still select+copy manually
    }
  }

  return (
    <div className="rounded-2xl border dark:border-white/8 border-gray-200 dark:bg-white/[0.02] bg-white p-4 space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-bold uppercase tracking-widest dark:text-white/35 text-gray-400">Reply to Brandon</h3>
        <button
          onClick={copy}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold dark:bg-white/5 bg-gray-100 dark:text-white/60 text-gray-500 dark:hover:bg-white/10 hover:bg-gray-200 cursor-pointer"
        >
          {copied ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="text-xs whitespace-pre-wrap dark:text-white/70 text-gray-700 font-sans leading-relaxed">{text}</pre>
    </div>
  )
}

export default function IntakePanel() {
  const [rawText, setRawText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [intake, setIntake] = useState<IntakeResponse | null>(null)
  const [parsed, setParsed] = useState<ParsedRide | null>(null)
  const [suggestions, setSuggestions] = useState<DriverSuggestion[]>([])
  const [pricing, setPricing] = useState<Pricing | null>(null)
  const [resuggesting, setResuggesting] = useState(false)
  const [historyKey, setHistoryKey] = useState(0)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const skipNextResuggest = useRef(false)

  async function submitIntake() {
    if (!rawText.trim()) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const res = await api.post<IntakeResponse>('/api/data/assignment/intake', { raw_text: rawText })
      skipNextResuggest.current = true
      setIntake(res)
      setParsed(res.parsed)
      setSuggestions(res.suggestions)
      setPricing(res.pricing)
      setHistoryKey(k => k + 1)
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : 'Could not parse that email — check it pasted fully')
    } finally {
      setSubmitting(false)
    }
  }

  const resuggest = useCallback(async (p: ParsedRide) => {
    setResuggesting(true)
    try {
      const qs = new URLSearchParams({
        school: p.school,
        direction: p.direction,
        miles: String(p.miles),
        net_pay: String(p.net_pay),
        wheelchair: String(p.wheelchair),
      })
      const res = await api.get<SuggestResponse>(`/api/data/assignment/suggest?${qs.toString()}`)
      setSuggestions(res.suggestions)
      setPricing(res.pricing)
    } catch {
      // leave prior suggestions/pricing visible — a stale-but-present read beats a blank panel
    } finally {
      setResuggesting(false)
    }
  }, [])

  useEffect(() => {
    if (!parsed) return
    if (skipNextResuggest.current) {
      skipNextResuggest.current = false
      return
    }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => resuggest(parsed), RESUGGEST_DEBOUNCE_MS)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed?.school, parsed?.direction, parsed?.miles, parsed?.net_pay, parsed?.wheelchair])

  function handleDecided() {
    setHistoryKey(k => k + 1)
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border dark:border-white/8 border-gray-200 dark:bg-white/[0.02] bg-white p-4 space-y-3">
        <div className="flex items-center gap-2">
          <ClipboardPaste className="w-4 h-4 dark:text-white/35 text-gray-400" />
          <h2 className="text-sm font-semibold dark:text-white text-gray-900">Paste Brandon&apos;s email</h2>
        </div>
        <textarea
          value={rawText}
          onChange={e => setRawText(e.target.value)}
          rows={7}
          placeholder="Paste the full ride email here…"
          className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-800 placeholder-gray-400 dark:placeholder-white/30 focus:outline-none focus:border-[#667eea]/60 resize-y"
        />
        <div className="flex items-center gap-3">
          <button
            onClick={submitIntake}
            disabled={submitting || !rawText.trim()}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-white disabled:opacity-50 cursor-pointer"
            style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
          >
            {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Get suggestions
          </button>
          {submitError && <p className="text-xs text-red-500">{submitError}</p>}
        </div>
      </div>

      {intake && parsed && pricing && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-5">
          <ParsedCard parsed={parsed} onChange={setParsed} />

          <PricingBanner pricing={pricing} />

          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-bold uppercase tracking-widest dark:text-white/35 text-gray-400">
                Who should take this
              </h3>
              {resuggesting && <Loader2 className="w-3 h-3 animate-spin dark:text-white/30 text-gray-300" />}
            </div>
            <SuggestionList drivers={suggestions} emptyLabel="No drivers match this route yet" />
          </section>

          <ReplyDraftBox text={intake.reply_draft} />

          <div className="rounded-2xl border dark:border-white/8 border-gray-200 dark:bg-white/[0.02] bg-white p-4">
            <DecisionPanel intakeId={intake.intake_id} onDecided={handleDecided} />
          </div>
        </motion.div>
      )}

      <div className="pt-2 border-t dark:border-white/5 border-gray-100">
        <IntakeHistory refreshKey={historyKey} />
      </div>
    </div>
  )
}
