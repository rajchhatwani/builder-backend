import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from '../../../../api/client'
import type { AuthConfig, AuthConfigUpdate, KeycloakConfig, KeycloakWrite, SuiteRef } from '../../../../api/types'
import type { ValidationIssue } from '../../../validators'

const options = { retry: false, retryOnMount: false, staleTime: 30_000 }
export const secureKeys = {
  project: (id: string) => ['projects', id] as const,
  section: (id: string, section: string) => [...secureKeys.project(id), section] as const,
  impact: (id: string, action: string) => [...secureKeys.section(id, 'keycloak'), 'impact', action] as const,
}
async function optional<T>(read: () => Promise<T>) {
  try { return await read() } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}
export type Migration = {
  state: 'legacy_read_only' | 'dual' | 'hub_only'
  legacy_issuer: string
  dual_until: string | null
  window_started_at: string | null
}
export type SavedSuite = SuiteRef & { migration?: Migration | null }
const readAuth = (id: string) => optional(() => api.getAuthConfig(id) as Promise<AuthConfig & { suite: SavedSuite | null }>)
export const authOptions = (id: string) => queryOptions({
  ...options, queryKey: secureKeys.section(id, 'auth'),
  queryFn: () => readAuth(id),
})
export const keycloakOptions = (id: string) => queryOptions({
  ...options, queryKey: secureKeys.section(id, 'keycloak'), queryFn: () => optional(() => api.getKeycloak(id)),
})
export const fieldsOptions = (id: string, page: number) => queryOptions({
  ...options, queryKey: [...secureKeys.section(id, 'auth-fields'), page],
  queryFn: () => api.listAuthCustomFields(id, fieldPageSize, (page - 1) * fieldPageSize),
})
export const fieldPageSize = 10
export const impactOptions = (id: string, action: 'enable' | 'disable') => queryOptions({
  ...options, staleTime: 0, queryKey: secureKeys.impact(id, action),
  queryFn: () => api.keycloakImpact(id, action),
})
export const sourceOptions = (id: string) => queryOptions({
  ...options, queryKey: secureKeys.section(id, 'keycloak-sources'),
  async queryFn() {
    const [project, projects] = await Promise.all([api.getProject(id), api.listProjects(200)])
    const candidates = projects.items.filter(item => item.id !== id && item.organization_id === project.organization_id)
    const reads = await Promise.allSettled(candidates.map(async item => {
      const config = await api.getKeycloak(item.id)
      return config.mode === 'own' ? { id: item.id, name: item.name, realm: config.realm } : null
    }))
    return reads.flatMap(read => read.status === 'fulfilled' && read.value ? [read.value] : [])
  },
})
export const projectInfoOptions = (id: string) => queryOptions({
  ...options, queryKey: secureKeys.section(id, 'metadata'), queryFn: () => api.getProject(id),
})
export const projectIssuesOptions = (id: string) => queryOptions({
  ...options, queryKey: secureKeys.section(id, 'status'), queryFn: () => api.getProjectStatus(id),
})
export const checksOptions = (id: string) => queryOptions({
  ...options, queryKey: secureKeys.section(id, 'auth-checks'), queryFn: () => api.validateProject(id),
})
export const securityApi = {
  setup: (id: string) => api.createAuthConfig(id, { email_magic_link_enabled: false, sms_otp_enabled: false }),
  update: (id: string, data: AuthConfigUpdate, confirm = false) => api.updateAuthConfig(id, data, confirm),
  createField: api.createAuthCustomField,
  updateField: api.updateAuthCustomField,
  deleteField: api.deleteAuthCustomField,
  saveKeycloak: api.putKeycloak,
  switchKeycloak: api.switchKeycloak,
}
export const keycloakDefaults: KeycloakWrite = {
  mode: 'own', realm: null, api_client_id: null, web_client_id: null, redirect_uris: [],
  password_min_length: 12, mfa: 'optional', session_idle_minutes: 30, session_max_hours: 10,
  audit_retention_days: 90, identity_providers: [], source_project_id: null,
}
export function useSecureMutation<T, V>(id: string, write: (value: V) => Promise<T>, target?: string) {
  const query = useQueryClient()
  return useMutation({
    mutationFn: write,
    async onSuccess() {
      await query.invalidateQueries({ queryKey: target ? secureKeys.section(id, target) : secureKeys.project(id),
        predicate: item => item.queryKey[2] !== 'auth-checks' })
    },
  })
}
export function statusOf(error: unknown) {
  return error instanceof ApiError ? error.status : undefined
}
export function codeOf(error: unknown) {
  return error instanceof ApiError ? error.code : undefined
}
export function fieldErrors(error: unknown, aliases: Record<string, string> = {}): Record<string, ValidationIssue> {
  if (!(error instanceof ApiError) || error.status !== 422) return {}
  return Object.fromEntries((error.details ?? []).flatMap((detail: unknown) => {
    if (!detail || typeof detail !== 'object' || !('loc' in detail) || !Array.isArray(detail.loc) ||
      !('msg' in detail) || typeof detail.msg !== 'string') return []
    const path = detail.loc.filter(part => part !== 'body').join('.')
    return path ? [[aliases[path] ?? path, { key: 'secure.fieldError', values: { message: detail.msg } }]] : []
  }))
}

export function suiteKeycloakBody(current: KeycloakConfig | null, realm: string): KeycloakWrite {
  const saved = current ?? keycloakDefaults
  const { api_client_id, web_client_id, redirect_uris, password_min_length, mfa, session_idle_minutes,
    session_max_hours, audit_retention_days, identity_providers } = saved
  return { mode: 'shared', realm, api_client_id, web_client_id, redirect_uris, password_min_length, mfa,
    session_idle_minutes, session_max_hours, audit_retention_days, identity_providers, source_project_id: null }
}
export async function saveSuite(id: string, base: SavedSuite | null, suite: SavedSuite | null) {
  const current = await readAuth(id)
  const latest = current?.suite ?? null
  if (JSON.stringify(base) !== JSON.stringify(latest) || (!suite && latest?.migration && latest.migration.state !== 'hub_only')) {
    throw new ApiError(409, { code: 'suite_changed', message: '', details: [] })
  }
  return securityApi.update(id, { suite })
}
