import type { Operand, Policy, PolicyCondition, PolicyGroup, PolicyLeaf, SpecForPolicies } from '../../api/types'

/** The operations a generated entity route can have, in the order the docs list them. */
export const OPERATIONS = ['list', 'get', 'create', 'replace', 'update', 'delete', 'head'] as const

export const OPS: { id: string; label: string; unary?: boolean; list?: boolean }[] = [
  { id: 'eq', label: 'is' },
  { id: 'ne', label: 'is not' },
  { id: 'lt', label: 'is less than' },
  { id: 'lte', label: 'is at most' },
  { id: 'gt', label: 'is more than' },
  { id: 'gte', label: 'is at least' },
  { id: 'in', label: 'is one of', list: true },
  { id: 'not_in', label: 'is not one of', list: true },
  { id: 'contains', label: 'includes' },
  { id: 'is_null', label: 'is empty', unary: true },
  { id: 'not_null', label: 'is set', unary: true },
  { id: 'ip_in', label: 'is inside the network', list: true },
]

export const ENV_ATTRIBUTES: { id: string; label: string; kind: string }[] = [
  { id: 'hour_utc', label: 'current hour (UTC, 0-23)', kind: 'integer' },
  { id: 'weekday_utc', label: 'weekday (UTC, Monday is 0)', kind: 'integer' },
  { id: 'client_ip', label: 'IP address of the caller', kind: 'string' },
]

export type OperandKind = 'subject' | 'resource' | 'env' | 'literal'

export const KIND_LABELS: Record<OperandKind, string> = {
  subject: 'The person',
  resource: 'The record',
  env: 'The moment',
  literal: 'A value',
}

const FIELD_KIND: Record<string, string> = {
  string: 'string',
  text: 'string',
  enum: 'string',
  integer: 'integer',
  bigint: 'integer',
  float: 'number',
  decimal: 'number',
  boolean: 'boolean',
  date: 'date',
  datetime: 'datetime',
  uuid: 'uuid',
}

export interface Catalogue {
  /** entity -> attribute -> kind (only fields a policy can look at). */
  resource: Record<string, Record<string, string>>
  subject: Record<string, string>
  roles: string[]
  entities: { name: string; ops: string[] }[]
}

export function buildCatalogue(spec: SpecForPolicies): Catalogue {
  const resource: Record<string, Record<string, string>> = {}
  for (const e of spec.entities) {
    const attrs: Record<string, string> = {
      id: 'uuid',
      created_at: 'datetime',
      updated_at: 'datetime',
      created_by_id: 'uuid',
    }
    for (const f of e.fields) {
      const kind = FIELD_KIND[f.type]
      if (kind) attrs[f.name] = kind
    }
    resource[e.name] = attrs
  }
  const subject: Record<string, string> = { id: 'uuid', email: 'string', roles: 'list' }
  if (spec.auth?.multi_tenant) subject.tenant_id = 'uuid'
  for (const c of spec.auth?.registration?.custom_fields ?? []) {
    if (FIELD_KIND[c.type] || ['email', 'phone', 'url'].includes(c.type)) subject[c.name] = FIELD_KIND[c.type] ?? 'string'
  }
  return {
    resource,
    subject,
    roles: (spec.auth?.roles ?? []).map((r) => r.name),
    entities: spec.entities.map((e) => ({
      name: e.name,
      ops: (OPERATIONS as readonly string[]).filter((op) => (e.options.operations ?? (OPERATIONS as readonly string[])).includes(op)),
    })),
  }
}

/** All action strings the policy form can offer: `*`, `Entity.*` and `Entity.op`. */
export function actionChoices(catalogue: Catalogue): string[] {
  const out = ['*']
  for (const e of catalogue.entities) {
    out.push(`${e.name}.*`)
    for (const op of e.ops) out.push(`${e.name}.${op}`)
  }
  return out
}

export function isGroup(node: PolicyCondition): node is PolicyGroup {
  return 'all' in node || 'any' in node
}

export function groupKey(node: PolicyGroup): 'all' | 'any' {
  return 'all' in node ? 'all' : 'any'
}

export function emptyLeaf(): PolicyLeaf {
  return { left: { resource: '' }, op: 'eq', right: { literal: '' } }
}

export function emptyGroup(key: 'all' | 'any' = 'all'): PolicyGroup {
  return key === 'all' ? { all: [emptyLeaf()] } : { any: [emptyLeaf()] }
}

export function operandKind(operand: Operand): OperandKind {
  return Object.keys(operand)[0] as OperandKind
}

export function operandName(operand: Operand): string {
  const kind = operandKind(operand)
  const value = (operand as Record<string, unknown>)[kind]
  return kind === 'literal' ? literalToText(value) : String(value ?? '')
}

export function literalToText(value: unknown): string {
  if (Array.isArray(value)) return value.map((v) => String(v)).join(', ')
  if (value === null || value === undefined) return ''
  return String(value)
}

