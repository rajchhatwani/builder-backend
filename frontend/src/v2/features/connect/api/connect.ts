import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import { BASE_URL } from '../../../../api/session'
import type { MemberRole, PaymentsImpact, PaymentsWrite, SpecForPolicies, StorageWrite } from '../../../../api/types'
import type { ValidationIssue } from '../../../validators'

export type { MemberRole, PaymentsConfig, PaymentsPayable, PaymentsSizing, PaymentsWrite, StorageConfig, StorageWrite } from '../../../../api/types'
export type { ValidationIssue as ProjectIssue } from '../../../../api/types'
export type Impact = PaymentsImpact
export type SwitchAction = 'enable' | 'disable'
export type SettingsKind = 'payments' | 'storage'
export type ConnectRole = { role?: MemberRole; rolePending?: boolean; roleError?: boolean; retryRole?: () => void }
export type ConnectProps = ConnectRole & { projectId: string }
export type ConnectSpec = {
  events?: { enabled: boolean } | null
  jobs?: { enabled: boolean; jobs?: { name: string }[] } | null
  providers?: { enabled: boolean } | null
  tenancy?: { mode?: string } | null
  state_machines?: { entity: string }[]
  relations?: { kind: string; to_entity: string; to_name: string }[]
  auth: (NonNullable<SpecForPolicies['auth']> & { enabled: boolean }) | null
  entities: { name: string; fields: {
    name: string; type: string; required: boolean; min_value?: number | null; max_length?: number | null; enum_values?: string[] | null
  }[] }[]
}

const project = (id: string) => ['projects', id] as const
const settings = (id: string, kind: SettingsKind) => [...project(id), 'connect', kind] as const
export const connectKeys = {
  settings,
  block: (id: string, key: string) => [...project(id), 'connect', 'block', key] as const,
  issues: (id: string) => [...project(id), 'connect', 'issues'] as const,
  roles: (id: string) => [...project(id), 'connect', 'roles'] as const,
  previews: (id: string) => [...project(id), 'connect', 'previews'] as const,
  live: (id: string, preview: string, session: string, ...key: string[]) => [...project(id), 'connect', 'live', preview, session, ...key] as const,
  spec: (id: string) => [...project(id), 'connect', 'spec'] as const,
  status: (id: string) => [...project(id), 'status'] as const,
  members: (id: string) => [...project(id), 'members'] as const,
  tokens: (id: string) => [...project(id), 'connect', 'tokens'] as const,
  plan: (slug: string) => ['connect', 'plan', slug] as const,
}
const options = { retry: false, retryOnMount: false, staleTime: 15_000 }
export const statusOf = (error: unknown) => error instanceof ApiError ? error.status : undefined

async function readSettings<T>(read: () => Promise<T>, kind: SettingsKind) {
  try { return await read() } catch (error) {
    if (error instanceof ApiError && error.status === 404 && error.message === kind + ' settings not found') return null
    throw error
  }
}

export const paymentsOptions = (id: string) => queryOptions({
  ...options, queryKey: settings(id, 'payments'), queryFn: () => readSettings(() => api.getPayments(id), 'payments'),
})
export const storageOptions = (id: string) => queryOptions({
  ...options, queryKey: settings(id, 'storage'), queryFn: () => readSettings(() => api.getStorage(id), 'storage'),
})
export const sizingOptions = (id: string, enabled: boolean) => queryOptions({
  ...options, queryKey: [...settings(id, 'payments'), 'sizing'], queryFn: () => api.paymentsSizing(id), enabled,
})
export const impactOptions = (id: string, kind: SettingsKind, action: SwitchAction, enabled: boolean) => queryOptions({
  ...options, staleTime: 0, queryKey: [...settings(id, kind), 'impact', action], enabled,
  queryFn: () => kind === 'payments' ? api.paymentsImpact(id, action) : api.storageImpact(id, action),
})
export const specOptions = (id: string) => queryOptions({
  ...options, queryKey: connectKeys.spec(id), queryFn: async () => await api.getSpecJson(id) as ConnectSpec,
})
export const statusOptions = (id: string) => queryOptions({
  ...options, staleTime: 30_000, queryKey: connectKeys.status(id), queryFn: () => api.getProjectStatus(id),
})
export const membersOptions = (id: string) => queryOptions({
  ...options, queryKey: connectKeys.members(id), queryFn: () => api.listMembers(id),
})
export const pinnedTokensOptions = (id: string, owner: boolean) => queryOptions({
  ...options, queryKey: connectKeys.tokens(id), queryFn: () => api.listProjectTokens(id), enabled: owner,
})
export const planOptions = (slug: string) => queryOptions({
  ...options, queryKey: connectKeys.plan(slug), queryFn: () => api.orgPlan(slug), enabled: Boolean(slug),
})
export const mcpEndpoint = () => new URL(BASE_URL, window.location.origin).href.replace(/\/$/, '') + '/mcp'

