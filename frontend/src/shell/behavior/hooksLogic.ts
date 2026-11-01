/** Pure logic for Build > Hooks (F1-5): declared hook <-> API body, the point picker, the legal kind / failure-policy
 *  choices, the stub text and the backend issue path -> form field. No React here, so it is unit-tested directly.
 *  The rules mirror app/core/validation_hooks.py to keep users from typing an impossible combination; the backend
 *  validator stays the truth and its messages are shown as they come. */
import type { HookBody, HookFieldBody, ValidationIssue } from '../../api/types'
import { issuesForSection, newKey, type FieldErrors, type SectionIssues } from './formLogic'

export const HOOK_TYPES = ['string', 'int', 'float', 'decimal', 'bool', 'date', 'datetime', 'uuid'] as const
export const KINDS = ['pure', 'effect'] as const
export const POLICIES = ['fail_closed', 'fail_open', 'fallback'] as const
export const STAGES = ['before_save', 'validate', 'after_save', 'after_commit'] as const
export type Stage = (typeof STAGES)[number] | 'transition_guard'

/** Builder field type -> hook field type (validation_hooks.ENTITY_TO_HOOK). Other types cannot cross the contract. */
export const ENTITY_TO_HOOK: Record<string, string> = {
  string: 'string', text: 'string', enum: 'string', integer: 'int', bigint: 'int', float: 'float',
  decimal: 'decimal', boolean: 'bool', date: 'date', datetime: 'datetime', uuid: 'uuid',
}

/** Budget ceilings per kind (validation_hooks.CEILINGS). */
export const CEILINGS = {
  pure: { cpu_ms: 1000, rows: 0, outbound_calls: 0 },
  effect: { cpu_ms: 4000, rows: 1000, outbound_calls: 0 },
} as const

/** Fixed output shapes the platform acts on (validation_hooks.GUARD_OUTPUT / VALIDATE_OUTPUT). */
export const FIXED_OUTPUT: Record<'validate' | 'transition_guard', HookFieldBody[]> = {
  validate: [{ name: 'valid', type: 'bool', required: true }, { name: 'message', type: 'string', required: false }],
  transition_guard: [{ name: 'allowed', type: 'bool', required: true }, { name: 'reason', type: 'string', required: false }],
}

export const GATE_COMMAND = 'python -m app.platform_gate'
export const CONTRACT_VERSION = 'v1' // module.py CONTRACT
export const SIGNATURE_COMMENT = '# platform:signature (fixed)' // hook_gates.SIGNATURE_COMMENT
export const stubPath = (name: string) => `app/custom/hooks/${name}.py`

// ── Points ──────────────────────────────────────────────────────────────────
const POINT_RE = /^([A-Z][A-Za-z0-9_]*)\.(?:(before_save|validate|after_save|after_commit)|transition_guard\(([a-z][a-z0-9_]*)\))$/

export interface ParsedPoint {
  entity: string
  stage: Stage
  transition: string | null
}

export function parsePoint(point: string): ParsedPoint | null {
  const m = POINT_RE.exec(point)
  if (!m) return null
  return { entity: m[1], stage: (m[2] as Stage | undefined) ?? 'transition_guard', transition: m[3] ?? null }
}

export const buildPoint = (entity: string, stage: Stage, transition?: string | null) =>
  stage === 'transition_guard' ? `${entity}.transition_guard(${transition ?? ''})` : `${entity}.${stage}`

export interface CatalogEntity {
  /** Fields a hook can read (name + hook type), `id` first. */
  fields: { name: string; type: string }[]
  /** State field of the entity's machine, null when it has none. */
  stateField: string | null
  /** MANUAL transitions only (a guard hook cannot sit on an automatic one). */
  transitions: string[]
}
export type HookCatalog = Record<string, CatalogEntity>

export interface PointOption {
  value: string
  label: string
  group: string
}

const STAGE_LABEL: Record<(typeof STAGES)[number], string> = {
  before_save: 'before save (set values)',
  validate: 'validate (accept or refuse a save)',
  after_save: 'after save (inside the transaction)',
  after_commit: 'after commit (side effect)',
}

