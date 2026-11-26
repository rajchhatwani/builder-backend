import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { api, ApiError } from '../../../../api/client'
import { BASE_URL } from '../../../../api/session'
import type { PreviewInstance } from '../../../../api/types'
import { previewBase } from '../../../../shell/ai/seeItLogic'
import { operateKeys } from './operate'
import type { OperateProps } from './operate'

type Credential = { token: string; bearer?: string; revision: number }
export type LiveProps = OperateProps & {
  credentials?: Record<string, Credential>
  renderIdentity?: (preview: PreviewInstance, credential: Credential) => ReactNode
}
export type Session = { projectId: string; target: PreviewInstance; token: string; bearer: string; scope: string }
export type Page<T> = { items: T[]; total: number; limit: number; offset: number }
type Params = Record<string, string | number | boolean | undefined>
type Method = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
type Endpoint = `/${'ledger/' | 'invoices' | 'payouts' | 'reconciliation/' | 'booking/' | 'location/' | 'geo/' | 'matching/' | 'prediction/' | 'ai/documents' | 'ai/agents' | 'ai/usage' | 'ai/calls' | 'ai/knowledge/' | 'ai/evals/' | 'auth/me' | 'documents'}${string}`

const previewMount = (id: string) => '/previews/' + encodeURIComponent(id)
export function usablePreview(projectId: string, preview: PreviewInstance) {
  const mount = previewMount(preview.id)
  return preview.project_id === projectId && preview.is_preview === true && ['running', 'sleeping'].includes(preview.state)
    && [mount, mount + '/'].includes(preview.url_path)
}
export const previewOptions = (id: string) => queryOptions({
  queryKey: operateKeys.item(id, 'previews'), queryFn: () => api.listPreviews(id),
  retry: false, retryOnMount: false, refetchInterval: 15_000,
})
export const bookingRulesOptions = (id: string) => queryOptions({
  queryKey: operateKeys.item(id, 'booking-rules'), queryFn: () => api.getBlock(id, 'packs'),
  retry: false, retryOnMount: false,
})
export function useBookingRulesWrite(id: string) {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: ({ packs, version }: { packs: Record<string, unknown>; version: number }) =>
      api.putBlock(id, 'packs', { packs, expected_version: version }),
    onSuccess: async reply => {
      const key = bookingRulesOptions(id).queryKey
      await cache.cancelQueries({ queryKey: key, exact: true })
      cache.setQueryData(key, reply)
      await cache.invalidateQueries({ queryKey: ['projects', id], predicate: query =>
        query.queryKey.length !== key.length || query.queryKey.some((part, index) => part !== key[index]) })
    },
  })
}
export const segment = encodeURIComponent
const badResponse = () => new ApiError(200, { code: 'bad_response', message: '', details: [] })

