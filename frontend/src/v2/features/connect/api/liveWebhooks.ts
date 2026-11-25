import { queryOptions } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import type { PreviewInstance } from '../../../../api/types'
import { BASE_URL } from '../../../../api/session'
import { previewBase } from '../../../../shell/ai/seeItLogic'
import { sendRequest } from '../../../../shell/workbench/sendRequest'
import type { InboundEndpoint, Subscription, SubscriptionCreated } from '../../../../shell/connect/webhookApi'
import { connectKeys } from './connect'

export type { InboundEndpoint, Subscription, PreviewInstance }
export type PreviewCredential = { token: string; bearer?: string; revision: number }
export type LiveSession = { target: PreviewInstance; token: string; bearer: string; key: string }
export type SubscriptionInput = { url: string; event_types: string[]; description: string }
type Delivery = {
  id: string; event_id: string; event_type: string; status: string; attempts: number;
  last_status_code: number | null; last_error: string | null; created_at: string; finished_at: string | null;
}
type Attempt = { attempt: number; outcome: string; status_code: number | null; duration_ms: number; created_at: string }
const options = { retry: false, retryOnMount: false }
const liveOptions = { ...options, gcTime: 0 }
const subPath = (id: string) => '/webhooks/subscriptions/' + encodeURIComponent(id)

export const webhookPreviewsOptions = (id: string) => queryOptions({
  ...options, queryKey: connectKeys.previews(id), queryFn: () => api.listPreviews(id), refetchInterval: 15_000,
})

async function request<T>(session: LiveSession, path: string, method = 'GET', body?: unknown): Promise<T> {
  const preview = session.target
  const expected = '/previews/' + encodeURIComponent(preview.id)
  if (preview.is_preview !== true || !['running', 'sleeping'].includes(preview.state) ||
    (preview.url_path !== expected && preview.url_path !== expected + '/') || !path.startsWith('/webhooks/')) throw new Error('preview_path')
  const base = previewBase(BASE_URL, preview.url_path)
  const mount = new URL(base + '/webhooks/', window.location.origin)
  const url = new URL(base + path, window.location.origin)
  if (url.origin !== mount.origin || !url.pathname.startsWith(mount.pathname) || /\\|%2f|%5c/i.test(url.pathname)) throw new Error('preview_path')
  const reply = await sendRequest({
    url: url.href, origin: url.origin, method, previewToken: session.token, bearer: session.bearer,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let data: unknown
  try { data = reply.text ? JSON.parse(reply.text) : null } catch { data = null }
  if (reply.status < 200 || reply.status >= 300) {
    const error = data as { code?: string; message?: string; detail?: string; error?: { code?: string; message?: string } } | null
    throw new ApiError(reply.status, { code: error?.code ?? error?.error?.code ?? '',
      message: error?.message ?? error?.error?.message ?? (typeof error?.detail === 'string' ? error.detail : ''), details: [] })
  }
  return data as T
}

export function liveKey(id: string, session: LiveSession, ...keys: string[]) {
  return connectKeys.live(id, session.target.id, session.key, ...keys)
}

export const webhookSubscriptionsOptions = (id: string, session: LiveSession) => queryOptions({
  ...liveOptions, queryKey: liveKey(id, session, 'subscriptions'), queryFn: () => request<Subscription[]>(session, '/webhooks/subscriptions'),
})
export const webhookEventsOptions = (id: string, session: LiveSession) => queryOptions({
  ...liveOptions, queryKey: liveKey(id, session, 'events'), queryFn: () => request<string[]>(session, '/webhooks/events'),
})
export const webhookInboundOptions = (id: string, session: LiveSession) => queryOptions({
  ...liveOptions, queryKey: liveKey(id, session, 'inbound'), queryFn: () => request<InboundEndpoint[]>(session, '/webhooks/inbound'),
})
export const webhookSubscriptionOptions = (id: string, session: LiveSession, sub: string) => queryOptions({
  ...liveOptions, queryKey: liveKey(id, session, 'subscription', sub), queryFn: () => request<Subscription>(session, subPath(sub)),
})
export const webhookDeliveriesOptions = (id: string, session: LiveSession, sub: string, limit: number) => queryOptions({
  ...liveOptions, queryKey: liveKey(id, session, 'deliveries', sub, String(limit)),
  queryFn: () => request<Delivery[]>(session, subPath(sub) + '/deliveries?limit=' + limit),
})
export const webhookAttemptsOptions = (id: string, session: LiveSession, delivery: string) => queryOptions({
  ...liveOptions, queryKey: liveKey(id, session, 'attempts', delivery),
  queryFn: () => request<Attempt[]>(session, '/webhooks/deliveries/' + encodeURIComponent(delivery) + '/attempts'),
})

export const createSubscription = (session: LiveSession, input: SubscriptionInput) =>
  request<SubscriptionCreated>(session, '/webhooks/subscriptions', 'POST', input)
export const updateSubscription = (session: LiveSession, id: string, input: SubscriptionInput) =>
  request<Subscription>(session, subPath(id), 'PATCH', input)
export const rotateSubscription = (session: LiveSession, id: string, hours?: number) =>
  request<SubscriptionCreated>(session, subPath(id) + '/rotate', 'POST', hours === undefined ? {} : { overlap_hours: hours })
export const enableSubscription = (session: LiveSession, id: string) => request<Subscription>(session, subPath(id) + '/enable', 'POST')
export const disableSubscription = (session: LiveSession, id: string) => request<Subscription>(session, subPath(id) + '/disable', 'POST')
export const deleteSubscription = (session: LiveSession, id: string) => request<null>(session, subPath(id), 'DELETE')
export const writeInboundSecret = (session: LiveSession, name: string, value: string) =>
  request<InboundEndpoint>(session, '/webhooks/inbound/' + encodeURIComponent(name) + '/secret', 'PUT', { value })

export const liveErrorCode = (error: unknown) => error instanceof ApiError ? error.code : undefined
