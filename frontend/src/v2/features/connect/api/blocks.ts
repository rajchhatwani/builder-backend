import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import { issuesFromDetail } from '../../../../forms/schemaLogic'
import type { PathErrors } from '../../../../forms/types'
import { connectKeys } from './connect'

export const notificationChannels = ['email', 'sms', 'push'] as const
export type Template = { channel: string; subject: string; body: string; html: boolean }
export type NotificationType = {
  name: string; category: string; channels: string[]; variables: string[]; templates: Template[];
  default_enabled: boolean; on_event: string | null; recipient_key_field: string | null; address_fields: Record<string, string>;
}
export type Notifications = {
  enabled: boolean; admin_role: string; types: NotificationType[];
  max_attempts: number; backoff_seconds: number; retention_days: number;
}
export type Inbound = { name: string; tolerance_seconds: number; max_body_bytes: number; dedupe_days: number }
export type Webhooks = {
  enabled: boolean; admin_role: string; events: string[]; inbound: Inbound[];
  max_consecutive_failures: number; timeout_seconds: number; max_payload_bytes: number; allow_http: boolean;
  allowed_ports: number[]; secret_overlap_hours: number;
}

export type ProviderAdapter = { kind: string; name: string; settings: Record<string, string | number | boolean> }
export type Providers = {
  enabled: boolean; admin_role: string; adapters: ProviderAdapter[]; timeout_seconds: number
  max_attempts: number; breaker_failures: number; breaker_reset_seconds: number
}
export type RateBucket = { capacity: number; refill_per_second: number }
export type RateGroup = { name: string; path_prefix: string; methods: string[]; user: RateBucket | null; tenant: RateBucket | null; cost: number }
export type ApiEdge = {
  enabled: boolean
  idempotency: { methods: string[]; ttl_hours: number; max_response_bytes: number } | null
  rate_limits: { user: RateBucket; tenant: RateBucket | null; anonymous: RateBucket; groups: RateGroup[]; read_fail_open: boolean } | null
  quotas: { meter: string; period: string; limit: number; path_prefix: string; methods: string[]; cost: number }[]
  versioning: { default: string; versions: { date: string; note: string }[] } | null
}
export type ApiPlatform = {
  enabled: boolean; roles: string[]; entities: { entity: string; fields: string[]; sandbox: boolean }[]
  rate_limit: string; sandbox_rate_limit: string; key_ttl_days: number
  apps: { name: string; title: string; scopes: string[]; events: string[] }[]
}
export type Blocks = { notifications: Notifications; webhooks: Webhooks; providers: Providers; api_edge: ApiEdge; api_platform: ApiPlatform }
const routeName = (key: BlockName) => key.replaceAll('_', '-')
export type BlockName = keyof Blocks
type BlockRead<T> = { version: number; row_version: number; updated_at: string | null; block: T | null }
type BlockReply<K extends BlockName> = Omit<BlockRead<Blocks[K]>, 'block'> & Record<K, Blocks[K] | null>

const decode = <K extends BlockName>(key: K, data: Record<string, unknown>): BlockRead<Blocks[K]> => {
  const { version, row_version, updated_at, ...blocks } = data as BlockReply<K>
  return { version, row_version, updated_at, block: (blocks as Record<K, Blocks[K] | null>)[key] }
}
const options = { retry: false, retryOnMount: false, staleTime: 15_000 }
export const blockOptions = <K extends BlockName>(id: string, key: K) => queryOptions({
  ...options, queryKey: connectKeys.block(id, key), queryFn: async () => decode(key, await api.getBlock(id, routeName(key))),
})
export const connectIssuesOptions = (id: string) => queryOptions({
  ...options, queryKey: connectKeys.issues(id), queryFn: () => api.getBehaviorIssues(id),
})
export const connectRolesOptions = (id: string) => queryOptions({
  ...options, queryKey: connectKeys.roles(id), queryFn: () => api.getBehaviorRoles(id),
})

export function useBlockWrite<K extends BlockName>(id: string, key: K) {
  const queryClient = useQueryClient()
  const queryKey = connectKeys.block(id, key)
  return useMutation({
    scope: { id: 'connect-block:' + id + ':' + key },
    mutationFn: async ({ block, version }: { block: Blocks[K] | null; version: number }) =>
      decode(key, await api.putBlock(id, routeName(key), { [key]: block, expected_version: version })),
    onSuccess: async data => {
      await queryClient.cancelQueries({ queryKey, exact: true })
      queryClient.setQueryData(queryKey, data)
      await queryClient.invalidateQueries({ queryKey: ['projects', id], predicate: query =>
        !(query.queryKey.length === queryKey.length && queryKey.every((part, index) => part === query.queryKey[index])) })
    },
  })
}

export function blockFieldErrors(error: unknown, key: BlockName): PathErrors {
  const fields: PathErrors = Object.create(null)
  if (!(error instanceof ApiError) || error.status !== 422) return fields
  for (const [path, messages] of Object.entries(issuesFromDetail(error.details))) {
    if (path === key) fields[''] = messages
    if (path.startsWith(key + '.')) fields[path.slice(key.length + 1)] = messages
  }
  for (const item of error.details as unknown[]) {
    if (!item || typeof item !== 'object' || !('message' in item) || typeof item.message !== 'string' ||
      !('path' in item) || typeof item.path !== 'string' || !item.path.startsWith(key + '.')) continue
    const path = item.path.slice(key.length + 1).replace(/\[(\d+)\]/g, '.$1')
    ;(fields[path] ??= []).push(item.message)
  }
  return fields
}
