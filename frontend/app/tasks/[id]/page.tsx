'use client'

import { use, useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import {
  ArrowLeft, BookOpen, Check, Plus, Trash2, AlertCircle,
  MessageSquare, Calendar, User as UserIcon,
} from 'lucide-react'
import { api } from '@/lib/api'
import GlassCard from '@/components/ui/GlassCard'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import {
  TaskDetail, TaskStatus, Role,
  STATUS_META, PRIORITY_META, TASK_STATUS_ORDER,
} from '@/lib/teamos'

interface Me {
  user_id?: number
  username?: string
  role?: Role
}

export default function TaskDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const taskId = Number(id)
  const router = useRouter()

  const [me, setMe] = useState<Me | null>(null)
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [newItem, setNewItem] = useState('')
  const [newComment, setNewComment] = useState('')
  const [posting, setPosting] = useState(false)

  const load = useCallback(async () => {
    try {
      const [meData, detail] = await Promise.all([
        api.get<Me>('/users/me'),
        api.get<TaskDetail>(`/tasks/${taskId}`),
      ])
      setMe(meData)
      setTask(detail)
    } catch (e: unknown) {
      setErr((e as Error).message || 'Failed to load task')
    } finally {
      setLoading(false)
    }
  }, [taskId])

  useEffect(() => {
    load()
  }, [load])

  const canManage = me?.role === 'admin' || me?.role === 'operator'

  async function updateStatus(status: TaskStatus) {
    if (!task) return
    try {
      await api.patch(`/tasks/${task.task_id}`, { status })
      setTask({
        ...task,
        status,
        completed_at:
          status === 'done' ? new Date().toISOString() : null,
      })
    } catch (e: unknown) {
      alert((e as Error).message || 'Update failed')
    }
  }

  async function toggleChecklist(itemId: number, done: boolean) {
    if (!task) return
    const optimistic = task.checklist.map((i) =>
      i.id === itemId ? { ...i, done } : i
    )
    setTask({ ...task, checklist: optimistic })
    try {
      await api.patch(`/tasks/${task.task_id}/checklist/${itemId}`, { done })
    } catch (e: unknown) {
      alert((e as Error).message || 'Update failed')
      load()
    }
  }

  async function addChecklistItem(e: React.FormEvent) {
    e.preventDefault()
    if (!task || !newItem.trim()) return
    try {
      const item = await api.post<TaskDetail['checklist'][number]>(
        `/tasks/${task.task_id}/checklist`,
        { label: newItem.trim() }
      )
      setTask({ ...task, checklist: [...task.checklist, item] })
      setNewItem('')
    } catch (e: unknown) {
      alert((e as Error).message || 'Add failed')
    }
  }

  async function removeChecklistItem(itemId: number) {
    if (!task) return
    if (!confirm('Remove this item?')) return
    try {
      await api.delete(`/tasks/${task.task_id}/checklist/${itemId}`)
      setTask({
        ...task,
        checklist: task.checklist.filter((i) => i.id !== itemId),
      })
    } catch (e: unknown) {
      alert((e as Error).message || 'Delete failed')
    }
  }

  async function addComment(e: React.FormEvent) {
    e.preventDefault()
    if (!task || !newComment.trim()) return
    setPosting(true)
    try {
      const c = await api.post<TaskDetail['comments'][number]>(
        `/tasks/${task.task_id}/comments`,
        { body: newComment.trim() }
      )
      setTask({ ...task, comments: [...task.comments, c] })
      setNewComment('')
    } catch (e: unknown) {
      alert((e as Error).message || 'Post failed')
    } finally {
      setPosting(false)
    }
  }

  async function deleteTask() {
    if (!task) return
    if (!confirm('Delete this task permanently?')) return
    try {
      await api.delete(`/tasks/${task.task_id}`)
      router.push('/tasks')
    } catch (e: unknown) {
      alert((e as Error).message || 'Delete failed')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner />
      </div>
    )
  }

  if (err || !task) {
    return (
      <div className="max-w-2xl mx-auto p-6">
        <Link
          href="/tasks"
          className="inline-flex items-center gap-1 text-sm dark:text-white/60 text-gray-600 mb-4"
        >
          <ArrowLeft className="w-4 h-4" /> Back to tasks
        </Link>
        <div className="p-3 rounded-lg border border-red-500/30 bg-red-500/10 text-red-500 text-sm">
          {err || 'Task not found'}
        </div>
      </div>
    )
  }

  const priority = PRIORITY_META[task.priority]
  const progress =
    task.checklist.length === 0
      ? null
      : Math.round(
          (task.checklist.filter((i) => i.done).length / task.checklist.length) * 100
        )

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="max-w-3xl mx-auto px-4 py-6 md:py-10 space-y-6"
    >
      <Link
        href="/tasks"
        className="inline-flex items-center gap-1 text-sm dark:text-white/60 text-gray-600 dark:hover:text-white hover:text-gray-900"
      >
        <ArrowLeft className="w-4 h-4" /> Back to tasks
      </Link>

      <GlassCard>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <h1 className="text-xl md:text-2xl font-bold dark:text-white text-gray-900">
              {task.title}
            </h1>
            <div className="flex flex-wrap items-center gap-2 mt-2">
              <StatusPill status={task.status} />
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${priority.badge}`}
              >
                {priority.label.toUpperCase()}
              </span>
              {task.assignee && (
                <span className="inline-flex items-center gap-1.5 text-xs dark:text-white/60 text-gray-600">
                  <UserIcon className="w-3 h-3" />
                  {task.assignee.display_name}
                </span>
              )}
              {task.due_at && (
                <span className="inline-flex items-center gap-1.5 text-xs dark:text-white/60 text-gray-600">
                  <Calendar className="w-3 h-3" />
                  {new Date(task.due_at).toLocaleDateString()}
                </span>
              )}
            </div>
          </div>
          {canManage && (
            <button
              onClick={deleteTask}
              className="p-2 rounded-lg text-red-500 hover:bg-red-500/10 cursor-pointer"
              title="Delete task"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
        </div>

        {task.description && (
          <div className="mt-4 text-sm dark:text-white/80 text-gray-700 whitespace-pre-wrap">
            {task.description}
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {TASK_STATUS_ORDER.map((s) => (
            <button
              key={s}
              onClick={() => updateStatus(s)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all cursor-pointer ${
                task.status === s
                  ? 'border-[#667eea] bg-[#667eea]/10 text-[#667eea]'
                  : 'dark:border-white/[0.1] border-gray-200 dark:text-white/60 text-gray-600 dark:hover:bg-white/[0.04] hover:bg-gray-50'
              }`}
            >
              {STATUS_META[s].label}
            </button>
          ))}
        </div>

        {task.linked_sop_id && (
          <Link
            href={`/sops/${task.linked_sop_id}`}
            className="mt-4 inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm dark:bg-white/[0.04] bg-gray-50 dark:text-white/80 text-gray-700 dark:hover:bg-white/[0.07] hover:bg-gray-100 transition"
          >
            <BookOpen className="w-4 h-4" />
            Open linked SOP
          </Link>
        )}
      </GlassCard>

      {/* Checklist */}
      <GlassCard>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold dark:text-white text-gray-900">Checklist</h2>
          {progress !== null && (
            <span className="text-xs dark:text-white/50 text-gray-500">
              {progress}%
            </span>
          )}
        </div>
        {task.checklist.length === 0 ? (
          <p className="text-sm dark:text-white/40 text-gray-400 italic">
            No items yet.
          </p>
        ) : (
          <ul className="space-y-2">
            {task.checklist.map((item) => (
              <li key={item.id} className="flex items-start gap-2 group">
                <button
                  onClick={() => toggleChecklist(item.id, !item.done)}
                  className={`mt-0.5 w-4 h-4 rounded border flex-shrink-0 flex items-center justify-center cursor-pointer transition ${
                    item.done
                      ? 'bg-emerald-500 border-emerald-500'
                      : 'dark:border-white/30 border-gray-300 hover:border-[#667eea]'
                  }`}
                >
                  {item.done && <Check className="w-3 h-3 text-white" />}
                </button>
                <span
                  className={`flex-1 text-sm ${
                    item.done
                      ? 'line-through dark:text-white/40 text-gray-400'
                      : 'dark:text-white/80 text-gray-700'
                  }`}
                >
                  {item.label}
                </span>
                {canManage && (
                  <button
                    onClick={() => removeChecklistItem(item.id)}
                    className="opacity-0 group-hover:opacity-100 text-red-500 hover:bg-red-500/10 p-1 rounded cursor-pointer"
                    title="Remove"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={addChecklistItem} className="flex gap-2 mt-4">
          <input
            type="text"
            value={newItem}
            onChange={(e) => setNewItem(e.target.value)}
            placeholder="Add a checklist item"
            className="flex-1 px-3 py-2 rounded-lg text-sm dark:bg-white/[0.04] bg-white border dark:border-white/[0.1] border-gray-200 dark:text-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#667eea]/50"
          />
          <button
            type="submit"
            disabled={!newItem.trim()}
            className="px-3 py-2 rounded-lg text-sm dark:bg-white/[0.06] bg-gray-100 dark:text-white/80 text-gray-700 disabled:opacity-40 cursor-pointer"
          >
            <Plus className="w-4 h-4" />
          </button>
        </form>
      </GlassCard>

      {/* Comments */}
      <GlassCard>
        <h2 className="font-semibold dark:text-white text-gray-900 mb-3 flex items-center gap-2">
          <MessageSquare className="w-4 h-4" /> Comments
        </h2>
        {task.comments.length === 0 ? (
          <p className="text-sm dark:text-white/40 text-gray-400 italic mb-3">
            No comments yet.
          </p>
        ) : (
          <div className="space-y-3 mb-4">
            {task.comments.map((c) => (
              <div key={c.id} className="flex gap-3">
                {c.author ? (
                  <div
                    className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-[11px] font-bold text-white"
                    style={{ backgroundColor: c.author.color }}
                  >
                    {c.author.initials}
                  </div>
                ) : (
                  <div className="w-8 h-8 rounded-full bg-gray-300 flex-shrink-0" />
                )}
                <div className="flex-1">
                  <div className="flex items-baseline gap-2 mb-0.5">
                    <span className="text-sm font-medium dark:text-white text-gray-900">
                      {c.author?.display_name || 'Someone'}
                    </span>
                    <span className="text-[10px] dark:text-white/40 text-gray-400">
                      {c.created_at
                        ? new Date(c.created_at).toLocaleString()
                        : ''}
                    </span>
                  </div>
                  <p className="text-sm dark:text-white/80 text-gray-700 whitespace-pre-wrap">
                    {c.body}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}

        <form onSubmit={addComment} className="space-y-2">
          <textarea
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
            rows={2}
            placeholder="Add a comment"
            className="w-full px-3 py-2 rounded-lg text-sm dark:bg-white/[0.04] bg-white border dark:border-white/[0.1] border-gray-200 dark:text-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#667eea]/50"
          />
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={!newComment.trim() || posting}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-[#667eea] to-[#764ba2] text-white disabled:opacity-50 cursor-pointer"
            >
              {posting ? 'Posting…' : 'Post'}
            </button>
          </div>
        </form>
      </GlassCard>
    </motion.div>
  )
}

function StatusPill({ status }: { status: TaskStatus }) {
  const meta = STATUS_META[status]
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-full dark:bg-white/[0.04] bg-gray-100 ${meta.color}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${meta.dotBg}`} />
      {meta.label}
    </span>
  )
}
