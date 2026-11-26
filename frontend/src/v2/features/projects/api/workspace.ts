import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, onOrgLocked, onOrgMfaRequired, onQuotaExceeded } from '../../../../api/client'
import type { MemberRole, OrgLockedDetail, OrgMfaDetail, QuotaDetail } from '../../../../api/types'
import type { ValidationIssue } from '../../../validators'
import { projectKeys } from './status'

export type { MemberRole }
export type WorkspaceNotice =
  | { kind: 'quota'; detail: QuotaDetail | null }
  | { kind: 'locked'; detail: OrgLockedDetail | null }
  | { kind: 'mfa'; detail: OrgMfaDetail | null }
export function subscribeWorkspaceNotices(listener: (notice: WorkspaceNotice) => void) {
  const unsubscribe = [
    onQuotaExceeded((_, detail) => listener({ kind: 'quota', detail })),
    onOrgLocked((_, detail) => listener({ kind: 'locked', detail })),
    onOrgMfaRequired((_, detail) => listener({ kind: 'mfa', detail })),
  ]
  return () => unsubscribe.forEach(stop => stop())
}

const options = { staleTime: 15_000, retry: false, retryOnMount: false }
export const projectOptions = (id: string) => queryOptions({
  ...options, queryKey: [...projectKeys.project(id), 'metadata'], queryFn: () => api.getProject(id), enabled: Boolean(id),
})
export const membersOptions = (id: string) => queryOptions({
  ...options, queryKey: [...projectKeys.project(id), 'members'], queryFn: () => api.listMembers(id), enabled: Boolean(id),
})
export function useWorkspaceRole(id: string, user: string) {
  const members = useQuery(membersOptions(id))
  const role = Array.isArray(members.data) ? members.data.find(member => member.user_id === user)?.role : undefined
  return { members, role }
}

export function workspaceError(error: unknown) {
  return error instanceof ApiError ? error.code : undefined
}

export function shareFieldErrors(error: unknown): Record<string, ValidationIssue> {
  if (!(error instanceof ApiError)) return {}
  if (error.code === 'user_unavailable') return { email: unavailableEmail }
  if (error.status !== 422) return {}
  return Object.fromEntries(error.details.flatMap(detail => {
    if (!detail || typeof detail !== 'object' || !('loc' in detail) || !Array.isArray(detail.loc)
      || !('msg' in detail) || typeof detail.msg !== 'string') return []
    const [scope, field] = detail.loc
    return scope === 'body' && (field === 'email' || field === 'role')
      ? [[field, { key: 'common.serverText', values: { text: detail.msg } }]] : []
  }))
}

const unavailableEmail = { key: 'share.unknownEmail' }

async function optionalConfig<T>(load: () => Promise<T>) {
  try { return await load() } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export const keycloakOptions = (id: string, enabled: boolean) => queryOptions({
  ...options, queryKey: [...projectKeys.project(id), 'keycloak'], enabled,
  queryFn: () => optionalConfig(() => api.getKeycloak(id)),
})

export const checklistOptions = (id: string, enabled: boolean) => queryOptions({
  ...options, queryKey: [...projectKeys.project(id), 'checklist'], enabled,
  queryFn: async () => {
    const [payments, storage, generations, roles] = await Promise.all([
      optionalConfig(() => api.getPayments(id)), optionalConfig(() => api.getStorage(id)),
      api.listGenerations(id, 1), api.listRoles(id),
    ])
    return { payments, storage, generations: generations.total, roles: roles.total }
  },
})

type ShareAction =
  | { kind: 'add'; email: string; role: MemberRole }
  | { kind: 'role'; user: string; role: MemberRole }
  | { kind: 'remove'; user: string }

export function useShareMutation(id: string) {
  const client = useQueryClient()
  const refresh = () => { void client.invalidateQueries({ queryKey: membersOptions(id).queryKey }) }
  return useMutation({
    scope: { id: 'project-members:' + id },
    mutationFn: async (action: ShareAction) => {
      switch (action.kind) {
        case 'add': await api.addMember(id, action.email, action.role); break
        case 'role': await api.setMemberRole(id, action.user, action.role); break
        case 'remove': await api.removeMember(id, action.user); break
      }
    },
    onSuccess: refresh,
    onError: (error, action) => {
      if (action.kind !== 'add' && workspaceError(error) === 'not_found') refresh()
    },
  })
}
