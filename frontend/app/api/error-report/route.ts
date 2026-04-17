import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()

    // Forward to backend which handles storage + email notification
    const res = await fetch(`${BACKEND}/api/v1/error-report`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!res.ok) {
      // Backend unavailable — still return 200 so the client doesn't loop
      return NextResponse.json({ ok: false, note: 'backend unreachable' }, { status: 200 })
    }

    return NextResponse.json({ ok: true }, { status: 200 })
  } catch {
    // Never 500 — error reporter must not itself error
    return NextResponse.json({ ok: false }, { status: 200 })
  }
}
