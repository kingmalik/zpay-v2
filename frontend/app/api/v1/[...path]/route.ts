import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const MAX_REDIRECTS = 5

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params
  const backendUrl = `${BACKEND}/${path.join('/')}`
  const search = req.nextUrl.search
  let url = search ? `${backendUrl}${search}` : backendUrl

  // Build base headers — forward Cookie so Railway validates session
  const baseHeaders = (): Record<string, string> => {
    const h: Record<string, string> = { 'Accept': 'application/json' }
    const cookieHeader = req.headers.get('cookie')
    if (cookieHeader) h['Cookie'] = cookieHeader
    return h
  }

  // Determine body and headers to send
  let bodyInit: BodyInit | undefined = undefined
  let fetchHeaders: Record<string, string> = baseHeaders()

  if (!['GET', 'HEAD'].includes(req.method)) {
    const ct = req.headers.get('content-type') ?? ''
    if (ct.includes('multipart/form-data')) {
      // Parse formData and explicitly read file bytes so they survive the re-serialization
      const formData = await req.formData()
      const newFormData = new FormData()
      for (const [key, value] of formData.entries()) {
        if (value instanceof File) {
          const bytes = await value.arrayBuffer()
          const fname = value.name || 'upload.xlsx'
          console.log(`[proxy-upload] key=${key} filename=${fname} type=${value.type} size=${bytes.byteLength}`)
          newFormData.append(key, new File([bytes], fname, { type: value.type || 'application/octet-stream' }))
        } else {
          console.log(`[proxy-upload] key=${key} value=${value}`)
          newFormData.append(key, value)
        }
      }
      bodyInit = newFormData
      // Do NOT set Content-Type — fetch sets it with the correct boundary
    } else {
      const buf = await req.arrayBuffer()
      bodyInit = buf.byteLength > 0 ? buf : undefined
      if (ct) fetchHeaders['Content-Type'] = ct
    }
  }

  // Manually follow redirects so Cookie header is preserved on each hop
  let backendRes: Response | null = null
  for (let i = 0; i < MAX_REDIRECTS; i++) {
    backendRes = await fetch(url, {
      method: req.method,
      headers: fetchHeaders,
      body: bodyInit,
      redirect: 'manual',
    })

    const status = backendRes.status
    if (status >= 300 && status < 400) {
      const location = backendRes.headers.get('location')
      if (!location) break
      // Resolve relative redirects against the backend base
      url = location.startsWith('http') ? location : `${BACKEND}${location}`
      // On redirect, switch to GET with no body
      bodyInit = undefined
      fetchHeaders = baseHeaders()
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
  if (backendRes.status >= 400) {
    const bodyText = new TextDecoder().decode(resBody).slice(0, 500)
    console.log(`[proxy-upload] backend status=${backendRes.status} body=${bodyText}`)
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
