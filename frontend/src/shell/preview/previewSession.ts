import type { PreviewInstance } from '../../api/types'

/** Pure helpers of the dashboard-supplied preview session (no React, no fetch). */

export type SessionStatus = 'no-origin' | 'loading' | 'no-preview' | 'starting' | 'needs-signin' | 'ready' | 'error'

export interface SessionResponse { status: number; text: string }

export interface PreviewSession {
  status: SessionStatus
  /** `<origin>/previews/{id}` once a preview is chosen, else null. */
  base: string | null
  /** Raw preview state (running, sleeping, ...) for messages; null when there is no preview. */
  previewState: string | null
  error: string | null
  /** `opts.bearer` replaces the session's app login for this one call (a string), or sends no Authorization (null). */
  request: (method: string, path: string, body?: unknown, opts?: { bearer?: string | null }) => Promise<SessionResponse>
  start: () => Promise<void>
  /** Resolve to null on success or a readable message. */
  signIn: (email: string, password: string) => Promise<string | null>
  register: (email: string, password: string) => Promise<string | null>
  signOut: () => void
}

/** Rank of a preview state for picking the one to use; higher wins. States not listed are not usable. */
const RANK: Record<string, number> = { running: 3, starting: 2, sleeping: 1 }

/** The preview to connect to: running, then starting, then sleeping (it wakes on the first request); newest first within a state.
 *  stopping/expired/failed/killed are never picked. */
export function pickLivePreview(list: readonly PreviewInstance[]): PreviewInstance | null {
  let best: PreviewInstance | null = null
  for (const p of list) {
    const r = RANK[p.state]
    if (!r) continue
    if (!best || r > RANK[best.state] || (r === RANK[best.state] && Date.parse(p.created_at) > Date.parse(best.created_at))) best = p
  }
  return best
}

/** `<origin>/previews/{id}`: origin without a trailing slash plus the preview's relative url_path without one. */
export function buildPreviewBase(origin: string, urlPath: string): string {
  const o = origin.replace(/\/+$/, '')
  const p = '/' + urlPath.replace(/^\/+/, '').replace(/\/+$/, '')
  return o + p
}

/** `<base>/<path>`; path always starts with a single slash. */
export function joinPreviewUrl(base: string, path: string): string {
  return base + (path.startsWith('/') ? path : '/' + path)
}

/** What the headers of an app request are, for tests and docs: sendRequest builds the real ones from these two secrets. */
export function previewAuth(previewToken: string | null, jwt: string | null): { previewToken?: string; bearer?: string } {
  return { ...(previewToken ? { previewToken } : {}), ...(jwt ? { bearer: jwt } : {}) }
}

/** Is this 401 the platform proxy refusing the preview token (as opposed to the app refusing the user)? */
export function isPreviewTokenRefusal(status: number, text: string): boolean {
  return status === 401 && /preview token/i.test(text)
}

/** Reads the app's `access_token` from a login answer; null when absent. */
export function parseAccessToken(text: string): string | null {
  try {
    const j = JSON.parse(text) as { access_token?: unknown }
    return typeof j.access_token === 'string' && j.access_token ? j.access_token : null
  } catch { return null }
}

/** Short readable reason from an app error body ({detail|message|error:{message}}). */
export function appErrorMessage(status: number, text: string): string {
  try {
    const j = JSON.parse(text) as { message?: unknown; detail?: unknown; error?: { message?: unknown } }
    const m = j.error?.message ?? j.message ?? j.detail
    if (typeof m === 'string' && m) return m
    if (Array.isArray(m) && m.length > 0) {
      const first = m[0] as { msg?: unknown }
      if (typeof first?.msg === 'string') return first.msg
    }
  } catch { /* not JSON */ }
  if (status === 429) return 'Too many attempts. Wait a moment and try again.'
  if (status === 504 || status === 503) return 'The preview is still waking up. Try again in a few seconds.'
  return `The preview app answered ${status}.`
}

/** Text shown by the gate for each non-ready status. */
export function waitingMessage(status: SessionStatus, previewState: string | null): string {
  if (status === 'loading') return 'Looking for a preview of this project…'
  if (status === 'starting') return 'The preview is starting. This takes a few seconds.'
  if (status === 'needs-signin' && previewState === 'sleeping') return 'The preview is asleep and wakes on your first request (a few seconds).'
  return ''
}
