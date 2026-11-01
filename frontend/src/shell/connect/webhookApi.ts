import { sendRequest } from '../workbench/sendRequest'

/** Calls to the GENERATED project's /webhooks API (admin role). Only the preview origin may be called, no cookies are
 *  sent, and the bearer token is passed per call from React state: it is never stored. Secrets in responses are
 *  returned to the caller once and are not logged or kept here. */
export interface Subscription {
  id: string
  url: string
  description: string
  event_types: string[]
  status: string
  disabled_reason: string | null
  consecutive_failures: number
  secret_version: number
  rotating: boolean
  created_at: string
}
export interface SubscriptionCreated extends Subscription { secret: string }
export interface InboundEndpoint { name: string; has_secret: boolean; secret_version: number | null; rotating: boolean; updated_at: string | null }

export class WebhookApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export interface Conn { origin: string; token: string }

async function call<T>(c: Conn, method: string, path: string, body?: unknown): Promise<T> {
  if (!path.startsWith('/webhooks/')) throw new Error('Refusing a path outside /webhooks')
  const res = await sendRequest({ url: c.origin + path, origin: c.origin, method, body: body === undefined ? undefined : JSON.stringify(body), bearer: c.token })
  let parsed: unknown = null
  try {
    parsed = res.text ? JSON.parse(res.text) : null
  } catch {
    parsed = null
  }
  if (res.status < 200 || res.status >= 300) {
    const msg = (parsed as { message?: unknown } | null)?.message
    const detail = (parsed as { detail?: unknown } | null)?.detail
    throw new WebhookApiError(res.status, typeof msg === 'string' ? msg : typeof detail === 'string' ? detail : `The generated API answered ${res.status}`)
  }
  return parsed as T
}

export const webhookApi = {
  list: (c: Conn) => call<Subscription[]>(c, 'GET', '/webhooks/subscriptions'),
  create: (c: Conn, b: { url: string; event_types: string[]; description: string }) => call<SubscriptionCreated>(c, 'POST', '/webhooks/subscriptions', b),
  rotate: (c: Conn, id: string, overlapHours?: number) =>
    call<SubscriptionCreated>(c, 'POST', `/webhooks/subscriptions/${encodeURIComponent(id)}/rotate`, overlapHours ? { overlap_hours: overlapHours } : {}),
  setEnabled: (c: Conn, id: string, enabled: boolean) => call<Subscription>(c, 'POST', `/webhooks/subscriptions/${encodeURIComponent(id)}/${enabled ? 'enable' : 'disable'}`),
  remove: (c: Conn, id: string) => call<null>(c, 'DELETE', `/webhooks/subscriptions/${encodeURIComponent(id)}`),
  inbound: (c: Conn) => call<InboundEndpoint[]>(c, 'GET', '/webhooks/inbound'),
  setInboundSecret: (c: Conn, name: string, value: string) => call<InboundEndpoint>(c, 'PUT', `/webhooks/inbound/${encodeURIComponent(name)}/secret`, { value }),
}
