// Shared Team OS types for tasks + SOPs.

export type Role = 'admin' | 'operator' | 'associate'
export type TaskStatus = 'todo' | 'in_progress' | 'blocked' | 'done'
export type TaskPriority = 'low' | 'normal' | 'high' | 'urgent'

export interface PersonRef {
  user_id: number
  username?: string
  display_name: string
  color: string
  initials: string
}

export interface TaskRow {
  task_id: number
  title: string
  description?: string | null
  assignee_id?: number | null
  created_by?: number | null
  priority: TaskPriority
  status: TaskStatus
  due_at?: string | null
  linked_sop_id?: number | null
  created_at?: string | null
  updated_at?: string | null
  completed_at?: string | null
  assignee?: PersonRef | null
  creator?: PersonRef | null
}

export interface ChecklistItem {
  id: number
  label: string
  done: boolean
  order_index: number
}

export interface Comment {
  id: number
  body: string
  created_at?: string | null
  author?: PersonRef | null
}

export interface TaskDetail extends TaskRow {
  checklist: ChecklistItem[]
  comments: Comment[]
}

export interface SOPRow {
  sop_id: number
  title: string
  category?: string | null
  owner_role: Role
  trigger_when?: string | null
  content: string
  version: number
  archived: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface SOPFieldNote {
  id: number
  note: string
  promoted: boolean
  created_at?: string | null
  author?: PersonRef | null
}

export interface SOPDetail extends SOPRow {
  field_notes: SOPFieldNote[]
}

export const STATUS_META: Record<
  TaskStatus,
  { label: string; color: string; dotBg: string }
> = {
  todo: {
    label: 'To do',
    color: 'dark:text-white/60 text-gray-600',
    dotBg: 'bg-gray-400',
  },
  in_progress: {
    label: 'In progress',
    color: 'text-[#667eea]',
    dotBg: 'bg-[#667eea]',
  },
  blocked: {
    label: 'Blocked',
    color: 'text-amber-500',
    dotBg: 'bg-amber-500',
  },
  done: {
    label: 'Done',
    color: 'text-emerald-500',
    dotBg: 'bg-emerald-500',
  },
}

export const PRIORITY_META: Record<
  TaskPriority,
  { label: string; badge: string }
> = {
  low: {
    label: 'Low',
    badge: 'bg-gray-500/10 text-gray-500',
  },
  normal: {
    label: 'Normal',
    badge: 'bg-[#667eea]/10 text-[#667eea]',
  },
  high: {
    label: 'High',
    badge: 'bg-orange-500/15 text-orange-500',
  },
  urgent: {
    label: 'Urgent',
    badge: 'bg-red-500/15 text-red-500',
  },
}

export const TASK_STATUS_ORDER: TaskStatus[] = [
  'todo',
  'in_progress',
  'blocked',
  'done',
]
