import { queryOptions } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import { BASE_URL } from '../../../../api/session'
import { previewBase } from '../../../../shell/ai/seeItLogic'
import type { PreviewInstance } from '../../../../api/types'
import { connectKeys } from './connect'
import type { LiveSession } from './liveWebhooks'

export type Catalogue = {
  entities: { entity: string; plural_path: string; fields: string[]; sandbox: boolean }[]
  rate_limit: string; sandbox_rate_limit: string; key_ttl_days: number
}
export type PlatformKey = {
  id: string; name: string; prefix: string; kind: string; app: string | null; environment: string; scopes: string[]
  created_at: string; expires_at: string; revoked_at: string | null; last_used_at: string | null
  status: 'active' | 'revoked' | 'expired'
}
export type PlatformApp = {
  name: string; title: string; scopes: string[]; events: string[]; installed: boolean
  installation_id: string | null; granted_scopes: string[]; installed_at: string | null
}
type Audit = { id: string; at: string; actor: string; action: string; target: string | null; detail: Record<string, unknown> }
export type CreateKey = { name: string; scopes: string[]; environment: 'prod' | 'sandbox'; ttl_days: number | null }
type Created = Pick<PlatformKey, 'id' | 'name' | 'prefix' | 'environment' | 'scopes' | 'expires_at' | 'created_at'> & { key: string }
type Installed = { installation_id: string; app: string; granted_scopes: string[]; token: string; signing_secret: string }
const options = { retry: false, retryOnMount: false, gcTime: 0 }
export const auditSize = 50

export const platformPreviewsOptions = (id: string) => queryOptions({
  queryKey: connectKeys.previews(id), queryFn: () => api.listPreviews(id), retry: false, retryOnMount: false, refetchInterval: 15_000,
})

export function isPlatformPreview(id: string, preview: PreviewInstance) {
  const expected = '/previews/' + encodeURIComponent(preview.id)
  return preview.project_id === id && preview.is_preview === true && ['running', 'sleeping'].includes(preview.state)
    && (preview.url_path === expected || preview.url_path === expected + '/')
}

async function request<T>(session: LiveSession, path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const base = previewBase(BASE_URL, session.target.url_path)
  const mount = new URL(base + '/platform/', window.location.origin)
  const url = new URL(base + '/platform/' + path, window.location.origin)
  if (url.origin !== mount.origin || !url.pathname.startsWith(mount.pathname) || /\\|%2f|%5c/i.test(url.pathname)) throw new Error('preview_path')
  const reply = await fetch(url.href, {
    method, signal, credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer',
    headers: { Accept: 'application/json', 'X-Preview-Token': session.token, Authorization: 'Bearer ' + session.bearer,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await reply.json().catch(() => null)
  if (!reply.ok) throw new ApiError(reply.status, {
    code: data?.code ?? data?.error?.code ?? '',
    message: data?.message ?? data?.error?.message ?? (typeof data?.detail === 'string' ? data.detail : ''), details: [],
  })
  if (data == null) throw new ApiError(reply.status, { code: 'bad_response', message: '', details: [] })
  return data
}

export const platformKey = (id: string, session: LiveSession, ...parts: string[]) =>
  connectKeys.live(id, session.target.id, session.key, 'platform', ...parts)

export const catalogueOptions = (id: string, session: LiveSession) => queryOptions({
  ...options, queryKey: platformKey(id, session, 'catalogue'), queryFn: async ({ signal }) => {
    const data = await request<Catalogue>(session, 'catalogue', 'GET', undefined, signal)
    if (!Array.isArray(data.entities)) throw new ApiError(200, { code: 'bad_response', message: '', details: [] })
    return data
  },
})
const list = async <T>(session: LiveSession, path: string, signal: AbortSignal) => {
  const data = await request<T[]>(session, path, 'GET', undefined, signal)
  if (!Array.isArray(data)) throw new ApiError(200, { code: 'bad_response', message: '', details: [] })
  return data
}
export const platformKeysOptions = (id: string, session: LiveSession) => queryOptions({
  ...options, queryKey: platformKey(id, session, 'keys'), queryFn: ({ signal }) => list<PlatformKey>(session, 'keys', signal),
})
export const platformAppsOptions = (id: string, session: LiveSession) => queryOptions({
  ...options, queryKey: platformKey(id, session, 'apps'), queryFn: ({ signal }) => list<PlatformApp>(session, 'apps', signal),
})
export const platformAuditOptions = (id: string, session: LiveSession, page: number) => queryOptions({
  ...options, queryKey: platformKey(id, session, 'audit', String(page)),
  queryFn: ({ signal }) => list<Audit>(session, 'audit?limit=' + auditSize + '&offset=' + (page - 1) * auditSize, signal),
})

export const createPlatformKey = (session: LiveSession, body: CreateKey) => request<Created>(session, 'keys', 'POST', body)
export const revokePlatformKey = (session: LiveSession, id: string) =>
  request<PlatformKey>(session, 'keys/' + encodeURIComponent(id) + '/revoke', 'POST')
export const installPlatformApp = (session: LiveSession, name: string, scopes: string[]) =>
  request<Installed>(session, 'apps/' + encodeURIComponent(name) + '/install', 'POST', { scopes })
export const uninstallPlatformApp = (session: LiveSession, name: string) =>
  request<{ installation_id: string; status: 'uninstalled' }>(session, 'apps/' + encodeURIComponent(name) + '/uninstall', 'POST')

export const platformErrorCode = (error: unknown) => error instanceof ApiError ? error.code : undefined
