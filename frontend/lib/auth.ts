import { cookies } from 'next/headers'

export async function getSession(): Promise<string | null> {
  const cookieStore = await cookies()
  return cookieStore.get('session')?.value ?? null
}

export async function isAuthenticated(): Promise<boolean> {
  const session = await getSession()
  return !!session
}
