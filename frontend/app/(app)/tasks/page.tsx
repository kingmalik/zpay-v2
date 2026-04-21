'use client'

import { useEffect, useMemo, useState, useCallback } from 'react'
import Link from 'next/link'
import { motion, AnimatePresence } from 'framer-motion'
import { ClipboardList, Plus, X, Filter, AlertCircle, BookOpen } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import EmptyState from '@/components/ui/EmptyState'
import PageHeader from '@/components/ui/PageHeader'
import { primaryBtn, secondaryBtn, inputCls, labelCls } from '@/lib/styles'
import {
  TaskRow, TaskStatus, TaskPriority, Role,
  STATUS_META, PRIORITY_META, TASK_STATUS_ORDER,
  SOPRow, PersonRef,
} from '@/lib/teamos'

interface Me {
  user_id?: number
  username?: string
  role?: Role
}

const COLUMN_ACCENT: Record<TaskStatus, string> = {
  todo:        'border-t-gray-400/40',
  in_progress: 'border-t-[#667eea]/70',
  blocked:     'border-t-amber-500/70',
  done:        'border-t-emerald-500/70',
}

export default function TasksPage() {
  const [me, setMe] = useState<Me | null>(null)
  const [tasks, setTasks] = useState<TaskRow[]>([])
  const [team, setTeam] = useState<PersonRef[]>([])
  const [sops, setSops] = useState<SOPRow[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [filter, setFilter] = useState<number | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  const load = useCallback(async () => {
    try {
      const meData = await api.get<Me>('/users/me')
      setMe(meData)
      const canSeeTeam = meData.role === 'admin' || meData.role === 'operator'
      const [t, teamData, sopData] = await Promise.all([
        api.get<TaskRow[]>('/tasks'),
        canSeeTeam ? api.get<PersonRef[]>('/users').catch(() => []) : Promise.resolve([]),
        api.get<SOPRow[]>('/sops').catch(() => []),
      ])
      setTasks(t)
      setTeam(teamData)
      setSops(sopData)
    } catch (e: unknown) {
      setErr((e as Error).message || 'Failed to load tasks')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const canManage = me?.role === 'admin' || me?.role === 'operator'

  const byStatus = useMemo(() => {
    const groups: Record<TaskStatus, TaskRow[]> = {
      todo: [], in_progress: [], blocked: [], done: [],
    }
    const source = filter ? tasks.filter(t => t.assignee_id === filter) : tasks
    for (const t of source) groups[t.status].push(t)
    return groups
  }, [tasks, filter])

  async function moveTask(task: TaskRow, status: TaskStatus) {
    const prev = tasks
    setTasks(cur => cur.map(t => t.task_id === task.task_id ? { ...t, status } : t))
    try {
      await api.patch(`/tasks/${task.task_id}`, { status })
    } catch (e: unknown) {
      setTasks(prev)
      alert((e as Error).message || 'Update failed')
    }
  }

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner /></div>

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="max-w-7xl mx-auto px-4 py-6 md:py-10 space-y-6"
    >
      <PageHeader
        title="Tasks"
        subtitle={canManage ? "Delegate work and track what's in motion." : 'Work assigned to you.'}
        icon={<ClipboardList className="w-4 h-4" />}
        actions={
          <div className="flex items-center gap-2">
            {canManage && team.length > 0 && (
              <AssigneeFilter team={team} value={filter} onChange={setFilter} />
            )}
            {canManage && (
              <button
                onClick={() => setCreateOpen(true)}
                className={cn(primaryBtn, 'flex items-center gap-2 px-4 py-2 text-sm')}
              >
                <Plus className="w-4 h-4" />
                New task
              </button>
            )}
          </div>
        }
      />

      {err && (
        <div className="flex gap-2 p-3 rounded-lg border border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{err}</span>
        </div>
      )}

      {tasks.length === 0 ? (
        <EmptyState
          icon={<ClipboardList className="w-8 h-8" />}
          title="No tasks yet"
          subtitle={canManage ? 'Create the first task to get the board rolling.' : 'Nothing assigned to you right now.'}
        />
      ) : (
        <div data-tour="tasks-board" className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {TASK_STATUS_ORDER.map(status => (
            <Column
              key={status}
              status={status}
              tasks={byStatus[status]}
              canManage={!!canManage}
              onMove={moveTask}
            />
          ))}
        </div>
      )}

      <AnimatePresence>
        {createOpen && (
          <CreateTaskModal
            team={team}
            sops={sops}
            onClose={() => setCreateOpen(false)}
            onCreated={() => { setCreateOpen(false); load() }}
          />
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function Column({ status, tasks, canManage, onMove }: {
  status: TaskStatus
  tasks: TaskRow[]
  canManage: boolean
  onMove: (t: TaskRow, s: TaskStatus) => void
}) {
  const meta = STATUS_META[status]
  return (
    <div className="flex flex-col">
      {/* Column header with colored top border */}
      <div className={cn(
        'flex items-center gap-2 mb-3 p-3 rounded-xl border-t-2',
        'dark:bg-white/[0.03] bg-gray-50/80 border dark:border-white/[0.06] border-gray-100',
        COLUMN_ACCENT[status]
      )}>
        <span className={cn('w-2 h-2 rounded-full flex-shrink-0', meta.dotBg)} />
        <h2 className={cn('font-semibold text-sm flex-1', meta.color)}>{meta.label}</h2>
        <span className={cn(
          'text-xs px-1.5 py-0.5 rounded-md font-medium tabular-nums',
          'dark:bg-white/[0.08] bg-white dark:text-white/50 text-gray-500 border dark:border-white/[0.08] border-gray-200'
        )}>
          {tasks.length}
        </span>
      </div>

      <div className="space-y-2 min-h-[60px]">
        {tasks.length === 0 ? (
          <div className="text-xs dark:text-white/25 text-gray-300 italic px-2 py-6 text-center border-2 border-dashed dark:border-white/[0.05] border-gray-100 rounded-xl">
            Empty
          </div>
        ) : (
          tasks.map(t => (
            <TaskCard key={t.task_id} task={t} canManage={canManage} onMove={onMove} />
          ))
        )}
      </div>
    </div>
  )
}

function TaskCard({ task, canManage, onMove }: {
  task: TaskRow
  canManage: boolean
  onMove: (t: TaskRow, s: TaskStatus) => void
}) {
  const priority = PRIORITY_META[task.priority]
  const isBlocked = task.status === 'blocked'
  const isUrgent = task.priority === 'urgent'
  const isDone = task.status === 'done'

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.15 }}
      className={cn(
        isDone && 'opacity-60'
      )}
    >
      <GlassCard
        className={cn(
          'transition-all group border-l-2',
          isUrgent ? 'border-l-red-500/70' :
          isBlocked ? 'border-l-amber-500/70' :
          'border-l-transparent'
        )}
        padding={false}
        hover
      >
        <Link href={`/tasks/${task.task_id}`} className="block">
          <div className="p-3">
            {/* Title + priority badge */}
            <div className="flex items-start justify-between gap-2 mb-2">
              <h3 className={cn(
                'font-semibold text-sm dark:text-white text-gray-900 line-clamp-2 flex-1',
                isDone && 'line-through dark:text-white/50 text-gray-400'
              )}>
                {task.title}
              </h3>
              {task.priority !== 'normal' && (
                <span className={cn('text-[10px] px-1.5 py-0.5 rounded font-semibold flex-shrink-0', priority.badge)}>
                  {priority.label.toUpperCase()}
                </span>
              )}
            </div>

            {task.description && (
              <p className="text-xs dark:text-white/50 text-gray-500 line-clamp-2 mb-2">
                {task.description}
              </p>
            )}

            {/* Assignee + SOP indicator */}
            <div className="flex items-center gap-2">
              {task.assignee ? (
                <div
                  className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold text-white flex-shrink-0"
                  style={{ backgroundColor: task.assignee.color }}
                  title={task.assignee.display_name}
                >
                  {task.assignee.initials}
                </div>
              ) : (
                <span className="text-[10px] dark:text-white/30 text-gray-400 italic">unassigned</span>
              )}
              {task.linked_sop_id && (
                <BookOpen className="w-3 h-3 dark:text-white/30 text-gray-400" aria-label="Linked SOP" />
              )}
            </div>
          </div>
        </Link>

        {/* Status pill row — replaces the select */}
        {canManage && (
          <div
            className="flex gap-1 px-3 pb-2.5 pt-1 border-t dark:border-white/[0.05] border-gray-100"
            onClick={e => e.stopPropagation()}
          >
            {TASK_STATUS_ORDER.map(s => (
              <button
                key={s}
                onClick={() => onMove(task, s)}
                className={cn(
                  'flex-1 py-1 rounded text-[10px] font-medium transition-colors duration-150 cursor-pointer min-h-[28px]',
                  task.status === s
                    ? cn('text-white', {
                        'bg-gray-500/70':       s === 'todo',
                        'bg-[#667eea]':         s === 'in_progress',
                        'bg-amber-500':         s === 'blocked',
                        'bg-emerald-500':       s === 'done',
                      })
                    : 'dark:text-white/30 text-gray-400 dark:hover:text-white/60 hover:text-gray-600 dark:hover:bg-white/[0.05] hover:bg-gray-100'
                )}
                title={STATUS_META[s].label}
              >
                {STATUS_META[s].label.split(' ')[0]}
              </button>
            ))}
          </div>
        )}
      </GlassCard>
    </motion.div>
  )
}

function AssigneeFilter({ team, value, onChange }: {
  team: PersonRef[]
  value: number | null
  onChange: (v: number | null) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <Filter className="w-4 h-4 dark:text-white/40 text-gray-400" />
      <select
        value={value ?? ''}
        onChange={e => onChange(e.target.value ? Number(e.target.value) : null)}
        className="px-3 py-2 rounded-lg text-sm dark:bg-white/[0.04] bg-white border dark:border-white/[0.1] border-gray-200 dark:text-white text-gray-900 cursor-pointer"
      >
        <option value="">Everyone</option>
        {team.map(u => (
          <option key={u.user_id} value={u.user_id}>{u.display_name}</option>
        ))}
      </select>
    </div>
  )
}

function CreateTaskModal({ team, sops, onClose, onCreated }: {
  team: PersonRef[]
  sops: SOPRow[]
  onClose: () => void
  onCreated: () => void
}) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [assigneeId, setAssigneeId] = useState<number | ''>('')
  const [priority, setPriority] = useState<TaskPriority>('normal')
  const [linkedSop, setLinkedSop] = useState<number | ''>('')
  const [checklist, setChecklist] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setSaving(true)
    try {
      await api.post('/tasks', {
        title,
        description: description || null,
        assignee_id: assigneeId === '' ? null : assigneeId,
        priority,
        linked_sop_id: linkedSop === '' ? null : linkedSop,
        checklist: checklist.split('\n').map(s => s.trim()).filter(Boolean),
      })
      onCreated()
    } catch (e: unknown) {
      setErr((e as Error).message || 'Create failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.96, y: 8 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.96, y: 8 }}
        transition={{ duration: 0.15 }}
        onClick={e => e.stopPropagation()}
        className="w-full max-w-lg dark:bg-[#111113] bg-white border dark:border-white/[0.08] border-gray-200 rounded-2xl shadow-xl max-h-[90vh] overflow-y-auto"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b dark:border-white/[0.08] border-gray-100">
          <h3 className="font-semibold dark:text-white text-gray-900">New task</h3>
          <button onClick={onClose} className="p-1 rounded-lg dark:text-white/50 text-gray-400 dark:hover:bg-white/[0.07] hover:bg-gray-100 cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-3">
          <Field label="Title">
            <input type="text" value={title} onChange={e => setTitle(e.target.value)} required className={inputCls} autoFocus />
          </Field>
          <Field label="Description (optional, markdown)">
            <textarea value={description} onChange={e => setDescription(e.target.value)} rows={3} className={inputCls} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Assignee">
              <select value={assigneeId} onChange={e => setAssigneeId(e.target.value ? Number(e.target.value) : '')} className={inputCls}>
                <option value="">Unassigned</option>
                {team.map(u => <option key={u.user_id} value={u.user_id}>{u.display_name}</option>)}
              </select>
            </Field>
            <Field label="Priority">
              <select value={priority} onChange={e => setPriority(e.target.value as TaskPriority)} className={inputCls}>
                {(['low', 'normal', 'high', 'urgent'] as TaskPriority[]).map(p => (
                  <option key={p} value={p}>{PRIORITY_META[p].label}</option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Link to SOP (optional)">
            <select value={linkedSop} onChange={e => setLinkedSop(e.target.value ? Number(e.target.value) : '')} className={inputCls}>
              <option value="">None</option>
              {sops.map(s => <option key={s.sop_id} value={s.sop_id}>{s.title}</option>)}
            </select>
          </Field>
          <Field label="Checklist (one per line)">
            <textarea value={checklist} onChange={e => setChecklist(e.target.value)} rows={3} placeholder={'Step one\nStep two\nStep three'} className={inputCls} />
          </Field>
          {err && (
            <div className="text-sm text-red-500 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />{err}
            </div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className={cn(secondaryBtn, 'px-4 py-2 text-sm')}>Cancel</button>
            <button type="submit" disabled={saving} className={cn(primaryBtn, 'px-4 py-2 text-sm disabled:opacity-50')}>
              {saving ? 'Creating…' : 'Create task'}
            </button>
          </div>
        </form>
      </motion.div>
    </motion.div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className={labelCls}>{label}</span>
      {children}
    </label>
  )
}
