import type { AccessCell, AccessDiff, AccessDiffRequest, AccessLayer, AccessMatrix, FieldAccessRule, PermissionRule } from '../../api/types'

export const PUBLIC_ROLE = '(public)'
export const LAYERS: { id: AccessLayer; label: string }[] = [
  { id: 'object', label: 'Object' },
  { id: 'field', label: 'Field' },
  { id: 'row', label: 'Row' },
]
const OP_ORDER = ['list', 'get', 'create', 'replace', 'update', 'delete', 'head']

export interface AccessTable {
  targets: string[]
  roles: string[]
  /** values[role][target]; a missing entry means no cell exists there (shown as an em dash). */
  values: Record<string, Record<string, string>>
}

/** Cells of one layer and entity as a role x target table. Roles keep the API order; targets are operations in a
 *  fixed order (object, row) or in order of first appearance, field by field (field). */
export function groupTable(matrix: AccessMatrix, layer: AccessLayer, entity: string): AccessTable {
  const cells = matrix.cells.filter((c) => c.layer === layer && c.entity === entity)
  const seen: string[] = []
  const values: Record<string, Record<string, string>> = {}
  for (const c of cells) {
    if (!seen.includes(c.target)) seen.push(c.target)
    ;(values[c.role] ??= {})[c.target] = c.value
  }
  const rank = (t: string) => {
    const i = OP_ORDER.indexOf(t)
    return i < 0 ? OP_ORDER.length : i
  }
  const targets = layer === 'field' ? seen : [...seen].sort((a, b) => rank(a) - rank(b))
  return { targets, roles: matrix.roles, values }
}

/** Field names that have field cells for an entity. */
export function fieldNames(matrix: AccessMatrix, entity: string): string[] {
  const out: string[] = []
  for (const c of matrix.cells as AccessCell[]) {
    if (c.layer !== 'field' || c.entity !== entity) continue
    const name = c.target.replace(/\.(read|write)$/, '')
    if (!out.includes(name)) out.push(name)
  }
  return out
}

/** Roles that can be edited: everything but the (public) pseudo role. */
export const editableRoles = (matrix: AccessMatrix) => matrix.roles.filter((r) => r !== PUBLIC_ROLE)

// ── spec access (spec.auth.permissions, spec.authorization.field_access) ──
type Spec = Record<string, unknown>
const asObj = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})

export const permissionsOf = (spec: Spec): PermissionRule[] => {
  const p = asObj(spec.auth).permissions
  return Array.isArray(p) ? (p as PermissionRule[]) : []
}
export const fieldAccessOf = (spec: Spec): FieldAccessRule[] => {
  const f = asObj(spec.authorization).field_access
  return Array.isArray(f) ? (f as FieldAccessRule[]) : []
}

/** The spec with the edited lists put in; a null list keeps the saved one. Never mutates the input. */
export function withEdits(spec: Spec, edits: AccessDiffRequest): Spec {
  const next: Spec = { ...spec }
  if (edits.permissions) next.auth = { ...asObj(spec.auth), permissions: edits.permissions }
  if (edits.field_access) next.authorization = { ...asObj(spec.authorization), field_access: edits.field_access }
  return next
}

/** Adds or removes one role on the (entity, operation) rule. A rule left with no roles stays (empty means nobody). */
export function toggleRole(rules: PermissionRule[], entity: string, operation: string, role: string, on: boolean): PermissionRule[] {
  const at = rules.findIndex((r) => r.entity === entity && r.operation === operation)
  if (at < 0) return on ? [...rules, { entity, operation, roles: [role] }] : rules
  const roles = rules[at].roles.filter((r) => r !== role)
  if (on) roles.push(role)
  return rules.map((r, i) => (i === at ? { ...r, roles } : r))
}

export const rolesOfOperation = (rules: PermissionRule[], entity: string, operation: string): string[] =>
  rules.find((r) => r.entity === entity && r.operation === operation)?.roles ?? []

/** Sets read/write role lists of one field (null = unrestricted). A rule with both null is dropped. */
export function setFieldRoles(
  rules: FieldAccessRule[],
  entity: string,
  field: string,
  next: { read_roles: string[] | null; write_roles: string[] | null },
): FieldAccessRule[] {
  const rest = rules.filter((r) => !(r.entity === entity && r.field === field))
  if (next.read_roles === null && next.write_roles === null) return rest
  return [...rest, { entity, field, read_roles: next.read_roles, write_roles: next.write_roles }]
}

export const fieldRolesOf = (rules: FieldAccessRule[], entity: string, field: string) => {
  const r = rules.find((x) => x.entity === entity && x.field === field)
  return { read_roles: r?.read_roles ?? null, write_roles: r?.write_roles ?? null }
}

export function permissionsRequest(rules: PermissionRule[]): AccessDiffRequest {
  return { permissions: rules, field_access: null }
}
export function fieldAccessRequest(rules: FieldAccessRule[]): AccessDiffRequest {
  return { permissions: null, field_access: rules }
}

export interface DiffSummary {
  gains: { role: string; targets: string[] }[]
  losses: { role: string; targets: string[] }[]
  lines: string[]
  weakens: boolean
  total: number
}

/** The review list: exactly the roles and targets the API names, in the API order. */
export function summariseDiff(diff: AccessDiff): DiffSummary {
  const gains = Object.entries(diff.roles_gaining).map(([role, targets]) => ({ role, targets }))
  const losses = Object.entries(diff.roles_losing).map(([role, targets]) => ({ role, targets }))
  const lines = [
    ...gains.map((g) => `Role ${g.role} gains ${g.targets.join(', ')}`),
    ...losses.map((l) => `Role ${l.role} loses ${l.targets.join(', ')}`),
  ]
  return { gains, losses, lines, weakens: diff.weakens, total: diff.changes.length }
}
