'use client'

import { useEffect, useState } from 'react'
import { Mail, Send, Save, Clock, CheckCircle2, XCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { formatDate, formatTime } from '@/lib/utils'
import StatCard from '@/components/ui/StatCard'
import GlassCard from '@/components/ui/GlassCard'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

interface EmailScheduleData {
  config?: { enabled?: boolean; day?: string; time?: string }
  stats?: { total_sent?: number; failed?: number; last_sent?: string }
  pending_batches?: { id?: string | number; batch_ref?: string; period?: string; company?: string }[]
  history?: { driver?: string; batch_ref?: string; sent_at?: string; status?: string; error?: string }[]
}

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export default function EmailSchedulePage() {
  const [data, setData] = useState<EmailScheduleData | null>(null)
  const [loading, setLoading] = useState(true)
  const [config, setConfig] = useState({ enabled: false, day: 'Friday', time: '17:00' })
  const [saving, setSaving] = useState(false)
  const [sendingBatch, setSendingBatch] = useState<string | number | null>(null)

  useEffect(() => {
    api.get<EmailScheduleData>('/admin/email-schedule').then(d => {
      setData(d)
      if (d.config) setConfig({ enabled: d.config.enabled || false, day: d.config.day || 'Friday', time: d.config.time || '17:00' })
    }).catch(console.error).finally(() => setLoading(false))
  }, [])

  async function saveConfig() {
    setSaving(true)
    try { await api.post('/admin/email-schedule/update', config) }
    catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  async function sendNow(batchId: string | number) {
    setSendingBatch(batchId)
    try {
      await api.post(`/admin/email-schedule/send-now/${batchId}`)
      const d = await api.get<EmailScheduleData>('/admin/email-schedule')
      setData(d)
    } catch (e) { console.error(e) }
    finally { setSendingBatch(null) }
  }

  if (loading) return <LoadingSpinner fullPage />

  const stats = data?.stats || {}

  return (
    <div className="max-w-4xl mx-auto space-y-5 py-6">
      <h1 className="text-2xl font-bold dark:text-white text-gray-900">Email Schedule</h1>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Status" value={config.enabled ? 'Enabled' : 'Disabled'} color={config.enabled ? 'success' : 'default'} index={0} />
        <StatCard label="Schedule" value={`${config.day} ${config.time}`} icon={<Clock className="w-4 h-4" />} index={1} />
        <StatCard label="Total Sent" value={stats.total_sent || 0} color="info" index={2} />
        <StatCard label="Failed" value={stats.failed || 0} color={(stats.failed || 0) > 0 ? 'danger' : 'default'} index={3} />
      </div>

      {/* Settings */}
      <GlassCard>
        <h3 className="text-sm font-semibold dark:text-white/70 text-gray-700 mb-4">Schedule Settings</h3>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm dark:text-white/80 text-gray-700">Email Automation</p>
              <p className="text-xs dark:text-white/40 text-gray-400">Automatically send pay stubs on schedule</p>
            </div>
            <button
              onClick={() => setConfig(s => ({ ...s, enabled: !s.enabled }))}
              className={`relative w-12 h-6 rounded-full transition-colors cursor-pointer ${config.enabled ? 'bg-[#667eea]' : 'dark:bg-white/15 bg-gray-300'}`}
            >
              <span className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all ${config.enabled ? 'left-7' : 'left-1'}`} />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs dark:text-white/40 text-gray-500 mb-1.5">Day of Week</label>
              <select value={config.day} onChange={e => setConfig(s => ({ ...s, day: e.target.value }))}
                className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none">
                {DAYS.map(d => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs dark:text-white/40 text-gray-500 mb-1.5">Time</label>
              <input type="time" value={config.time} onChange={e => setConfig(s => ({ ...s, time: e.target.value }))}
                className="w-full px-3 py-2.5 rounded-xl text-sm dark:bg-white/5 bg-gray-50 border dark:border-white/10 border-gray-200 dark:text-white text-gray-700 focus:outline-none" />
            </div>
          </div>
          <button onClick={saveConfig} disabled={saving}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white cursor-pointer disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}>
            <Save className="w-4 h-4" />
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </GlassCard>

      {/* Send Now */}
      {(data?.pending_batches || []).length > 0 && (
        <GlassCard>
          <h3 className="text-sm font-semibold dark:text-white/70 text-gray-700 mb-3">Send Pay Stubs Now</h3>
          <div className="space-y-2">
            {(data?.pending_batches || []).map(batch => {
              const isFa = (batch.company || '').toLowerCase().includes('first')
              return (
                <div key={batch.id} className="flex items-center justify-between px-4 py-3 rounded-xl dark:bg-white/5 bg-gray-50 border dark:border-white/8 border-gray-200">
                  <div className="flex items-center gap-3">
                    <Badge variant={isFa ? 'fa' : 'ed'}>{batch.company}</Badge>
                    <div>
                      <p className="text-sm dark:text-white/80 text-gray-700">{batch.period}</p>
                      <p className="text-xs font-mono dark:text-white/30 text-gray-400">{batch.batch_ref}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => sendNow(batch.id!)}
                    disabled={sendingBatch === batch.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-[#667eea]/15 text-[#667eea] hover:bg-[#667eea]/25 transition-all cursor-pointer"
                  >
                    <Send className="w-3 h-3" />
                    {sendingBatch === batch.id ? 'Sending...' : 'Send Now'}
                  </button>
                </div>
              )
            })}
          </div>
        </GlassCard>
      )}

      {/* History */}
      <GlassCard padding={false}>
        <div className="p-4 border-b dark:border-white/8 border-gray-100">
          <h3 className="font-semibold dark:text-white/80 text-sm">Send History</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b dark:border-white/8 border-gray-100">
                {['Driver', 'Batch', 'Sent At', 'Status', 'Error'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium dark:text-white/40 text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data?.history || []).map((row, i) => (
                <tr key={i} className="border-b last:border-0 dark:border-white/5 border-gray-50">
                  <td className="px-4 py-3 dark:text-white/80 text-gray-700">{row.driver}</td>
                  <td className="px-4 py-3 font-mono text-xs dark:text-white/50 text-gray-500">{row.batch_ref}</td>
                  <td className="px-4 py-3 text-xs dark:text-white/50 text-gray-500">{formatDate(row.sent_at)} {formatTime(row.sent_at)}</td>
                  <td className="px-4 py-3">
                    {row.status === 'sent'
                      ? <span className="flex items-center gap-1 text-emerald-400 text-xs"><CheckCircle2 className="w-3.5 h-3.5" />Sent</span>
                      : <span className="flex items-center gap-1 text-red-400 text-xs"><XCircle className="w-3.5 h-3.5" />Failed</span>}
                  </td>
                  <td className="px-4 py-3 text-xs text-red-400">{row.error || '—'}</td>
                </tr>
              ))}
              {(data?.history || []).length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-sm dark:text-white/30 text-gray-400">No send history</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </div>
  )
}
