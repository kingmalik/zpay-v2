import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const MAX_REDIRECTS = 5

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params
  const backendUrl = `${BACKEND}/${path.join('/')}`
  const search = req.nextUrl.search
  let url = search ? `${backendUrl}${search}` : backendUrl

  // Build headers — forward raw Cookie so Railway can validate the session
  const buildHeaders = (contentType?: string | null): Record<string, string> => {
    const h: Record<string, string> = { 'Accept': 'application/json' }
    const cookieHeader = req.headers.get('cookie')
    if (cookieHeader) h['Cookie'] = cookieHeader
    const ct = contentType ?? req.headers.get('content-type') ?? ''
    if (ct && !ct.includes('multipart/form-data')) h['Content-Type'] = ct
    return h
  }

  const body = ['GET', 'HEAD'].includes(req.method) ? undefined : await req.arrayBuffer()

  // Manually follow redirects so Cookie header is preserved on each hop
  let backendRes: Response | null = null
  for (let i = 0; i < MAX_REDIRECTS; i++) {
    backendRes = await fetch(url, {
      method: req.method,
      headers: buildHeaders(),
      body: body && body.byteLength > 0 ? body : undefined,
      redirect: 'manual',
    })

    const status = backendRes.status
    if (status >= 300 && status < 400) {
      const location = backendRes.headers.get('location')
      if (!location) break
      // Resolve relative redirects against the backend base
      url = location.startsWith('http') ? location : `${BACKEND}${location}`
      continue
    }
    break
  }

  if (!backendRes) return new NextResponse('Proxy error', { status: 502 })

  const resHeaders = new Headers()
  const contentType = backendRes.headers.get('content-type')
  if (contentType) resHeaders.set('content-type', contentType)
  backendRes.headers.forEach((val, key) => {
    if (key.toLowerCase() === 'set-cookie') resHeaders.append('set-cookie', val)
  })

  const resBody = await backendRes.arrayBuffer()
  return new NextResponse(resBody, {
    status: backendRes.status,
    headers: resHeaders,
  })
}

export const GET = proxy
export const POST = proxy
export const PUT = proxy
export const PATCH = proxy
export const DELETE = proxy
export const OPTIONS = proxy
