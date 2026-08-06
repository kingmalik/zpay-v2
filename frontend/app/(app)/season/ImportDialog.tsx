'use client'

import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { FileSpreadsheet, Inbox, Loader2, Upload } from 'lucide-react'
import SeasonDialog from './SeasonDialog'
import { importFromInbox, importSheet } from './seasonApi'
import { apiErrorMessage } from './utils'
import type { ImportReport } from './types'

interface ImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onImported: () => void
}

function ReportSummary({ report }: { report: ImportReport }) {
  return (
    <div className="mt-4 space-y-2">
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-xl px-2 py-2.5 bg-emerald-500/10 border border-emerald-500/20">
          <p className="text-lg font-bold text-emerald-500 tabular-nums">{report.created}</p>
          <p className="text-[11px] text-emerald-500/70">Created</p>
        </div>
        <div className="rounded-xl px-2 py-2.5 bg-blue-500/10 border border-blue-500/20">
          <p className="text-lg font-bold text-blue-500 tabular-nums">{report.updated}</p>
          <p className="text-[11px] text-blue-500/70">Updated</p>
        </div>
        <div className="rounded-xl px-2 py-2.5 dark:bg-white/5 bg-gray-100 border dark:border-white/10 border-gray-200">
          <p className="text-lg font-bold dark:text-white/60 text-gray-500 tabular-nums">{report.schools_created}</p>
          <p className="text-[11px] dark:text-white/40 text-gray-400">New schools</p>
        </div>
      </div>
      {report.errors?.length > 0 && (
        <div className="rounded-xl px-3 py-2 bg-red-500/10 border border-red-500/20 max-h-32 overflow-y-auto">
          <p className="text-[11px] font-medium text-red-400 mb-1">{report.errors.length} error(s)</p>
          <ul className="space-y-0.5">
            {report.errors.map((err, i) => (
              <li key={i} className="text-[11px] text-red-400/80">
                {err.row != null ? `Row ${err.row}: ` : err.intake_id != null ? `Intake ${err.intake_id}: ` : ''}
                {err.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function ImportDialog({ open, onOpenChange, onImported }: ImportDialogProps) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [pulling, setPulling] = useState(false)
  const [report, setReport] = useState<ImportReport | null>(null)

  function toastSummary(r: ImportReport) {
    const errPart = r.errors?.length ? `, ${r.errors.length} error(s)` : ''
    toast.success(`Import done — ${r.created} created, ${r.updated} updated${errPart}`)
  }

  async function handleUpload() {
    if (!file) return
    setUploading(true)
    try {
      const r = await importSheet(file)
      setReport(r)
      toastSummary(r)
      setFile(null)
      onImported()
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Import failed'))
    } finally {
      setUploading(false)
    }
  }

  async function handlePullInbox() {
    setPulling(true)
    try {
      const r = await importFromInbox()
      setReport(r)
      toastSummary(r)
      onImported()
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Failed to pull from inbox'))
    } finally {
      setPulling(false)
    }
  }

  return (
    <SeasonDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Import season rides"
      description="Upload a sheet or pull accepted offers already sitting in the intake inbox"
      icon={<Upload className="w-5 h-5 text-[#667eea]" />}
    >
      <div className="space-y-3">
        <div
          onClick={() => fileRef.current?.click()}
          className="rounded-xl border-2 border-dashed dark:border-white/10 border-gray-200 p-5 flex flex-col items-center gap-2 cursor-pointer dark:hover:border-[#667eea]/40 hover:border-[#667eea]/40 transition-colors"
        >
          <FileSpreadsheet className="w-6 h-6 dark:text-white/30 text-gray-400" />
          <p className="text-xs dark:text-white/50 text-gray-500 text-center">
            {file ? file.name : 'Click to choose a .xlsx or .csv sheet'}
          </p>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            className="hidden"
            onChange={e => setFile(e.target.files?.[0] || null)}
          />
        </div>

        <button
          onClick={handleUpload}
          disabled={!file || uploading}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white bg-[#667eea] hover:bg-[#5a72d8] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {uploading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          Import sheet
        </button>

        <div className="flex items-center gap-2 py-1">
          <div className="flex-1 h-px dark:bg-white/8 bg-gray-200" />
          <span className="text-[11px] dark:text-white/30 text-gray-400">or</span>
          <div className="flex-1 h-px dark:bg-white/8 bg-gray-200" />
        </div>

        <button
          onClick={handlePullInbox}
          disabled={pulling}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-sm font-medium dark:text-white text-gray-700 dark:bg-white/5 bg-gray-100 dark:hover:bg-white/10 hover:bg-gray-200 disabled:opacity-40 transition-colors"
        >
          {pulling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Inbox className="w-3.5 h-3.5" />}
          Pull accepted offers from inbox
        </button>

        {report && <ReportSummary report={report} />}
      </div>
    </SeasonDialog>
  )
}
