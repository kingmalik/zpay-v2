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

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params
  const backendUrl = `${BACKEND}/${path.join('/')}`
  const search = req.nextUrl.search
  let url = search ? `${backendUrl}${search}` : backendUrl

  // Build base request headers — forward Cookie and original Content-Type as-is.
  // The Content-Type for multipart MUST include the boundary parameter, so we
  // never re-generate it. We just pass the header through unchanged.
  const buildRequestHeaders = (): Record<string, string> => {
    const h: Record<string, string> = {}

    const accept = req.headers.get('accept') || '*/*'
    h['Accept'] = accept

    const cookie = req.headers.get('cookie')
    if (cookie) h['Cookie'] = cookie

    // Forward Content-Type for request bodies (multipart boundary included)
    if (!['GET', 'HEAD'].includes(req.method)) {
      const ct = req.headers.get('content-type')
      if (ct) h['Content-Type'] = ct
    }

    return h
  }

  // For non-GET/HEAD requests, stream the raw body directly — no re-serialization.
  // This preserves the multipart boundary that FastAPI needs to parse file uploads.
  // For JSON bodies this is equally correct and simpler.
  let bodyInit: BodyInit | null = null
  if (!['GET', 'HEAD'].includes(req.method)) {
    bodyInit = req.body
  }

  const fetchHeaders = buildRequestHeaders()

  // Manually follow redirects so Cookie is preserved on every hop
  let backendRes: Response | null = null
  for (let i = 0; i < MAX_REDIRECTS; i++) {
    const fetchInit: RequestInit & { duplex?: string } = {
      method: req.method,
      headers: fetchHeaders,
      redirect: 'manual',
    }

    // `duplex: 'half'` is required by the Fetch spec when body is a ReadableStream
    if (bodyInit !== null) {
      fetchInit.body = bodyInit
      fetchInit.duplex = 'half'
    }

    backendRes = await fetch(url, fetchInit)

    const status = backendRes.status
    if (status >= 300 && status < 400) {
      const location = backendRes.headers.get('location')
      if (!location) break
      // Resolve relative redirects
      url = location.startsWith('http') ? location : `${BACKEND}${location}`
      // Redirect: switch to GET with no body
      bodyInit = null
      delete fetchHeaders['Content-Type']
      fetchInit.method = 'GET'
      continue
    }
    break
  }

  if (!backendRes) return new NextResponse('Proxy error', { status: 502 })

  // Forward all safe response headers — including Set-Cookie and Content-Disposition
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
  if (backendRes.status >= 400) {
    const bodyText = new TextDecoder().decode(resBody).slice(0, 500)
    console.error(`[proxy] backend ${req.method} ${url} → ${backendRes.status}: ${bodyText}`)
  }

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
