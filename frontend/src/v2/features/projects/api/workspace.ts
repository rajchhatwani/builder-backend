import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, onOrgLocked, onOrgMfaRequired, onQuotaExceeded } from '../../../../api/client'
import type { MemberRole, OrgLockedDetail, OrgMfaDetail, QuotaDetail } from '../../../../api/types'
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
  | { kind: 'mcp'; user: string; enabled: boolean }
  | { kind: 'remove'; user: string }

export function useShareMutation(id: string) {
  const client = useQueryClient()
  return useMutation({
    scope: { id: 'project-members:' + id },
    mutationFn: async (action: ShareAction) => {
      switch (action.kind) {
        case 'add': await api.addMember(id, action.email, action.role); break
        case 'role': await api.setMemberRole(id, action.user, action.role); break
        case 'mcp': await api.setMemberMcp(id, action.user, action.enabled); break
        case 'remove': await api.removeMember(id, action.user); break
      }
    },
    onSuccess: () => client.invalidateQueries({ queryKey: membersOptions(id).queryKey }),
  })
}
