/**
 * "View as" hand-off (§4.5). An operator starts a session in the admin console; the resulting
 * token opens in a NEW tab named `builder-viewing-<random>`, passed by `postMessage` between the two
 * same-origin windows. It is never put in a URL, localStorage or sessionStorage, and the opener
 * forgets it as soon as it is delivered.
 *
 * The viewing tab has no refresh cookie of its own to use: when its token ends (ten minutes, the
 * operator or the customer ending it, consent withdrawn) it simply stops working.
 */

export const VIEWING_WINDOW = 'builder-viewing'  // prefix; each session gets its own tab name
const READY = 'builder-viewing-ready'
const TOKEN = 'builder-viewing-token'

/** True in the tab the operator's "View as" opened (the name survives reloads of that tab). */
export function isViewingTab(): boolean {
  return window.name.startsWith(VIEWING_WINDOW)
}

/** Operator side. Resolves false if the browser blocked the pop-up or the new tab never answered. */
export function openViewingTab(token: string): Promise<boolean> {
  const target = window.open('#/', `${VIEWING_WINDOW}-${crypto.randomUUID()}`)
  if (!target) return Promise.resolve(false)
  return new Promise((resolve) => {
    const done = (ok: boolean) => {
      window.removeEventListener('message', onMessage)
      window.clearTimeout(timer)
      resolve(ok)
    }
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== target) return
      if ((event.data as { type?: string } | null)?.type !== READY) return
      target.postMessage({ type: TOKEN, token }, window.location.origin)
      done(true)
    }
    const timer = window.setTimeout(() => done(false), 30_000)
    window.addEventListener('message', onMessage)
  })
}

/** Viewing-tab side: say we are ready and wait for the token from the window that opened us. */
export function receiveViewingToken(): Promise<string | null> {
  return new Promise((resolve) => {
    const opener = window.opener as Window | null
    if (!opener) {
      resolve(null)
      return
    }
    const done = (token: string | null) => {
      window.removeEventListener('message', onMessage)
      window.clearInterval(ask)
      window.clearTimeout(timer)
      resolve(token)
    }
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== opener) return
      const data = event.data as { type?: string; token?: unknown } | null
      if (data?.type === TOKEN && typeof data.token === 'string') done(data.token)
    }
    window.addEventListener('message', onMessage)
    // the opener may not be listening yet (it is awaiting this very message); ask until it does
    const ask = window.setInterval(() => opener.postMessage({ type: READY }, window.location.origin), 300)
    opener.postMessage({ type: READY }, window.location.origin)
    const timer = window.setTimeout(() => done(null), 15_000)
  })
}
