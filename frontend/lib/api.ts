import { toast } from 'sonner'

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
// Use Next.js rewrite proxy so cookies (zpay_session) flow correctly
const API_URL = '/api/v1'

const SESSION_EXPIRED_MESSAGE = 'Your session expired. Sign in again.'

/** The auth gate redirects cookie-less requests to /login; fetch follows it. */
function isLoginRedirect(res: Response): boolean {
  if (!res.redirected) return false
  try {
    return new URL(res.url).pathname === '/login'
  } catch {
    return false
  }
}

/** Prefer the backend's own error text over a bare status code. */
async function readErrorMessage(res: Response): Promise<string> {
  const text = await res.text()
  if (!text) return `HTTP ${res.status}`
  try {
    const parsed = JSON.parse(text) as { error?: unknown; detail?: unknown }
    const message = parsed.error ?? parsed.detail
    if (typeof message === 'string' && message) return message
  } catch {
    // not JSON — fall through to raw text
  }
  return text.length > 300 ? `HTTP ${res.status}` : text
}

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

  if (res.status === 401 || isLoginRedirect(res)) {
    if (typeof window !== 'undefined') {
      window.location.href = '/login'
    }
    throw new Error(SESSION_EXPIRED_MESSAGE)
  }

  if (!res.ok) {
    throw new Error(await readErrorMessage(res))
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
    if (res.status === 401 || isLoginRedirect(res)) {
      if (typeof window !== 'undefined') window.location.href = '/login'
      throw new Error(SESSION_EXPIRED_MESSAGE)
    }
    if (!res.ok) throw new Error(await readErrorMessage(res))
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
