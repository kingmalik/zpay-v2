'use client'

import { useState, useRef, DragEvent, ChangeEvent } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Upload, FileText, CheckCircle2, AlertCircle, X, FileSpreadsheet } from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'

interface UploadState {
  loading: boolean
  success: string | null
  error: string | null
  file: File | null
}

function UploadZone({
  accept, label, icon, endpoint, fileTypeLabel,
}: {
  accept: string
  label: string
  icon: React.ReactNode
  endpoint: string
  fileTypeLabel: string
}) {
  const router = useRouter()
  const fileRef = useRef<HTMLInputElement>(null)
  const [state, setState] = useState<UploadState>({ loading: false, success: null, error: null, file: null })
  const [dragging, setDragging] = useState(false)

  function handleDrop(e: DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) setState(s => ({ ...s, file, error: null, success: null }))
  }

  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) setState(s => ({ ...s, file, error: null, success: null }))
  }

  async function upload() {
    if (!state.file) return
    const formData = new FormData()
    formData.append('file', state.file)
    setState(s => ({ ...s, loading: true, error: null, success: null }))
    try {
      const res = await api.postForm<{ ok?: boolean; batch_id?: number; company?: string; already_imported?: boolean }>(endpoint, formData)
      setState(s => ({ ...s, loading: false, success: `${state.file?.name} uploaded successfully!`, file: null }))
      // Navigate to the batch detail page after successful upload
      if (res.batch_id) {
        setTimeout(() => {
          router.push(`/payroll/workflow/${res.batch_id}`)
        }, 800)
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Upload failed'
      setState(s => ({ ...s, loading: false, error: msg }))
    }
  }

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
        className={`relative rounded-2xl border-2 border-dashed cursor-pointer transition-all p-8 flex flex-col items-center justify-center gap-3 ${
          dragging
            ? 'border-[#667eea] bg-[#667eea]/10'
            : state.file
            ? 'border-emerald-500/50 bg-emerald-500/5'
            : 'dark:border-white/15 border-gray-300 dark:hover:border-[#667eea]/50 hover:border-[#667eea]/50 dark:hover:bg-white/3 hover:bg-gray-50'
        }`}
      >
        <input ref={fileRef} type="file" accept={accept} onChange={handleChange} className="hidden" />
        <div className="w-12 h-12 rounded-2xl bg-[#667eea]/10 flex items-center justify-center text-[#667eea]">
          {icon}
        </div>
        {state.file ? (
          <div className="text-center">
            <p className="text-sm font-medium dark:text-white text-gray-800">{state.file.name}</p>
            <p className="text-xs dark:text-white/40 text-gray-400">{(state.file.size / 1024).toFixed(1)} KB</p>
          </div>
        ) : (
          <div className="text-center">
            <p className="text-sm font-medium dark:text-white/70 text-gray-600">Drop {fileTypeLabel} here</p>
            <p className="text-xs dark:text-white/30 text-gray-400 mt-1">or click to browse</p>
          </div>
        )}
      </div>

      {/* Status messages */}
      <AnimatePresence>
        {state.success && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
            className="flex items-center gap-2 px-4 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-sm">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            {state.success}
            <button onClick={() => setState(s => ({ ...s, success: null }))} className="ml-auto cursor-pointer"><X className="w-3.5 h-3.5" /></button>
          </motion.div>
        )}
        {state.error && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
            className="flex items-center gap-2 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {state.error}
            <button onClick={() => setState(s => ({ ...s, error: null }))} className="ml-auto cursor-pointer"><X className="w-3.5 h-3.5" /></button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Upload button */}
      {state.file && (
        <button
          onClick={upload}
          disabled={state.loading}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-white font-medium text-sm transition-all cursor-pointer disabled:opacity-60"
          style={{ background: 'linear-gradient(135deg, #667eea, #06b6d4)' }}
        >
          {state.loading ? (
            <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Uploading...</>
          ) : (
            <><Upload className="w-4 h-4" />Upload {label}</>
          )}
        </button>
      )}
    </div>
  )
}

export default function UploadPage() {
  const [tab, setTab] = useState<'ed' | 'fa'>('ed')

  return (
    <div className="max-w-3xl mx-auto space-y-6 py-6">
      <div>
        <h1 className="text-2xl font-bold dark:text-[#fafafa] text-gray-900">Upload Files</h1>
        <p className="text-sm dark:text-white/40 text-gray-500 mt-0.5">Import EverDriven or FirstAlt data to create a payroll batch</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 rounded-xl dark:bg-white/5 bg-gray-100 w-fit">
        <button
          onClick={() => setTab('ed')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer ${tab === 'ed' ? 'bg-[#06b6d4] text-white' : 'dark:text-white/50 text-gray-500'}`}
        >
          EverDriven PDF
        </button>
        <button
          onClick={() => setTab('fa')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer ${tab === 'fa' ? 'bg-[#667eea] text-white' : 'dark:text-white/50 text-gray-500'}`}
        >
          FirstAlt Excel
        </button>
      </div>

      <GlassCard>
        {tab === 'ed' ? (
          <>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-xl bg-cyan-500/10 flex items-center justify-center text-cyan-400">
                <FileText className="w-5 h-5" />
              </div>
              <div>
                <h2 className="font-semibold dark:text-white text-gray-800">EverDriven PDF</h2>
                <p className="text-xs dark:text-white/40 text-gray-400">Upload the EverDriven payout PDF</p>
              </div>
            </div>
            <UploadZone
              accept=".pdf"
              label="EverDriven PDF"
              icon={<FileText className="w-6 h-6" />}
              endpoint="/upload/maz"
              fileTypeLabel=".pdf file"
            />
          </>
        ) : (
          <>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-400">
                <FileSpreadsheet className="w-5 h-5" />
              </div>
              <div>
                <h2 className="font-semibold dark:text-white text-gray-800">FirstAlt Excel</h2>
                <p className="text-xs dark:text-white/40 text-gray-400">Upload the Acumen/FirstAlt Excel file</p>
              </div>
            </div>
            <UploadZone
              accept=".xlsx,.xls,.csv"
              label="FirstAlt Excel"
              icon={<FileSpreadsheet className="w-6 h-6" />}
              endpoint="/upload/acumen"
              fileTypeLabel=".xlsx or .csv file"
            />
          </>
        )}
      </GlassCard>
    </div>
  )
}