/** Every point the backend would accept for this project, grouped by entity. */
export function pointOptions(catalog: HookCatalog): PointOption[] {
  const out: PointOption[] = []
  for (const entity of Object.keys(catalog).sort()) {
    for (const stage of STAGES) out.push({ value: buildPoint(entity, stage), label: STAGE_LABEL[stage], group: entity })
    for (const t of catalog[entity].transitions) {
      out.push({ value: buildPoint(entity, 'transition_guard', t), label: `guard for transition ${t}`, group: entity })
    }
  }
  return out
}

// ── Legal combinations ──────────────────────────────────────────────────────
export const legalKinds = (stage: Stage | null): readonly string[] => (stage === null || stage === 'after_commit' ? KINDS : ['pure'])

export function legalPolicies(stage: Stage | null): readonly string[] {
  if (stage === 'validate' || stage === 'transition_guard') return ['fail_closed']
  if (stage === 'after_commit') return ['fail_open', 'fallback']
  return POLICIES
}

/** validation_hooks.default_policy */
export function defaultPolicy(stage: Stage | null, kind: string): string {
  if (stage === 'validate' || stage === 'transition_guard') return 'fail_closed'
  if (kind === 'effect' || stage === 'after_commit') return 'fail_open'
  return 'fail_closed'
}

// ── Form row ────────────────────────────────────────────────────────────────
export interface HookRow {
  k: number
  name: string
  point: string
  kind: string
  policy: string
  cpu_ms: string
  rows: string
  outbound_calls: string
  reads: string[]
  inputModel: string
  outputModel: string
  inputFields: HookFieldBody[]
  outputFields: HookFieldBody[]
  /** Fallback output values as typed text, by output field name. */
  fallback: Record<string, string>
}

const camel = (snake: string) => snake.split('_').filter(Boolean).map((p) => p[0].toUpperCase() + p.slice(1)).join('')
/** Default model names for a hook name (match_invoice -> MatchInvoiceInput / MatchInvoiceResult); '' while unnamed. */
export const autoModels = (name: string): { input: string; output: string } => {
  const base = /^[a-z][a-z0-9_]*$/.test(name) ? camel(name) : ''
  return base ? { input: `${base}Input`, output: `${base}Result` } : { input: '', output: '' }
}

const stageOf = (point: string): Stage | null => parsePoint(point)?.stage ?? null

export function hookFromBody(b: HookBody): HookRow {
  const kind = b.kind ?? 'pure'
  return {
    k: newKey(),
    name: b.name,
    point: b.point,
    kind,
    policy: b.failure_policy ?? defaultPolicy(stageOf(b.point), kind),
    cpu_ms: String(b.budget?.cpu_ms ?? 200),
    rows: String(b.budget?.rows ?? 0),
    outbound_calls: String(b.budget?.outbound_calls ?? 0),
    reads: [...(b.reads ?? [])],
    inputModel: b.input.name,
    outputModel: b.output.name,
    inputFields: (b.input.fields ?? []).map((f) => ({ name: f.name, type: f.type ?? 'string', required: f.required ?? true })),
    outputFields: (b.output.fields ?? []).map((f) => ({ name: f.name, type: f.type ?? 'string', required: f.required ?? true })),
    fallback: Object.fromEntries(Object.entries(b.fallback ?? {}).map(([k, v]) => [k, String(v)])),
  }
}

const INT = /^-?\d+$/
const num = (t: string) => (INT.test(t.trim()) ? Number(t.trim()) : Number.NaN)

/** "true"/"false" -> boolean, numbers for int/float; anything else stays text so the backend can say what is wrong. */
function fallbackValue(type: string, text: string): string | number | boolean {
  const t = text.trim()
  if (type === 'bool') return t === 'true' ? true : t === 'false' ? false : t
  if (type === 'int') return INT.test(t) ? Number(t) : t
  if (type === 'float') return t !== '' && Number.isFinite(Number(t)) ? Number(t) : t
  return type === 'string' ? text : t
}

