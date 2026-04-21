'use client'

import { useEffect, useState } from 'react'
import { Save, Trash2, Plus, Mail, Info } from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface EmailTemplate {
  id?: string | number
  subject?: string
  body?: string
  week?: string
  driver?: string
  type?: string
}

interface TemplatesData {
  default?: EmailTemplate
  week_overrides?: EmailTemplate[]
  driver_overrides?: EmailTemplate[]
  drivers?: { id?: string | number; name?: string }[]
  weeks?: string[]
}

const TOKENS = [
  '{{driver_name}}', '{{period}}', '{{net_pay}}', '{{pay_this_period}}',
  '{{carried_over}}', '{{rides}}', '{{company}}', '{{batch_ref}}'
]

function TemplateEditor({
  template, label, onSave, onDelete, showDelete = false,
}: {
  template: EmailTemplate
  label: string
  onSave: (t: EmailTemplate) => Promise<void>
  onDelete?: () => Promise<void>
  showDelete?: boolean
}) {
  const [subject, setSubject] = useState(template.subject || '')
  const [body, setBody] = useState(template.body || '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  async function save() {
    setSaving(true)
    try {
      await onSave({ ...template, subject, body })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  function insertToken(token: string) {
    setBody(b => b + token)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium dark:text-white/50 text-gray-500 uppercase tracking-wide">{label}</p>
        {showDelete && onDelete && (
          <button onClick={onDelete} className="p-1.5 rounded-lg text-red-400/60 hover:text-red-400 hover:bg-red-500/10 transition-all cursor-pointer">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Subject line..."
        className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60" />
      <textarea value={body} onChange={e => setBody(e.target.value)} placeholder="Email body..." rows={6}
        className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none focus:border-[#667eea]/60 resize-none font-mono" />
      <button onClick={save} disabled={saving}
        className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium cursor-pointer transition-all ${saved ? 'bg-emerald-500/15 text-emerald-400' : 'text-white'} disabled:opacity-60`}
        style={saved ? {} : { background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}>
        <Save className="w-4 h-4" />
        {saving ? 'Saving...' : saved ? 'Saved!' : 'Save Template'}
      </button>
    </div>
  )
}

export default function EmailTemplatesPage() {
  const [data, setData] = useState<TemplatesData | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedWeek, setSelectedWeek] = useState('')
  const [selectedDriver, setSelectedDriver] = useState('')

  useEffect(() => {
    api.get<TemplatesData>('/email/templates').then(setData).catch(console.error).finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner fullPage />

  return (
    <div className="max-w-4xl mx-auto space-y-6 py-6">
      <h1 className="text-2xl font-bold dark:text-white text-gray-900">Email Templates</h1>


      {/* Default template */}
      <GlassCard>
        <div className="flex items-center gap-2 mb-5">
          <Mail className="w-4 h-4 text-[#667eea]" />
          <h2 className="font-semibold dark:text-white text-gray-800">Default Template</h2>
        </div>
        <TemplateEditor
          template={data?.default || {}}
          label="Sent to all drivers unless overridden"
          onSave={async t => { await api.post('/email/templates/save-default', t); setData(d => ({ ...d, default: t })) }}
        />
      </GlassCard>

      {/* Week override */}
      <GlassCard>
        <div className="flex items-center gap-2 mb-5">
          <h2 className="font-semibold dark:text-white text-gray-800">Week Override</h2>
        </div>
        <div className="mb-4">
          <label className="block text-xs dark:text-white/40 text-gray-500 mb-1.5">Select Week</label>
          <select value={selectedWeek} onChange={e => setSelectedWeek(e.target.value)}
            className="px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none w-48">
            <option value="">— Select week —</option>
            {(data?.weeks || []).map(w => <option key={w} value={w}>{w}</option>)}
          </select>
        </div>
        {selectedWeek && (
          <>
            <div className="mb-4 px-3 py-2 rounded-xl dark:bg-amber-500/10 bg-amber-50 border dark:border-amber-500/20 border-amber-200">
              <p className="text-xs text-amber-400">This override replaces the default template for week {selectedWeek} only</p>
            </div>
            <TemplateEditor
              template={(data?.week_overrides || []).find(w => w.week === selectedWeek) || { week: selectedWeek }}
              label={`Week ${selectedWeek} override`}
              onSave={async t => {
                await api.post('/email/templates/save-batch', t)
                setData(d => ({ ...d, week_overrides: [...(d?.week_overrides || []).filter(w => w.week !== selectedWeek), t] }))
              }}
            />
          </>
        )}
        {(data?.week_overrides || []).length > 0 && (
          <div className="mt-4 space-y-1">
            <p className="text-xs dark:text-white/30 text-gray-400">Saved overrides: {(data?.week_overrides || []).map(w => w.week).join(', ')}</p>
          </div>
        )}
      </GlassCard>

      {/* Driver override */}
      <GlassCard>
        <div className="flex items-center gap-2 mb-5">
          <h2 className="font-semibold dark:text-white text-gray-800">Driver Override</h2>
        </div>
        <div className="mb-4">
          <label className="block text-xs dark:text-white/40 text-gray-500 mb-1.5">Select Driver</label>
          <select value={selectedDriver} onChange={e => setSelectedDriver(e.target.value)}
            className="px-3 py-2 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none w-48">
            <option value="">— Select driver —</option>
            {(data?.drivers || []).map(d => <option key={String(d.id)} value={String(d.id)}>{d.name}</option>)}
          </select>
        </div>
        {selectedDriver && (
          <TemplateEditor
            template={(data?.driver_overrides || []).find(d => d.driver === selectedDriver) || { driver: selectedDriver }}
            label="Driver-specific template"
            onSave={async t => {
              await api.post('/email/templates/save-person', t)
              setData(d => ({ ...d, driver_overrides: [...(d?.driver_overrides || []).filter(x => x.driver !== selectedDriver), t] }))
            }}
          />
        )}
      </GlassCard>
    </div>
  )
}
