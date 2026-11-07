import type { Approval } from './types'

export const PLAN_KEYS = ['entities', 'hooks', 'zones', 'dependencies'] as const
export type PlanKey = (typeof PLAN_KEYS)[number]
export const PLAN_LABEL: Record<PlanKey, string> = { entities: 'Data it may change', hooks: 'Custom logic it may write', zones: 'Areas it may touch', dependencies: 'Packages it may add' }

export interface PlanRow { key: PlanKey; value: string; removed: boolean }

const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])

/** The editable scope table from a Gate A payload ({plan:{entities,hooks,zones,dependencies}}). */
export function planRows(payload: Record<string, unknown>): PlanRow[] {
  const plan = (payload.plan && typeof payload.plan === 'object' ? payload.plan : {}) as Record<string, unknown>
  return PLAN_KEYS.flatMap((key) => strs(plan[key]).map((value) => ({ key, value, removed: false })))
}

export const phasesOf = (payload: Record<string, unknown>): string[] => strs(payload.phases)

export const toggleRow = (rows: PlanRow[], i: number): PlanRow[] => rows.map((r, j) => (j === i ? { ...r, removed: !r.removed } : r))
export const addRow = (rows: PlanRow[], key: PlanKey, value: string): PlanRow[] => {
  const v = value.trim().slice(0, 120)
  return v && !rows.some((r) => r.key === key && r.value === v) ? [...rows, { key, value: v, removed: false }] : rows
}
export const isEdited = (rows: PlanRow[], original: PlanRow[]): boolean =>
  rows.length !== original.length || rows.some((r, i) => r.removed || r.key !== original[i].key || r.value !== original[i].value)

/** The kept scope, grouped for display or for a note. */
export function keptPlan(rows: PlanRow[]): Record<PlanKey, string[]> {
  const out = { entities: [], hooks: [], zones: [], dependencies: [] } as Record<PlanKey, string[]>
  for (const r of rows) if (!r.removed) out[r.key].push(r.value)
  return out
}

/** The reviewer's edited scope as the decision body's `plan`: lists of strings per plan key. */
export const planBody = (rows: PlanRow[]): Record<PlanKey, string[]> => keptPlan(rows)
export const isEmptyPlan = (rows: PlanRow[]): boolean => PLAN_KEYS.every((k) => keptPlan(rows)[k].length === 0)

/** The server keeps the agent's original in payload.edited_from when a reviewer approved an edited plan. */
export interface EditedInfo { from: PlanRow[]; by: string | null }
export function editedInfo(payload: Record<string, unknown>): EditedInfo | null {
  const from = payload.edited_from
  if (!from || typeof from !== 'object' || Array.isArray(from)) return null
  const by = payload.edited_by
  return { from: planRows({ plan: from }), by: typeof by === 'string' && by ? by.slice(0, 80) : null }
}

export const PLAN_ERRORS: Record<string, string> = {
  plan_empty: 'The edited plan is empty, so the build step could touch nothing. Keep at least one item, or deny the plan instead.',
}

/** Gate A to show: a pending one for this run first, else the newest decided one. */
export const gateAFor = (approvals: Approval[]): Approval | null =>
  approvals.find((a) => a.kind === 'A' && a.state === 'pending') ?? approvals.filter((a) => a.kind === 'A').sort((x, y) => y.created_at.localeCompare(x.created_at))[0] ?? null

export const gateAPending = (approvals: Approval[], runId?: string) =>
  approvals.find((a) => a.kind === 'A' && a.state === 'pending' && (!runId || a.run_id === runId)) ?? null
