'use client'

import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'

interface SeasonDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  icon?: React.ReactNode
  children: React.ReactNode
  maxWidth?: string
}

export default function SeasonDialog({
  open, onOpenChange, title, description, icon, children, maxWidth = 'max-w-md',
}: SeasonDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
        <Dialog.Content
          className={`fixed left-1/2 top-1/2 z-50 w-[92vw] ${maxWidth} -translate-x-1/2 -translate-y-1/2 rounded-2xl p-6 dark:bg-[#16161d] bg-white border dark:border-white/10 border-gray-200 shadow-2xl focus:outline-none max-h-[85vh] overflow-y-auto`}
        >
          <div className="flex items-start justify-between mb-4 gap-3">
            <div className="flex items-center gap-2.5 min-w-0">
              {icon}
              <div className="min-w-0">
                <Dialog.Title className="text-base font-semibold dark:text-white text-gray-900">
                  {title}
                </Dialog.Title>
                {description && (
                  <Dialog.Description className="text-xs dark:text-white/40 text-gray-400">
                    {description}
                  </Dialog.Description>
                )}
              </div>
            </div>
            <Dialog.Close asChild>
              <button className="p-1 rounded-lg dark:hover:bg-white/10 hover:bg-gray-100 flex-shrink-0">
                <X className="w-4 h-4 dark:text-white/50 text-gray-400" />
              </button>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
