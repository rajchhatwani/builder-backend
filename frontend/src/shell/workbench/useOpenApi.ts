import { useCallback, useEffect, useState } from 'react'

export type OpenApiLoad =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; doc: Record<string, unknown> }

/** Fetches the generated project's OpenAPI from the preview API origin (GET, no credentials, never stored). */
export function useOpenApi(origin: string | null, enabled: boolean): { load: OpenApiLoad; retry: () => void } {
  const [load, setLoad] = useState<OpenApiLoad>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!origin || !enabled) return
    const ctl = new AbortController()
    setLoad({ status: 'loading' })
    fetch(`${origin}/openapi.json`, { credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal: ctl.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error(`The preview API answered ${r.status} for /openapi.json`)
        const doc: unknown = await r.json()
        if (typeof doc !== 'object' || doc === null || Array.isArray(doc) || !('paths' in doc)) throw new Error('That is not an OpenAPI document')
        setLoad({ status: 'ready', doc: doc as Record<string, unknown> })
      })
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return
        setLoad({ status: 'error', message: e instanceof TypeError ? 'Could not reach the preview API. Is the preview running?' : e instanceof Error ? e.message : 'Could not load the API description' })
      })
    return () => ctl.abort()
  }, [origin, enabled, attempt])
  return { load, retry: useCallback(() => setAttempt((n) => n + 1), []) }
}
