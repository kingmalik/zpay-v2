import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const MAX_REDIRECTS = 5

// Hop-by-hop headers that must NOT be forwarded to the backend
const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'transfer-encoding',
  'trailer',
  'upgrade',
  'proxy-authorization',
  'proxy-authenticate',
  'te',
  'host',
])

/**
 * Public catch-all proxy for /api/data/[...path]
 * Driver-facing pages (join, training, contract) call /api/data/... directly
 * without the /api/v1 prefix. This proxy forwards them to the Railway backend.
 *
 * Raw body streaming: the original Content-Type header (including multipart boundary)
 * is forwarded as-is — no re-serialization, no boundary mismatch.
 */
async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params
  const backendUrl = `${BACKEND}/api/data/${path.join('/')}`
  const search = req.nextUrl.search
  let url = search ? `${backendUrl}${search}` : backendUrl

  const buildRequestHeaders = (): Record<string, string> => {
    const h: Record<string, string> = {}

    h['Accept'] = req.headers.get('accept') || 'application/json'

    const cookie = req.headers.get('cookie')
    if (cookie) h['Cookie'] = cookie

    if (!['GET', 'HEAD'].includes(req.method)) {
      const ct = req.headers.get('content-type')
      if (ct) h['Content-Type'] = ct
    }

    return h
  }

  let bodyInit: BodyInit | null = null
  if (!['GET', 'HEAD'].includes(req.method)) {
    bodyInit = req.body
  }

  let fetchHeaders = buildRequestHeaders()
  let backendRes: Response | null = null

  for (let i = 0; i < MAX_REDIRECTS; i++) {
    const fetchInit: RequestInit & { duplex?: string } = {
      method: req.method,
      headers: fetchHeaders,
      redirect: 'manual',
    }

    if (bodyInit !== null) {
      fetchInit.body = bodyInit
      fetchInit.duplex = 'half'
    }

    backendRes = await fetch(url, fetchInit)

    const status = backendRes.status
    if (status >= 300 && status < 400) {
      const location = backendRes.headers.get('location')
      if (!location) break
      url = location.startsWith('http') ? location : `${BACKEND}${location}`
      // On redirect, switch to GET with no body
      bodyInit = null
      fetchHeaders = buildRequestHeaders()
      delete fetchHeaders['Content-Type']
      continue
    }
    break
  }

  if (!backendRes) return new NextResponse('Proxy error', { status: 502 })

  const resHeaders = new Headers()
  backendRes.headers.forEach((val, key) => {
    const k = key.toLowerCase()
    if (HOP_BY_HOP.has(k)) return
    if (k === 'set-cookie') {
      resHeaders.append('set-cookie', val)
    } else {
      resHeaders.set(key, val)
    }
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
