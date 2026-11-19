import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/client'
import { BASE_URL } from '../../api/session'
import { sendRequest } from '../workbench/sendRequest'
import { PREVIEW_ORIGIN } from '../workbench/previewOrigin'
import {
  appErrorMessage, buildPreviewBase, isPreviewTokenRefusal, joinPreviewUrl, parseAccessToken, pickLivePreview,
  type PreviewSession, type SessionResponse, type SessionStatus,
} from './previewSession'

const POLL_MS = 2000
const origin0 = (): string | null => PREVIEW_ORIGIN ?? BASE_URL ?? null

interface Options {
  /** True when the page was given its own session (tests): this hook then stays idle. */
  disabled?: boolean
  origin?: string | null
  doFetch?: typeof fetch
  pollMs?: number
}

/** The shared preview session for the pack pages: finds (or starts) the project's preview, refreshes its access token on connect
 *  and signs in to the generated app. Both tokens live only in this hook's refs: cleared on project change and unmount. */
export function usePreviewSession(projectId: string, opts: Options = {}): PreviewSession {
  const { disabled = false, doFetch, pollMs = POLL_MS } = opts
  const origin = opts.origin === undefined ? origin0() : opts.origin
  const [status, setStatus] = useState<SessionStatus>(disabled ? 'loading' : origin ? 'loading' : 'no-origin')
  const [base, setBase] = useState<string | null>(null)
  const [previewState, setPreviewState] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const previewToken = useRef<string | null>(null)
  const jwt = useRef<string | null>(null)
  const baseRef = useRef<string | null>(null)
  const preview = useRef<{ id: string } | null>(null)
  const gen = useRef(0)
  const connectRef = useRef<() => Promise<void>>(async () => {})

  const clear = () => { previewToken.current = null; jwt.current = null; baseRef.current = null; preview.current = null }

  const connect = useCallback(async () => {
    if (disabled) return
    const g = ++gen.current
    const live = () => gen.current === g
    if (!origin) { setStatus('no-origin'); return }
    setError(null)
    try {
      for (;;) {
        const p = pickLivePreview(await api.listPreviews(projectId))
        if (!live()) return
        if (!p) { clear(); setBase(null); setPreviewState(null); setStatus('no-preview'); return }
        preview.current = { id: p.id }
        baseRef.current = buildPreviewBase(origin, p.url_path)
        setBase(baseRef.current); setPreviewState(p.state)
        if (p.state === 'starting') {
          setStatus('starting')
          await new Promise((r) => setTimeout(r, pollMs))
          if (!live()) return
          continue
        }
        if (!previewToken.current) {
          const r = await api.rotatePreviewToken(projectId, p.id)
          if (!live()) return
          previewToken.current = r.token
        }
        setStatus(jwt.current ? 'ready' : 'needs-signin')
        return
      }
    } catch (e) {
      if (!live()) return
      setError(e instanceof Error ? e.message : 'Could not reach the platform')
      setStatus('error')
    }
  }, [projectId, origin, disabled, pollMs])
  connectRef.current = connect

  useEffect(() => {
    if (disabled) return
    clear(); setBase(null); setPreviewState(null); setError(null)
    void connect()
    return () => { gen.current++; clear() }
  }, [connect, disabled])

  const send = useCallback(async (method: string, path: string, body: unknown, withJwt: boolean): Promise<SessionResponse> => {
    const b = baseRef.current
    const tok = previewToken.current
    if (!b || !origin || !tok) throw new Error('No preview session. Connect to a preview first.')
    const r = await sendRequest({
      url: joinPreviewUrl(b, path), origin, method, body: body === undefined ? undefined : JSON.stringify(body),
      previewToken: tok, bearer: withJwt ? (jwt.current ?? undefined) : undefined,
    }, doFetch)
    return { status: r.status, text: r.text }
  }, [origin, doFetch])

  const request = useCallback(async (method: string, path: string, body?: unknown) => {
    const r = await send(method, path, body, true)
    if (r.status === 401) {
      if (isPreviewTokenRefusal(r.status, r.text)) {
        previewToken.current = null; jwt.current = null
        void connectRef.current()
      } else if (jwt.current) {
        jwt.current = null
        setStatus('needs-signin')
      }
    }
    return r
  }, [send])

  const signIn = useCallback(async (email: string, password: string): Promise<string | null> => {
    try {
      const r = await send('POST', '/auth/login', { email, password }, false)
      if (isPreviewTokenRefusal(r.status, r.text)) { previewToken.current = null; void connectRef.current(); return 'The preview access token expired. Reconnecting; try again.' }
      const t = r.status >= 200 && r.status < 300 ? parseAccessToken(r.text) : null
      if (!t) return appErrorMessage(r.status, r.text)
      jwt.current = t
      setStatus('ready')
      return null
    } catch (e) { return e instanceof Error ? e.message : 'Could not reach the preview app' }
  }, [send])

  const register = useCallback(async (email: string, password: string): Promise<string | null> => {
    try {
      const r = await send('POST', '/auth/register', { email, password }, false)
      if (r.status < 200 || r.status >= 300) return appErrorMessage(r.status, r.text)
    } catch (e) { return e instanceof Error ? e.message : 'Could not reach the preview app' }
    const m = await signIn(email, password)
    return m ? `Account created, but signing in failed: ${m}` : null
  }, [send, signIn])

  const signOut = useCallback(() => { jwt.current = null; setStatus(previewToken.current ? 'needs-signin' : 'loading') }, [])

  const start = useCallback(async () => {
    if (disabled) return
    const g = ++gen.current
    setError(null); setStatus('loading')
    try {
      const c = await api.createPreview(projectId)
      if (gen.current !== g) return
      previewToken.current = c.token
      await connectRef.current()
    } catch (e) {
      if (gen.current !== g) return
      setError(e instanceof Error ? e.message : 'Could not start a preview')
      setStatus('error')
    }
  }, [projectId, disabled])

  return useMemo(() => ({ status, base, previewState, error, request, start, signIn, register, signOut }),
    [status, base, previewState, error, request, start, signIn, register, signOut])
}
