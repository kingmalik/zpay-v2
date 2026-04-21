import { toast } from 'sonner'

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
// Use Next.js rewrite proxy so cookies (zpay_session) flow correctly
const API_URL = '/api/v1'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      ...options.headers,
    },
    ...options,
  })

  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      window.location.href = '/login'
    }
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }

  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) {
    return res.json()
  }
  return res.text() as unknown as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PATCH',
      body: body ? JSON.stringify(body) : undefined,
    }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(path: string) =>
    request<T>(path, { method: 'DELETE' }),
  postForm: async <T>(path: string, formData: FormData): Promise<T> => {
    const res = await fetch(`/api/v1${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Accept': 'application/json' },
      body: formData,
    })
    if (res.status === 401) {
      if (typeof window !== 'undefined') window.location.href = '/login'
      throw new Error('Unauthorized')
    }
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },
}

/**
 * Wraps any async mutation with automatic toast feedback.
 * All mutation call sites should use this so failures are never silent.
 *
 * @param fn       Async function that performs the mutation
 * @param messages Custom messages for success and error states
 */
export async function apiMutation<T>(
  fn: () => Promise<T>,
  messages: { success: string; error?: string }
): Promise<T | null> {
  try {
    const result = await fn()
    toast.success(messages.success)
    return result
  } catch (err: unknown) {
    const detail = err instanceof Error ? err.message : 'Something went wrong'
    toast.error(messages.error ?? detail, { description: messages.error ? detail : undefined })
    return null
  }
}

export { API_URL, BACKEND_URL }