// Tokenize strings as well as integers so keys inside quoted user content are never rewritten.
export function parseRuntimeJson(source: string): unknown {
  return JSON.parse(source.replace(/("(?:[^"\\]|\\.)*")(?:\s*:\s*(-?\d+)(?=\s*[,}]))?/g, (chunk, key: string, integer?: string) =>
    integer !== undefined && ((key.endsWith('_minor"') || key.endsWith('_micro_usd"')) || key === '"seq"')
      ? key + ':' + JSON.stringify(integer) : chunk))
}
async function runtimeFetch(session: Session, path: Endpoint, method: Method, body?: unknown, params?: Params, signal?: AbortSignal, accept = 'application/json') {
  if (!usablePreview(session.projectId, session.target)) throw badResponse()
  const mount = new URL(previewBase(BASE_URL, session.target.url_path) + '/', window.location.origin)
  const url = new URL(mount.href + path.slice(1))
  if (url.origin !== mount.origin || !url.pathname.startsWith(mount.pathname) || /\\|%2f|%5c/i.test(url.pathname)) throw badResponse()
  for (const [key, value] of Object.entries(params ?? {})) if (value !== undefined && value !== '') url.searchParams.set(key, String(value))
  return fetch(url.href, {
    method, signal, credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer',
    headers: { Accept: accept, 'X-Preview-Token': session.token, Authorization: 'Bearer ' + session.bearer,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}
async function readRuntimeResponse(response: Response) {
  const raw = await response.text()
  let value: unknown
  try { value = raw ? parseRuntimeJson(raw) : null } catch { value = null }
  if (!response.ok) {
    const error = value as { code?: string; message?: string; detail?: unknown; error?: { code?: string; message?: string }; details?: unknown[] } | null
    throw new ApiError(response.status, { code: error?.code ?? error?.error?.code ?? '',
      message: error?.message ?? error?.error?.message ?? (typeof error?.detail === 'string' ? error.detail : ''),
      details: error?.details ?? (Array.isArray(error?.detail) ? error.detail : []),
    })
  }
  if (value == null && response.status !== 204) throw badResponse()
  return value
}
export async function runtimeRequest<T>(session: Session, path: Endpoint, method: Method, body?: unknown, params?: Params, signal?: AbortSignal) {
  const response = await runtimeFetch(session, path, method, body, params, signal)
  const value = await readRuntimeResponse(response)
  return { data: value as T, replayed: response.headers.get('Idempotent-Replayed') === 'true' ||
    (method === 'POST' && response.status === 200 && ([
      '/ledger/transactions', '/payouts/run', '/booking/bookings', '/reconciliation/runs',
    ].includes(path) || path.endsWith('/payments') || path.endsWith('/reverse'))) }
}
function validRuntimeRead(path: Endpoint, value: unknown): boolean {
  if (value == null || typeof value !== 'object') return false
  if (path === '/payouts/totals' || path === '/documents' || path === '/ai/evals/suites') return Array.isArray(value)
  if (path === '/ai/agents' || path === '/ai/agents/stats') {
    const registry = value as { agents?: unknown; actions?: unknown }
    return Array.isArray(registry.agents) && (path.endsWith('/stats') || Array.isArray(registry.actions))
  }
  if (path === '/auth/me') {
    const identity = value as { id?: unknown; roles?: unknown }
    return typeof identity.id === 'string' && Array.isArray(identity.roles) && identity.roles.every(role => typeof role === 'string')
  }
  if (path === '/ai/usage') {
    const usage = value as { period?: unknown; period_start?: unknown }
    return typeof usage.period === 'string' && typeof usage.period_start === 'string'
  }
  if (path.startsWith('/ai/evals/runs/')) return Array.isArray((value as { results?: unknown }).results)
  if (path.startsWith('/ai/agents/runs/')) return Array.isArray((value as { proposals?: unknown }).proposals)
  const arrays = path === '/ledger/balances' ? ['items', 'totals'] :
    path === '/invoices/aging' ? ['currencies'] :
    path.endsWith('/results') ? ['matched', 'unmatched_lines', 'unmatched_entries'] :
    path.endsWith('/availability') ? ['slots'] :
    path.endsWith('/history') || path.endsWith('/entries') ||
      ['/ledger/accounts', '/ledger/transactions', '/invoices', '/payouts', '/reconciliation/runs', '/booking/resources',
        '/booking/bookings', '/geo/places', '/geo/geofences', '/location/positions', '/geo/events', '/geo/places/nearest', '/geo/places/within', '/matching/assignments', '/prediction/records',
        '/ai/documents', '/ai/agents/proposals', '/ai/agents/runs', '/ai/calls', '/ai/knowledge/sources', '/ai/evals/runs'].includes(path) ? ['items'] : []
  const record = value as Record<string, unknown>
  return !Array.isArray(value) && arrays.every(field => Array.isArray(record[field]))
}
export const liveKey = (session: Session) => operateKeys.item(session.projectId, 'live', session.target.id, session.scope)
export function liveRead<T>(session: Session, path: Endpoint, params: Params = {}, enabled = true, poll?: number) {
  return queryOptions({
    queryKey: [...liveKey(session), path, params], retry: false, retryOnMount: false, gcTime: 0, enabled, refetchInterval: poll,
    queryFn: async ({ signal }) => {
      const { data } = await runtimeRequest<T>(session, path, 'GET', undefined, params, signal)
      if (!validRuntimeRead(path, data)) throw badResponse()
      return data
    },
  })
}
export function useRuntimeWrite<B, T>(session: Session, path: Endpoint, method: Exclude<Method, 'GET'> = 'POST', refresh = true) {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: (body: B) => runtimeRequest<T>(session, path, method, body),
    onSuccess: () => refresh ? cache.invalidateQueries({ queryKey: liveKey(session) }) : undefined,
  })
}
export const runtimeError = (error: unknown) => error instanceof ApiError ? { code: error.code, message: error.message, details: error.details } : undefined
export const runtimeStatus = (error: unknown) => error instanceof ApiError ? error.status : undefined
export const runtimeMessage = (error: unknown) => error instanceof ApiError && error.status < 500 ? error.message : ''

export const allLedgerAccounts = <T>(session: Session, enabled: boolean) => queryOptions({
  queryKey: [...liveKey(session), 'all-ledger-accounts'], enabled, gcTime: 0, retry: false, retryOnMount: false,
  queryFn: async ({ signal }) => {
    const items: T[] = []
    const size = 200
    for (let page = 0; page < 100; page++) {
      const { data } = await runtimeRequest<Page<T>>(session, '/ledger/accounts', 'GET', undefined, { limit: size, offset: page * size }, signal)
      if (!validRuntimeRead('/ledger/accounts', data)) throw badResponse()
      items.push(...data.items)
      if (data.items.length < size || items.length >= data.total) return { items, truncated: false }
    }
    return { items, truncated: true }
  },
})

export function useRuntimePdf(session: Session, template: string, bound: boolean) {
  return useMutation({
    mutationFn: async ({ record, data }: { record?: string; data?: Record<string, unknown> }) => {
      const path = bound ? `/documents/${segment(template)}/records/${segment(record ?? '')}` as const : `/documents/${segment(template)}/render` as const
      const response = await runtimeFetch(session, path, 'POST', bound ? undefined : { data }, undefined, undefined, 'application/pdf')
      if (!response.ok) await readRuntimeResponse(response)
      if (!response.headers.get('content-type')?.startsWith('application/pdf')) throw badResponse()
      return response.blob()
    },
  })
}
