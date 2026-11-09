import { authHeader, refreshSession, BASE_URL } from '../api/session'
import { parseEnvelope, type RealtimeEvent } from './eventRouting'
import { STABLE_MS, parseRetryAfter, reconnectDelay } from './backoff'
import { createSseParser } from './sseParser'

export type StreamStatus = 'connecting' | 'live' | 'reconnecting' | 'stopped'
export interface PresenceUser { user_id: string; display: string; where: string }

export interface StreamOptions {
  projectId: string
  onEvent: (ev: RealtimeEvent) => void
  onPresence?: (users: PresenceUser[]) => void
  onStatus?: (s: StreamStatus) => void
  doFetch?: typeof fetch
  headers?: () => Record<string, string>
  refresh?: () => Promise<boolean>
  wait?: (ms: number, signal: AbortSignal) => Promise<void>
  rand?: () => number
  now?: () => number
}

const defaultWait = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => { clearTimeout(t); resolve() }, { once: true })
  })

/** Authenticated SSE client (fetch streaming: EventSource cannot send Authorization). Resumes with Last-Event-ID,
 *  dedupes by id, backs off with jitter (honouring Retry-After) and stops for good on 401 (after one refresh try), 403, 404. */
export function connectProjectEvents(opts: StreamOptions): { close: () => void; lastId: () => number | null } {
  const doFetch = opts.doFetch ?? ((...a: Parameters<typeof fetch>) => fetch(...a))
  const headers = opts.headers ?? (() => authHeader('app'))
  const refresh = opts.refresh ?? (() => refreshSession('app'))
  const wait = opts.wait ?? defaultWait
  const rand = opts.rand ?? Math.random
  const now = opts.now ?? Date.now
  const ctl = new AbortController()
  let lastId: number | null = null
  let attempt = 0
  let refreshed = false

  const run = async () => {
    while (!ctl.signal.aborted) {
      opts.onStatus?.(attempt === 0 && lastId === null ? 'connecting' : 'reconnecting')
      let retryAfter: number | null = null
      let openedAt = 0
      try {
        const h: Record<string, string> = { ...headers(), Accept: 'text/event-stream' }
        if (lastId !== null) h['Last-Event-ID'] = String(lastId)
        const res = await doFetch(`${BASE_URL}/projects/${encodeURIComponent(opts.projectId)}/events/stream`, {
          headers: h, credentials: 'include', cache: 'no-store', signal: ctl.signal,
        })
        if (res.status === 401) {
          if (!refreshed && (await refresh())) { refreshed = true; continue }
          break
        }
        if (res.status === 403 || res.status === 404) break
        if (res.status === 429) retryAfter = parseRetryAfter(res.headers.get('Retry-After'))
        else if (!res.ok || !res.body) throw new Error(`status ${res.status}`)
        else {
          refreshed = false
          openedAt = now()
          opts.onStatus?.('live')
          const parser = createSseParser()
          const reader = res.body.getReader()
          const dec = new TextDecoder()
          for (;;) {
            const { done, value } = await reader.read()
            if (done) break
            for (const frame of parser.push(dec.decode(value, { stream: true }))) {
              const ev = parseEnvelope(frame)
              if (!ev) continue
              if (ev.type === 'presence') {
                const users = ev.data.users
                if (Array.isArray(users)) opts.onPresence?.(users.filter((u): u is PresenceUser => typeof u === 'object' && u !== null && typeof (u as PresenceUser).user_id === 'string'))
                continue
              }
              if (ev.type === 'resync') { if (ev.id !== null) lastId = ev.id; opts.onEvent(ev); continue }
              if (ev.id !== null) {
                if (lastId !== null && ev.id <= lastId) continue
                lastId = ev.id
              }
              opts.onEvent(ev)
            }
          }
        }
      } catch {
        if (ctl.signal.aborted) break
      }
      if (ctl.signal.aborted) break
      if (openedAt && now() - openedAt >= STABLE_MS) attempt = 0
      opts.onStatus?.('reconnecting')
      await wait(reconnectDelay(attempt, retryAfter, rand), ctl.signal)
      attempt++
    }
    opts.onStatus?.('stopped')
  }
  void run()
  return { close: () => ctl.abort(), lastId: () => lastId }
}
