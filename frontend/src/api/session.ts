/**
 * Sign-in state for the two surfaces of the platform: the customer app and the admin console.
 *
 * Access tokens live only in memory (a page reload loses them on purpose); the long-lived refresh
 * token is an httpOnly cookie the browser sends to /account or /admin and page scripts cannot read.
 * When a request gets 401 we refresh once, shared by every request in flight, and retry.
 */

export type Surface = 'app' | 'admin'

/** 'lost' = the refresh cookie was refused (sign in again); 'unavailable' = 5xx/429/offline (try later). */
export type RefreshOutcome = 'ok' | 'lost' | 'unavailable'

interface SurfaceState {
  token: string | null
  refreshPath: string
  inflight: Promise<RefreshOutcome> | null
}

const surfaces: Record<Surface, SurfaceState> = {
  app: { token: null, refreshPath: '/account/refresh', inflight: null },
  admin: { token: null, refreshPath: '/admin/refresh', inflight: null },
}

export const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000'

/** Cookie-carrying endpoints need this header; a cross-site form cannot send it. */
export const CSRF_HEADERS = { 'X-Requested-With': 'builder' }

type Listener = (surface: Surface) => void
const lostListeners = new Set<Listener>()

/** Called when a surface's session can no longer be refreshed (expired, revoked, suspended). */
export function onSessionLost(listener: Listener): () => void {
  lostListeners.add(listener)
  return () => lostListeners.delete(listener)
}

export function setAccessToken(surface: Surface, token: string | null): void {
  surfaces[surface].token = token
}

export function accessToken(surface: Surface): string | null {
  return surfaces[surface].token
}

export function authHeader(surface: Surface): Record<string, string> {
  const token = surfaces[surface].token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** A "view as" tab (§4.5) never refreshes: its token is the viewed member's, for a few minutes. */
let viewingOnly = false
export function setViewingOnly(value: boolean): void {
  viewingOnly = value
}

/** Exchange the refresh cookie for a new access token. One call at a time per surface. */
export function refreshOutcome(surface: Surface): Promise<RefreshOutcome> {
  const state = surfaces[surface]
  if (viewingOnly && surface === 'app') {
    state.token = null
    return Promise.resolve('lost')
  }
  if (state.inflight) return state.inflight
  state.inflight = (async (): Promise<RefreshOutcome> => {
    try {
      const response = await fetch(`${BASE_URL}${state.refreshPath}`, {
        method: 'POST',
        credentials: 'include',
        headers: CSRF_HEADERS,
      })
      if (response.status === 401 || response.status === 403) {
        state.token = null
        return 'lost'
      }
      if (!response.ok) return 'unavailable'
      const body = (await response.json()) as { access_token: string }
      state.token = body.access_token
      return 'ok'
    } catch {
      return 'unavailable'
    } finally {
      state.inflight = null
    }
  })()
  return state.inflight
}

/** True when a fresh access token was obtained. */
export async function refreshSession(surface: Surface): Promise<boolean> {
  return (await refreshOutcome(surface)) === 'ok'
}

export function notifySessionLost(surface: Surface): void {
  surfaces[surface].token = null
  lostListeners.forEach((listener) => listener(surface))
}