export function hookToBody(r: HookRow): HookBody {
  const fallback: Record<string, string | number | boolean> = {}
  if (r.policy === 'fallback') {
    for (const f of r.outputFields) {
      const text = r.fallback[f.name]
      if (text !== undefined && text.trim() !== '') fallback[f.name] = fallbackValue(f.type ?? 'string', text)
    }
  }
  return {
    name: r.name.trim(),
    point: r.point,
    kind: r.kind,
    input: { name: r.inputModel.trim(), fields: r.inputFields.map((f) => ({ ...f })) },
    output: { name: r.outputModel.trim(), fields: r.outputFields.map((f) => ({ ...f })) },
    failure_policy: r.policy,
    fallback: r.policy === 'fallback' ? fallback : null,
    budget: { cpu_ms: num(r.cpu_ms), rows: num(r.rows), outbound_calls: num(r.outbound_calls) },
    reads: [...r.reads],
  }
}

const fieldsFor = (entity: CatalogEntity | undefined, names: string[]): HookFieldBody[] =>
  names.flatMap((n) => {
    const f = entity?.fields.find((x) => x.name === n)
    return f ? [{ name: f.name, type: f.type, required: true }] : []
  })

/** Default output of a new hook at a stage. */
export function defaultOutput(stage: Stage | null): HookFieldBody[] {
  if (stage === 'validate' || stage === 'transition_guard') return FIXED_OUTPUT[stage].map((f) => ({ ...f }))
  if (stage === 'after_save' || stage === 'after_commit') return [{ name: 'done', type: 'bool', required: true }]
  return []
}

/** Make a row consistent with its point: legal kind and policy, budget inside the ceilings, input fields that exist,
 *  the output shape of the stage. Called when the point or the kind changes. */
export function retarget(row: HookRow, point: string, catalog: HookCatalog): HookRow {
  const parsed = parsePoint(point)
  const stage = parsed?.stage ?? null
  const entity = parsed ? catalog[parsed.entity] : undefined
  const pointChanged = point !== row.point
  const kind = legalKinds(stage).includes(row.kind) ? row.kind : 'pure'
  const policies = legalPolicies(stage)
  const policy = policies.includes(row.policy) && !(pointChanged && row.policy === defaultPolicy(stageOf(row.point), row.kind))
    ? row.policy
    : defaultPolicy(stage, kind)
  const ceiling = CEILINGS[kind as 'pure' | 'effect'] ?? CEILINGS.pure
  const clamp = (text: string, min: number, max: number) =>
    INT.test(text.trim()) ? String(Math.min(Math.max(Number(text.trim()), min), max)) : text
  const keptInputs = row.inputFields.filter((f) => entity?.fields.some((x) => x.name === f.name))
  return {
    ...row,
    point,
    kind,
    policy: policies.includes(policy) ? policy : policies[0],
    cpu_ms: clamp(row.cpu_ms, 1, ceiling.cpu_ms),
    rows: clamp(row.rows, 0, ceiling.rows),
    outbound_calls: clamp(row.outbound_calls, 0, ceiling.outbound_calls),
    reads: kind === 'effect' ? row.reads.filter((n) => n in catalog) : [],
    inputFields: pointChanged ? (keptInputs.length ? keptInputs : fieldsFor(entity, ['id'])) : row.inputFields,
    outputFields: pointChanged ? defaultOutput(stage) : row.outputFields,
    fallback: policy === 'fallback' ? row.fallback : {},
  }
}

/** A new hook, pre-filled with a legal combination at the first point of the first entity. */
export function blankHook(catalog: HookCatalog): HookRow {
  const first = pointOptions(catalog)[0]?.value ?? ''
  const base: HookRow = {
    k: newKey(), name: '', point: '', kind: 'pure', policy: 'fail_closed', cpu_ms: '200', rows: '0', outbound_calls: '0',
    reads: [], inputModel: '', outputModel: '', inputFields: [], outputFields: [], fallback: {},
  }
  return first ? retarget({ ...base, point: '' }, first, catalog) : base
}

/** Typing a hook name also fills the model names, until the user has chosen their own. */
export function renameHook(row: HookRow, name: string): HookRow {
  const old = autoModels(row.name)
  const next = autoModels(name)
  return {
    ...row,
    name,
    inputModel: row.inputModel === old.input ? next.input : row.inputModel,
    outputModel: row.outputModel === old.output ? next.output : row.outputModel,
  }
}