export type ConfigWrite<T> = { settings: T } | { action: SwitchAction }

function useSettingsWrite<T, R>(id: string, kind: SettingsKind, write: (input: ConfigWrite<T>) => Promise<R>) {
  const client = useQueryClient()
  return useMutation({
    scope: { id: 'connect-settings:' + id + ':' + kind },
    mutationFn: write,
    onSuccess: async result => {
      const key = settings(id, kind)
      await client.cancelQueries({ queryKey: key, exact: true })
      client.setQueryData(key, result)
      await client.invalidateQueries({ queryKey: project(id), predicate: query => !(query.queryKey.length === key.length && query.queryKey.every((part, index) => part === key[index])) })
    },
  })
}

export function usePaymentsWrite(id: string) {
  return useSettingsWrite(id, 'payments', (input: ConfigWrite<PaymentsWrite>) =>
    'action' in input ? api.switchPayments(id, input.action) : api.putPayments(id, input.settings))
}

export function useStorageWrite(id: string) {
  return useSettingsWrite(id, 'storage', (input: ConfigWrite<StorageWrite>) =>
    'action' in input ? api.switchStorage(id, input.action) : api.putStorage(id, input.settings))
}

export type AccessAction = { user: string; enabled: boolean } | { token: string }
export function useIntegrationWrite(id: string) {
  const client = useQueryClient()
  return useMutation({
    scope: { id: 'project-members:' + id },
    mutationFn: async (action: AccessAction) => {
      if ('user' in action) await api.setMemberMcp(id, action.user, action.enabled)
      else await api.revokeProjectToken(id, action.token)
    },
    onSuccess: async (_, action) => {
      await client.invalidateQueries({ queryKey: 'user' in action ? connectKeys.members(id) : connectKeys.tokens(id) })
      if ('token' in action) await invalidateTokens(client)
    },
  })
}

function invalidateTokens(client: ReturnType<typeof useQueryClient>) {
  return client.invalidateQueries({ predicate: ({ queryKey }) =>
    queryKey[0] === 'connect' && queryKey[1] === 'plan' || queryKey[0] === 'entry' && queryKey[1] === 'account-tokens' })
}

export function useCreatePinnedToken(id: string, reveal: (token: string) => void) {
  const client = useQueryClient()
  return useMutation({
    gcTime: 0,
    mutationFn: async (input: Omit<Parameters<typeof api.createApiToken>[0], 'project_id'>) => {
      const result = await api.createApiToken({ ...input, project_id: id })
      reveal(result.token)
    },
    onSuccess: async () => {
      await Promise.all([client.invalidateQueries({ queryKey: connectKeys.tokens(id) }), invalidateTokens(client)])
    },
  })
}

export function fieldErrors(error: unknown): Record<string, ValidationIssue> {
  if (!(error instanceof ApiError) || error.status !== 422) return {}
  return Object.fromEntries(error.details.flatMap(detail => {
    if (!detail || typeof detail !== 'object' || !('loc' in detail) || !Array.isArray(detail.loc) ||
      !('msg' in detail) || typeof detail.msg !== 'string') return []
    const path = detail.loc.filter(part => part !== 'body' && typeof part !== 'number').join('.')
    return path ? [[path, { key: 'connect.fieldError', values: { message: detail.msg } }]] : []
  }))
}

export function errorText(error: unknown) {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return error.message
}
