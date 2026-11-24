import type { Approval } from '../api/guided'

export const scopeKinds = ['entities', 'hooks', 'zones', 'dependencies'] as const
export type ScopeKind = (typeof scopeKinds)[number]
export type ScopeRow = { kind: ScopeKind; name: string; removed?: boolean }
const extensionKinds = { entity: 'entities', hook: 'hooks', zone: 'zones', dependency: 'dependencies' } as const

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function scopeRows(value: unknown): ScopeRow[] {
  const scope = object(value)
  return scopeKinds.flatMap(kind => {
    const names = scope[kind]
    return Array.isArray(names) ? names.flatMap(name => typeof name === 'string' ? [{ kind, name }] : []) : []
  })
}

export function extensionRows(payload: Approval['payload']): ScopeRow[] | undefined {
  if (!('extend_items' in payload || 'extend' in payload)) return undefined
  const extensions = Array.isArray(payload.extend_items) && payload.extend_items.length ? payload.extend_items : [payload.extend]
  return extensions.flatMap(value => {
    const { kind, name } = object(value)
    return typeof kind === 'string' && Object.hasOwn(extensionKinds, kind) && typeof name === 'string'
      ? [{ kind: extensionKinds[kind as keyof typeof extensionKinds], name }] : []
  })
}

export function rowKey(row: ScopeRow) { return `${row.kind}:${row.name}` }

type Action = { type: 'toggle' | 'add'; row: ScopeRow }
export function planReducer(rows: ScopeRow[], action: Action): ScopeRow[] {
  const key = rowKey(action.row)
  if (action.type === 'toggle') return rows.map(row => rowKey(row) === key ? { ...row, removed: !row.removed } : row)
  if (rows.some(row => rowKey(row) === key)) return rows
  return [...rows, action.row]
}

export function buildScope(rows: ScopeRow[]) {
  const plan: Record<string, string[]> = {}
  for (const kind of scopeKinds) {
    const names = [...new Set(rows.filter(row => row.kind === kind && !row.removed).map(row => row.name))].sort()
    if (names.length) plan[kind] = names
  }
  return plan
}

export function approvalBinding(approval: Approval) {
  return JSON.stringify([approval.id, approval.state, approval.payload_hash, approval.bound_spec_hash, approval.bound_commit])
}

export function activePlan(approvals: Approval[]) {
  return approvals.filter(approval => approval.kind === 'A').sort((a, b) =>
    Number(b.state === 'pending') - Number(a.state === 'pending') || Date.parse(b.created_at) - Date.parse(a.created_at),
  )[0]
}
