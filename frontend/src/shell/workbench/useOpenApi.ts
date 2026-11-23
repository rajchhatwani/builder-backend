import { useCallback, useEffect, useState } from 'react'
import type { PreviewSession } from '../preview/previewSession'

export type OpenApiLoad =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; doc: Record<string, unknown> }

/** Fetches the generated project's OpenAPI from `<base>/openapi.json` through the dashboard's preview session (it sends the
 *  preview access token, no cookies, never stores anything). Waits until `enabled` (drawer opened and the session holds a preview). */
export function useOpenApi(session: Pick<PreviewSession, 'request' | 'base'>, enabled: boolean): { load: OpenApiLoad; retry: () => void } {
  const [load, setLoad] = useState<OpenApiLoad>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const { request, base } = session
  const live = enabled && !!base
  useEffect(() => {
    if (!live) return
    let off = false
    setLoad({ status: 'loading' })
    request('GET', '/openapi.json')
      .then((r) => {
        if (off) return
        if (r.status < 200 || r.status >= 300) throw new Error(`The preview API answered ${r.status} for /openapi.json`)
        const doc: unknown = JSON.parse(r.text)
        if (typeof doc !== 'object' || doc === null || Array.isArray(doc) || !('paths' in doc)) throw new Error('That is not an OpenAPI document')
        setLoad({ status: 'ready', doc: doc as Record<string, unknown> })
      })
      .catch((e: unknown) => {
        if (off) return
        setLoad({ status: 'error', message: e instanceof SyntaxError ? 'That is not an OpenAPI document' : e instanceof Error ? e.message : 'Could not load the API description' })
      })
    return () => { off = true }
  }, [request, base, live, attempt])
  return { load, retry: useCallback(() => setAttempt((n) => n + 1), []) }
}
