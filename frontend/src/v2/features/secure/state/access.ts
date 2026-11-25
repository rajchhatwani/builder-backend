import type { AuthorizationSettings, PermissionEntry, ProjectPermission, ProjectRole } from '../api/controls'
import type { controlsApi } from '../api/controls'

export type RoleValues = Parameters<typeof controlsApi.createRole>[1]
export type AuthorizationEdit =
  | { kind: 'settings'; settings: AuthorizationSettings }
  | { kind: 'role'; existing?: ProjectRole; values: RoleValues }

export type Review = { edit: AuthorizationEdit; confirm: boolean; removePolicies?: boolean }
type ReviewAction = { type: 'review'; edit: AuthorizationEdit } | { type: 'confirm'; edit: AuthorizationEdit } | { type: 'close' }

export function reviewReducer(_review: Review | null, action: ReviewAction): Review | null {
  if (action.type === 'close') return null
  return { edit: action.edit, confirm: action.type === 'confirm',
    removePolicies: action.type === 'review' && action.edit.kind === 'settings' }
}

export const operations = ['list', 'get', 'create', 'replace', 'update', 'delete', 'head'] as const

export type PermissionChange = { current: ProjectPermission | undefined; value: PermissionEntry | null }
export type PermissionChanges = Record<string, PermissionChange>
export type PermissionAction = { type: 'stage'; key: string; change: PermissionChange } |
  { type: 'applied'; keys: string[] } | { type: 'reset' }

export function permissionReducer(draft: PermissionChanges, action: PermissionAction): PermissionChanges {
  if (action.type === 'reset') return {}
  if (action.type === 'applied') return Object.fromEntries(Object.entries(draft).filter(([key]) => !action.keys.includes(key)))
  return { ...draft, [action.key]: action.change }
}