/** Entity fields a before_save hook may set (not id, not the state field). */
export const settableFields = (entity: CatalogEntity | undefined) =>
  (entity?.fields ?? []).filter((f) => f.name !== 'id' && f.name !== entity?.stateField)

export function setOutputFromEntity(row: HookRow, entity: CatalogEntity | undefined, name: string, on: boolean): HookRow {
  const without = row.outputFields.filter((f) => f.name !== name)
  return { ...row, outputFields: on ? [...without, ...fieldsFor(entity, [name])] : without }
}

export function setInputFromEntity(row: HookRow, entity: CatalogEntity | undefined, name: string, on: boolean): HookRow {
  const without = row.inputFields.filter((f) => f.name !== name)
  return { ...row, inputFields: on ? [...without, ...fieldsFor(entity, [name])] : without }
}

// ── Stub ────────────────────────────────────────────────────────────────────
export const signatureLine = (name: string, inputModel: string, outputModel: string) =>
  `def ${name}(data: ${inputModel}) -> ${outputModel}:  ${SIGNATURE_COMMENT}`

/** Exactly what the generator writes for this hook (app/core/generator/features/hooks/module.py stub_source):
 *  fixed header and signature, and the marked body region. Only the lines between the markers are the author's. */
export function stubText(h: HookBody): string {
  // kind lands in a header line: only the legal values may be written, anything else gives no stub at all.
  const kind = h.kind ?? 'pure'
  if (kind !== 'pure' && kind !== 'effect') return ''
  const models = [h.input.name, h.output.name].sort().join(', ')
  return (
    `# ${stubPath(h.name)}\n` +
    `# platform:hook ${h.name}  point=${h.point}  kind=${kind}  contract=${CONTRACT_VERSION}\n` +
    `from app.hooks_gen.contracts import ${models}\n` +
    '\n\n' +
    `${signatureLine(h.name, h.input.name, h.output.name)}\n` +
    `    # <agent:body hook=${h.name}>\n` +
    '    raise NotImplementedError\n' +
    '    # </agent:body>\n'
  )
}

/** The stub can only be shown for a hook that has the names the generator needs. */
export const stubReady = (r: HookRow) =>
  /^[a-z][a-z0-9_]*$/.test(r.name.trim()) && /^[A-Z][A-Za-z0-9]*$/.test(r.inputModel.trim()) && /^[A-Z][A-Za-z0-9]*$/.test(r.outputModel.trim()) && parsePoint(r.point) !== null && (r.kind === 'pure' || r.kind === 'effect')

// ── Client-side checks and issue mapping ─────────────────────────────────────
const NEED_INT = 'Enter a whole number'

export function hookClientErrors(rows: HookRow[]): FieldErrors {
  const out: FieldErrors = {}
  rows.forEach((r, i) => {
    for (const key of ['cpu_ms', 'rows', 'outbound_calls'] as const) {
      if (!INT.test(r[key].trim())) out[`${i}.${key}`] = NEED_INT
    }
  })
  return out
}

/** Backend path below `hooks[i]` -> the form control it belongs to. */
export function hookUiField(field: string): string {
  if (field === 'name' || field === 'point' || field === 'kind' || field === 'failure_policy') return field
  if (field.startsWith('fallback')) return 'fallback'
  if (field.startsWith('budget.')) return field.slice('budget.'.length)
  if (field.startsWith('reads')) return 'reads'
  if (field === 'input.name') return 'inputModel'
  if (field === 'output.name') return 'outputModel'
  if (field.startsWith('input.fields')) return 'inputFields'
  if (field.startsWith('output.fields')) return 'outputFields'
  return field
}

/** Group the backend's /behavior/issues messages for hooks by hook index and form control. */
export function hookIssues(issues: ValidationIssue[]): SectionIssues {
  const raw = issuesForSection('hooks', issues)
  const rows: SectionIssues['rows'] = {}
  for (const [i, r] of Object.entries(raw.rows)) {
    const fields: Record<string, string[]> = {}
    for (const [f, msgs] of Object.entries(r.fields)) (fields[hookUiField(f)] ??= []).push(...msgs)
    rows[Number(i)] = { fields, row: r.row }
  }
  return { section: raw.section, rows }
}
