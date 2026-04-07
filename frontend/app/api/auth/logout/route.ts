import { NextRequest, NextResponse } from 'next/server'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export async function GET(request: NextRequest) {
  await fetch(`${API_URL}/logout`, {
    credentials: 'include',
    headers: { Cookie: request.headers.get('cookie') || '' },
  }).catch(() => {})

  const response = NextResponse.redirect(new URL('/login', request.url))
  response.cookies.set('session', '', { maxAge: 0, path: '/' })
  return response
}
