import type { AuthorizationSettings, Policy, PolicyCondition } from '../api/controls'

export type OperandKind = 'subject' | 'resource' | 'env' | 'literal'
export type DraftOperand = { kind: OperandKind; value: string }
type Leaf = { kind: 'comparison'; left: DraftOperand; op: string; right: DraftOperand }
type Group = { kind: 'all' | 'any'; children: DraftCondition[] }
export type DraftCondition = Leaf | Group
export type DraftPolicy = Omit<Policy, 'when'> & { when: DraftCondition | null }
export type PolicyDraft = { original?: Policy; base: AuthorizationSettings; policy: DraftPolicy }
type PolicyAction = { type: 'open'; draft: PolicyDraft } | { type: 'change'; value: Partial<DraftPolicy> } | { type: 'close' }

const kinds = ['subject', 'resource', 'env', 'literal'] as const
export const unary = (op: string) => op === 'is_null' || op === 'not_null'
export const emptyOperand = (kind: OperandKind): DraftOperand => ({ kind, value: kind === 'literal' ? '""' : '' })
export const emptyLeaf = (): DraftCondition => ({ kind: 'comparison', left: emptyOperand('resource'), op: 'eq', right: emptyOperand('literal') })

function operandDraft(value: Record<string, unknown>): DraftOperand {
  const kind = kinds.find(key => key in value) ?? 'literal'
  return { kind, value: kind === 'literal' ? JSON.stringify(value[kind]) ?? 'null' : String(value[kind] ?? '') }
}
export function conditionDraft(node: PolicyCondition | null): DraftCondition | null {
  if (!node) return null
  if ('left' in node) return { kind: 'comparison', op: node.op, left: operandDraft(node.left),
    right: node.right ? operandDraft(node.right) : emptyOperand('literal') }
  const kind = node.all ? 'all' : 'any'
  return { kind, children: (node[kind] ?? []).flatMap(item => {
    const next = conditionDraft(item)
    return next ? [next] : []
  }) }
}
export function conditionSize(node: DraftCondition | null): number {
  if (!node) return 0
  return node.kind === 'comparison' ? 1 : 1 + node.children.reduce((count, item) => count + conditionSize(item), 0)
}
export function conditionBody(node: DraftCondition | null): PolicyCondition | null {
  if (!node) return null
  if (node.kind === 'comparison') {
    const operand = (item: DraftOperand) => ({ [item.kind]: item.kind === 'literal' ? JSON.parse(item.value) as unknown : item.value })
    const left = operand(node.left) as Extract<PolicyCondition, { left: unknown }>['left']
    const right = unary(node.op) ? undefined : operand(node.right) as typeof left
    return { left, op: node.op, ...(right ? { right } : {}) }
  }
  return { [node.kind]: node.children.flatMap(child => {
    const result = conditionBody(child)
    return result ? [result] : []
  }) }
}

export function policyReducer(state: PolicyDraft | null, action: PolicyAction): PolicyDraft | null {
  if (action.type === 'close') return null
  if (action.type === 'open') return action.draft
  return state && { ...state, policy: { ...state.policy, ...action.value } }
}