/** Text typed in the form -> the JSON value stored in the policy, typed by what it is compared with. */
export function parseLiteral(text: string, listValue: boolean, kind: string | undefined): unknown {
  const parse = (part: string): unknown => {
    const t = part.trim()
    if (kind === 'integer' || kind === 'number') {
      const n = Number(t)
      return t !== '' && Number.isFinite(n) ? n : t
    }
    if (kind === 'boolean') return t === 'true' ? true : t === 'false' ? false : t
    return t
  }
  if (listValue) {
    return text
      .split(',')
      .map((p) => p.trim())
      .filter((p) => p !== '')
      .map(parse)
  }
  return parse(text)
}

const ENV_WORDS: Record<string, string> = {
  hour_utc: 'the current hour (UTC)',
  weekday_utc: 'the weekday (UTC, Monday is 0)',
  client_ip: 'your IP address',
}

function operandText(operand: Operand): string {
  const kind = operandKind(operand)
  const value = (operand as Record<string, unknown>)[kind]
  if (kind === 'subject') return value === 'roles' ? 'your roles' : `your ${String(value).replace(/_/g, ' ')}`
  if (kind === 'resource') return `the record's ${String(value).replace(/_/g, ' ')}`
  if (kind === 'env') return ENV_WORDS[String(value)] ?? String(value)
  return JSON.stringify(value)
}

/** The same plain-English rendering the generated documentation uses. */
export function describe(node: PolicyCondition | null): string {
  if (node === null) return 'always'
  if (isGroup(node)) {
    const key = groupKey(node)
    const parts = (node[key] ?? []).map(describe)
    return parts.length === 1 ? parts[0] : `(${parts.join(key === 'all' ? ' and ' : ' or ')})`
  }
  const word = OPS.find((o) => o.id === node.op)?.label ?? node.op
  const left = operandText(node.left)
  return node.right === undefined ? `${left} ${word}` : `${left} ${word} ${operandText(node.right)}`
}

/** Kind of the attribute an operand points at, when it is a record attribute of one of the entities. */
export function resourceKind(catalogue: Catalogue, entities: string[], name: string): string | undefined {
  for (const e of entities) {
    const kind = catalogue.resource[e]?.[name]
    if (kind) return kind
  }
  return undefined
}

/** Entities a policy's action list reaches (`*` = all). */
export function reachedEntities(catalogue: Catalogue, actions: string[]): string[] {
  if (actions.includes('*')) return catalogue.entities.map((e) => e.name)
  return [...new Set(actions.map((a) => a.split('.')[0]))].filter((n) => catalogue.resource[n])
}

export function emptyPolicy(existing: Policy[]): Policy {
  let n = existing.length + 1
  while (existing.some((p) => p.id === `policy_${n}`)) n += 1
  return { id: `policy_${n}`, description: '', effect: 'allow', actions: [], when: null }
}

/** Ready-made starting points so nobody faces an empty form. */
export const TEMPLATES: { title: string; help: string; build: (entity: string) => Omit<Policy, 'id'> }[] = [
  {
    title: 'People see and change their own records',
    help: 'Allow every action on the record when you created it.',
    build: (entity) => ({
      description: 'Everybody works on the records they created.',
      effect: 'allow',
      actions: [`${entity}.*`],
      when: { left: { resource: 'created_by_id' }, op: 'eq', right: { subject: 'id' } },
    }),
  },
  {
    title: 'Only during office hours',
    help: 'Allow writing between 08:00 and 18:00 UTC.',
    build: (entity) => ({
      description: 'Writes are allowed from 08:00 to 17:59 UTC.',
      effect: 'allow',
      actions: [`${entity}.create`, `${entity}.update`, `${entity}.delete`],
      when: {
        all: [
          { left: { env: 'hour_utc' }, op: 'gte', right: { literal: 8 } },
          { left: { env: 'hour_utc' }, op: 'lt', right: { literal: 18 } },
        ],
      },
    }),
  },
  {
    title: 'Only from the office network',
    help: 'Allow actions only for callers inside an address range.',
    build: (entity) => ({
      description: 'Only from the office network.',
      effect: 'allow',
      actions: [`${entity}.*`],
      when: { left: { env: 'client_ip' }, op: 'ip_in', right: { literal: ['10.0.0.0/8'] } },
    }),
  },
  {
    title: 'Nobody changes finished records',
    help: 'A deny policy that wins over every allow policy.',
    build: (entity) => ({
      description: 'Finished records are frozen.',
      effect: 'deny',
      actions: [`${entity}.update`, `${entity}.replace`, `${entity}.delete`],
      when: { left: { resource: 'status' }, op: 'eq', right: { literal: 'done' } },
    }),
  },
]

/** Drops empty groups (the API refuses them) and unwraps groups of one. Null when nothing is left. */
export function prune(node: PolicyCondition | null): PolicyCondition | null {
  if (node === null) return null
  if (!isGroup(node)) return node
  const key = groupKey(node)
  const kept = (node[key] ?? []).map(prune).filter((n): n is PolicyCondition => n !== null)
  if (kept.length === 0) return null
  return key === 'all' ? { all: kept } : { any: kept }
}
