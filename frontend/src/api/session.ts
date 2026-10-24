/**
 * Sign-in state for the two surfaces of the platform: the customer app and the admin console.
 *
 * Access tokens live only in memory (a page reload loses them on purpose); the long-lived refresh
 * token is an httpOnly cookie the browser sends to /account or /admin and page scripts cannot read.
 * When a request gets 401 we refresh once, shared by every request in flight, and retry.
 */

export type Surface = 'app' | 'admin'

interface SurfaceState {
  token: string | null
  refreshPath: string
  inflight: Promise<boolean> | null
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

/** Exchange the refresh cookie for a new access token. One call at a time per surface. */
export function refreshSession(surface: Surface): Promise<boolean> {
  const state = surfaces[surface]
  if (state.inflight) return state.inflight
  state.inflight = (async () => {
    try {
      const response = await fetch(`${BASE_URL}${state.refreshPath}`, {
        method: 'POST',
        credentials: 'include',
        headers: CSRF_HEADERS,
      })
      if (!response.ok) {
        state.token = null
        return false
      }
      const body = (await response.json()) as { access_token: string }
      state.token = body.access_token
      return true
    } catch {
      return false
    } finally {
      state.inflight = null
    }
  })()
  return state.inflight
}

export function notifySessionLost(surface: Surface): void {
  surfaces[surface].token = null
  lostListeners.forEach((listener) => listener(surface))
}
