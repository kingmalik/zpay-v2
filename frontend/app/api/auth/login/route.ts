import { NextRequest, NextResponse } from 'next/server'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export async function POST(request: NextRequest) {
  const body = await request.json()

  const form = new URLSearchParams()
  form.append('username', body.username ?? '')
  form.append('password', body.password ?? '')

  // Use manual redirect so we can capture Set-Cookie from the 302 response
  const res = await fetch(`${API_URL}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form.toString(),
    redirect: 'manual',
  })

  // FastAPI returns 302 on success with Set-Cookie, 200/401 on failure
  const setCookie = res.headers.get('set-cookie')
  if ((res.status === 302 || res.status === 303) && setCookie) {
    const response = NextResponse.json({ ok: true })
    response.headers.set('set-cookie', setCookie)
    return response
  }

  return NextResponse.json({ error: 'Invalid username or password' }, { status: 401 })
}
