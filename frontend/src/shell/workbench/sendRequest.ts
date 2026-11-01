import { MAX_RESPONSE_CHARS, REQUEST_TIMEOUT_MS, formatResponseText } from './workbenchLogic'

export interface SendInput {
  /** Already built by buildRequestUrl against the preview origin. */
  url: string
  origin: string
  method: string
  body?: string
  /** Held in memory by the caller only. Never logged, stored or returned. */
  bearer?: string
}
export interface SendResult { status: number; text: string; ms: number }

/** The one place the console calls fetch. Cookies/credentials are never sent, redirects are refused (a redirect
 *  could leave the preview origin), the body is read with a size cap and returned as plain text. */
export async function sendRequest(input: SendInput, doFetch: typeof fetch = fetch): Promise<SendResult> {
  if (new URL(input.url).origin !== input.origin) throw new Error('Refusing a request outside the preview API origin')
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (input.body !== undefined) headers['Content-Type'] = 'application/json'
  if (input.bearer) headers.Authorization = `Bearer ${input.bearer}`
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), REQUEST_TIMEOUT_MS)
  const t0 = performance.now()
  try {
    const res = await doFetch(input.url, {
      method: input.method,
      headers,
      body: input.body,
      credentials: 'omit',
      redirect: 'error',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
      signal: ctl.signal,
    })
    const text = await readCapped(res)
    return { status: res.status, text: formatResponseText(text), ms: Math.round(performance.now() - t0) }
  } catch (e) {
    if (ctl.signal.aborted) throw new Error('The preview API did not answer in time')
    throw new Error(e instanceof TypeError ? 'Could not reach the preview API (network error, CORS or a redirect)' : e instanceof Error ? e.message : 'Request failed')
  } finally {
    clearTimeout(timer)
  }
}

async function readCapped(res: Response): Promise<string> {
  if (!res.body) return await res.text()
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let out = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    out += dec.decode(value, { stream: true })
    if (out.length > MAX_RESPONSE_CHARS) {
      await reader.cancel()
      break
    }
  }
  return out
}
