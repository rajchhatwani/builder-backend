import type { PreviewSession, SessionStatus } from './previewSession'

/** A ready session for page tests: requests go to `doFetch` as `http://gen.test<path>`, like the real one but with no network or auth. */
export function readySession(doFetch: typeof fetch, over: Partial<PreviewSession> = {}): PreviewSession {
  const base = 'http://gen.test'
  return {
    status: 'ready', base, previewState: 'running', error: null,
    request: async (method, path, body) => {
      const res = await doFetch(base + path, { method, body: body === undefined ? undefined : JSON.stringify(body), headers: {} })
      return { status: res.status, text: await res.text() }
    },
    start: async () => {}, signIn: async () => null, register: async () => null, signOut: () => {},
    ...over,
  }
}

export const stubSession = (status: SessionStatus, over: Partial<PreviewSession> = {}): PreviewSession =>
  ({ ...readySession((async () => new Response('{}')) as unknown as typeof fetch), status, base: null, previewState: null, ...over })
