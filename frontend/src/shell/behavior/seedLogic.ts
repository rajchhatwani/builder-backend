/** Pure logic for Build > Seed data (F1-6B): declared seed profile <-> API body, which generators may fill which
 *  column, generator parameter forms and the backend issue path -> form control. No React here, so it is unit-tested
 *  directly. The rules mirror app/core/validation_seed.py (GENERATORS, INJECTIVE, SEEDABLE) to keep users from picking
 *  an impossible combination; the backend validator stays the truth and its messages are shown as they come. */
import type { SeedFieldBody, SeedGeneratorBody, SeedProfileBody, StateMachineBody, ValidationIssue } from '../../api/types'
import { issuesForSection, newKey, SECRET_WORDS, type FieldErrors, type SectionIssues } from './formLogic'

export const SEEDABLE = ['string', 'text', 'integer', 'bigint', 'float', 'decimal', 'boolean', 'date', 'datetime', 'enum']
const INT_TYPES = ['integer', 'bigint']

/** generator type -> [column types it can fill, parameter keys it takes] (validation_seed.GENERATORS). */
export const GENERATORS: Record<string, { types: string[]; keys: string[]; label: string; hint: string }> = {
  constant: { types: SEEDABLE, keys: ['value'], label: 'constant', hint: 'the same value in every row' },
  one_of: { types: SEEDABLE, keys: ['values'], label: 'one_of', hint: 'a value picked from a list you give' },
  sequence: { types: ['string', 'text', ...INT_TYPES], keys: ['prefix', 'start', 'width'], label: 'sequence', hint: 'counts up: INV-00001, INV-00002 ...' },
  int_range: { types: INT_TYPES, keys: ['min', 'max'], label: 'int_range', hint: 'a whole number between min and max' },
  decimal_range: { types: ['decimal', 'float'], keys: ['min', 'max', 'places'], label: 'decimal_range', hint: 'a number between min and max' },
  date_range: { types: ['date', 'datetime'], keys: ['min', 'max'], label: 'date_range', hint: 'a date between min and max' },
  bool_ratio: { types: ['boolean'], keys: ['ratio'], label: 'bool_ratio', hint: 'true for a share of the rows' },
  words: { types: ['string', 'text'], keys: ['min_words', 'max_words'], label: 'words', hint: 'made-up words' },
  email: { types: ['string', 'text'], keys: ['prefix'], label: 'email', hint: 'unique addresses on the example.test domain' },
  reference: { types: [], keys: ['entity', 'pick'], label: 'reference', hint: 'points at a seeded row of the other entity' },
  state: { types: ['enum'], keys: ['weights'], label: 'state', hint: 'a state of the state machine, by weight' },
}
/** Usable on a unique column (validation_seed.INJECTIVE). */
const INJECTIVE = ['sequence', 'email']
const MAX_WORD_LENGTH = 7 // seed_engine.MAX_WORD_LENGTH
const NAME_RE = /^[a-z][a-z0-9_]{0,23}$/

export const looksSecret = (name: string) => SECRET_WORDS.some((w) => name.toLowerCase().includes(w))
export const isProfileName = (name: string) => NAME_RE.test(name)

// ── Catalogue (built from the entities / fields / relations / state machines APIs) ──────────
export interface SeedColumn {
  name: string
  type: string
  required: boolean
  unique: boolean
  hasDefault: boolean
  maxLength: number | null
  minValue: number | null
  maxValue: number | null
  enumValues: string[]
}
export interface SeedFk {
  column: string
  target: string
  required: boolean
  unique: boolean
}
export interface SeedEntityInfo {
  columns: SeedColumn[]
  fks: SeedFk[]
  stateField: string | null
  /** States the machine can reach from its initial state (the backend refuses weight on others). */
  reachable: string[]
}
export type SeedCatalog = Record<string, SeedEntityInfo>

export function reachableStates(machine: StateMachineBody | undefined, all: string[]): string[] {
  if (!machine) return all
  const seen = new Set<string>([machine.initial])
  let grew = true
  while (grew) {
    grew = false
    for (const t of machine.transitions ?? []) {
      if ((t.from_states ?? []).some((s) => seen.has(s)) && !seen.has(t.to_state)) {
        seen.add(t.to_state)
        grew = true
      }
    }
  }
  return all.filter((s) => seen.has(s))
}

// ── Rows ────────────────────────────────────────────────────────────────────
export interface GenRow {
  type: string
  value: string
  values: string // one per line
  prefix: string
  start: string
  width: string
  min: string
  max: string
  places: string
  ratio: string
  min_words: string
  max_words: string
  entity: string
  pick: string
  weights: Record<string, string>
}
export interface FieldPlanRow {
  k: number
  field: string
  gen: GenRow
}
export interface EntityPlanRow {
  k: number
  entity: string
  count: string
  fields: FieldPlanRow[]
}
export interface ProfileRow {
  k: number
  name: string
  seed: string
  as_of: string
  tenants: string
  entities: EntityPlanRow[]
}

const EMPTY_GEN: Omit<GenRow, 'type'> = {
  value: '', values: '', prefix: '', start: '', width: '', min: '', max: '', places: '', ratio: '',
  min_words: '', max_words: '', entity: '', pick: '', weights: {},
}

/** What a column is for the picker: a real field, or the foreign-key column of a relation. */
export type Target = { kind: 'field'; col: SeedColumn; isState: boolean } | { kind: 'fk'; fk: SeedFk }

export function targetOf(info: SeedEntityInfo | undefined, name: string): Target | null {
  const col = info?.columns.find((c) => c.name === name)
  if (col) return { kind: 'field', col, isState: info?.stateField === col.name }
  const fk = info?.fks.find((f) => f.column === name)
  return fk ? { kind: 'fk', fk } : null
}

/** The generators that can legally fill this column (so users cannot pick an impossible one). */
export function generatorsFor(t: Target): string[] {
  if (t.kind === 'fk') return ['reference']
  if (t.isState) return ['state']
  let out = Object.keys(GENERATORS).filter((g) => g !== 'state' && g !== 'reference' && GENERATORS[g].types.includes(t.col.type))
  if (t.col.unique) out = out.filter((g) => INJECTIVE.includes(g))
  if (looksSecret(t.col.name)) out = out.filter((g) => !['constant', 'one_of', 'words'].includes(g))
  return out
}

/** Columns of an entity that can get a generator and are not planned yet. */
export function plannableColumns(info: SeedEntityInfo | undefined, plan: EntityPlanRow): string[] {
  if (!info) return []
  const used = new Set(plan.fields.map((f) => f.field))
  const cols = info.columns.filter((c) => SEEDABLE.includes(c.type)).map((c) => c.name)
  return [...cols, ...info.fks.map((f) => f.column)].filter((n) => !used.has(n))
}

/** Required columns that have no generator yet (the backend: required_field_missing). The state column is filled by the machine. */
export function missingRequired(info: SeedEntityInfo | undefined, plan: EntityPlanRow): string[] {
  if (!info) return []
  const used = new Set(plan.fields.map((f) => f.field))
  const cols = info.columns.filter((c) => c.required && !c.hasDefault && c.name !== info.stateField && SEEDABLE.includes(c.type))
  return [...cols.map((c) => c.name), ...info.fks.filter((f) => f.required).map((f) => f.column)].filter((n) => !used.has(n))
}

const clip = (n: number, lo: number | null, hi: number | null) => Math.min(hi ?? n, Math.max(lo ?? n, n))

/** A sensible starting generator for a column; the user edits it. */
export function suggestGen(t: Target, ctx: { asOfYear: number }): GenRow {
  const g = (type: string, p: Partial<GenRow> = {}): GenRow => ({ ...EMPTY_GEN, type, weights: {}, ...p })
  if (t.kind === 'fk') return g('reference', { entity: t.fk.target, pick: t.fk.unique ? 'cycle' : 'random' })
  const c = t.col
  if (t.isState) return g('state', { weights: {} })
  if (c.type === 'enum') return g('one_of', { values: c.enumValues.join('\n') })
  if (c.type === 'boolean') return g('bool_ratio', { ratio: '0.5' })
  if (c.type === 'date' || c.type === 'datetime') return g('date_range', { min: `${ctx.asOfYear}-01-01`, max: `${ctx.asOfYear}-12-28` })
  if (c.type === 'decimal' || c.type === 'float')
    return g('decimal_range', { min: String(clip(10, c.minValue, c.maxValue)), max: String(clip(500, c.minValue, c.maxValue)), places: '2' })
  if (INT_TYPES.includes(c.type)) {
    if (c.unique) return g('sequence', { start: '1' })
    return g('int_range', { min: String(clip(1, c.minValue, c.maxValue)), max: String(clip(100, c.minValue, c.maxValue)) })
  }
  // string / text
  if (c.unique) return /mail/i.test(c.name) ? g('email', { prefix: 'user' }) : g('sequence', { prefix: `${c.name.replace(/[^A-Za-z0-9]/g, '').slice(0, 6)}-`, start: '1', width: '5' })
  const maxWords = c.maxLength !== null ? Math.max(1, Math.min(3, Math.floor((c.maxLength + 1) / (MAX_WORD_LENGTH + 1)))) : 3
  return g('words', { min_words: '1', max_words: String(maxWords) })
}

/** Switch the generator type of a column: the parameters of the old type are dropped, the new one starts with defaults. */
export function retypeGen(t: Target, type: string, ctx: { asOfYear: number }): GenRow {
  const base: GenRow = { ...EMPTY_GEN, type, weights: {} }
  if (t.kind === 'fk') return suggestGen(t, ctx)
  const c = t.col
  switch (type) {
    case 'constant': return { ...base, value: c.type === 'boolean' ? 'true' : c.type === 'enum' ? (c.enumValues[0] ?? '') : '' }
    case 'one_of': return { ...base, values: c.type === 'enum' ? c.enumValues.join('\n') : c.type === 'boolean' ? 'true\nfalse' : '' }
    case 'sequence': return { ...base, start: '1', ...(INT_TYPES.includes(c.type) ? {} : { prefix: '', width: '5' }) }
    case 'int_range': return { ...base, min: '1', max: '100' }
    case 'decimal_range': return { ...base, min: '0', max: '100', places: '2' }
    case 'date_range': return { ...base, min: `${ctx.asOfYear}-01-01`, max: `${ctx.asOfYear}-12-28` }
    case 'bool_ratio': return { ...base, ratio: '0.5' }
    case 'words': return { ...base, min_words: '1', max_words: '3' }
    case 'email': return { ...base, prefix: 'user' }
    default: return base
  }
}

export const blankFieldPlan = (field: string, gen: GenRow): FieldPlanRow => ({ k: newKey(), field, gen })
export const blankEntityPlan = (entity: string): EntityPlanRow => ({ k: newKey(), entity, count: '10', fields: [] })

export function blankProfile(existing: string[]): ProfileRow {
  const name = ['demo', 'dev', 'test'].find((n) => !existing.includes(n)) ?? `profile_${existing.length + 1}`
  return { k: newKey(), name, seed: '42', as_of: '2026-01-01', tenants: '0', entities: [] }
}

export const asOfYear = (asOf: string) => {
  const y = /^(\d{4})-/.exec(asOf.trim())
  return y ? Number(y[1]) : 2026
}

/** With a state generator the weights start at 1 for every state the machine can reach. */
export function withStateWeights(g: GenRow, info: SeedEntityInfo | undefined, states: string[]): GenRow {
  if (g.type !== 'state') return g
  const reach = new Set(info?.reachable ?? states)
  return { ...g, weights: Object.fromEntries(states.filter((s) => reach.has(s)).map((s) => [s, g.weights[s] ?? '1'])) }
}

// ── Body <-> row ─────────────────────────────────────────────────────────────
const INT = /^-?\d+$/
const text = (v: unknown) => (v === null || v === undefined ? '' : String(v))

/** The value a text box means for a column of that type: numbers/booleans typed, anything unparsable stays text so the backend can say why. */
export function coerce(raw: string, columnType: string): string | number | boolean {
  const t = raw.trim()
  if (INT_TYPES.includes(columnType) && INT.test(t)) return Number(t)
  if ((columnType === 'float' || columnType === 'decimal') && t !== '' && Number.isFinite(Number(t))) return Number(t)
  if (columnType === 'boolean' && (t === 'true' || t === 'false')) return t === 'true'
  return columnType === 'string' || columnType === 'text' || columnType === 'enum' || columnType === 'date' || columnType === 'datetime' ? raw : t
}

export function genFromBody(b: SeedGeneratorBody): GenRow {
  return {
    ...EMPTY_GEN, type: b.type, value: text(b.value), values: (b.values ?? []).map(text).join('\n'), prefix: text(b.prefix),
    start: text(b.start), width: text(b.width), min: text(b.min), max: text(b.max), places: text(b.places), ratio: text(b.ratio),
    min_words: text(b.min_words), max_words: text(b.max_words), entity: text(b.entity), pick: text(b.pick),
    weights: Object.fromEntries(Object.entries(b.weights ?? {}).map(([s, w]) => [s, String(w)])),
  }
}

const num = (s: string) => (INT.test(s.trim()) ? Number(s.trim()) : undefined)

/** Only the keys the generator type takes are sent (the backend refuses the others). */
export function genToBody(g: GenRow, columnType: string): SeedGeneratorBody {
  const out: SeedGeneratorBody = { type: g.type }
  switch (g.type) {
    case 'constant': if (g.value.trim() !== '' || columnType === 'string' || columnType === 'text') out.value = coerce(g.value, columnType); break
    case 'one_of': out.values = g.values.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => coerce(l, columnType)); break
    case 'sequence': {
      const start = num(g.start)
      if (start !== undefined) out.start = start
      if (!INT_TYPES.includes(columnType)) {
        out.prefix = g.prefix
        const w = num(g.width)
        if (w !== undefined) out.width = w
      }
      break
    }
    case 'int_range': if (g.min.trim()) out.min = coerce(g.min, 'integer') as string | number; if (g.max.trim()) out.max = coerce(g.max, 'integer') as string | number; break
    case 'decimal_range': {
      if (g.min.trim()) out.min = g.min.trim() // decimals are text: "10.50"
      if (g.max.trim()) out.max = g.max.trim()
      const p = num(g.places)
      if (p !== undefined) out.places = p
      break
    }
    case 'date_range': if (g.min.trim()) out.min = g.min.trim(); if (g.max.trim()) out.max = g.max.trim(); break
    case 'bool_ratio': if (g.ratio.trim() !== '' && Number.isFinite(Number(g.ratio))) out.ratio = Number(g.ratio); break
    case 'words': {
      const lo = num(g.min_words), hi = num(g.max_words)
      if (lo !== undefined) out.min_words = lo
      if (hi !== undefined) out.max_words = hi
      break
    }
    case 'email': if (g.prefix !== '') out.prefix = g.prefix; break
    case 'reference': out.entity = g.entity; if (g.pick) out.pick = g.pick; break
    case 'state': out.weights = Object.fromEntries(Object.entries(g.weights).filter(([, w]) => num(w) !== undefined).map(([s, w]) => [s, Number(w.trim())])); break
  }
  return out
}

/** Column types by (entity, field) are needed to type values; `types` maps `Entity.field` -> type. */
export type ColumnTypes = Record<string, string>
export const columnTypes = (catalog: SeedCatalog): ColumnTypes =>
  Object.fromEntries(Object.entries(catalog).flatMap(([e, i]) => i.columns.map((c) => [`${e}.${c.name}`, c.type])))

export function profileFromBody(b: SeedProfileBody): ProfileRow {
  return {
    k: newKey(), name: b.name, seed: String(b.seed), as_of: b.as_of, tenants: String(b.tenants ?? 0),
    entities: (b.entities ?? []).map((e) => ({
      k: newKey(), entity: e.entity, count: String(e.count),
      fields: (e.fields ?? []).map((f) => ({ k: newKey(), field: f.field, gen: genFromBody(f.generator) })),
    })),
  }
}

export function profileToBody(r: ProfileRow, types: ColumnTypes = {}): SeedProfileBody {
  return {
    name: r.name, seed: num(r.seed) ?? 0, as_of: r.as_of.trim(), tenants: num(r.tenants) ?? 0,
    entities: r.entities.map((e) => ({
      entity: e.entity, count: num(e.count) ?? 0,
      fields: e.fields.map((f): SeedFieldBody => ({ field: f.field, generator: genToBody(f.gen, types[`${e.entity}.${f.field}`] ?? 'string') })),
    })),
  }
}

// ── Client checks (shape only; limits and meaning are the backend's) ─────────
const NEED_INT = 'Enter a whole number'
export function seedClientErrors(rows: ProfileRow[]): FieldErrors {
  const out: FieldErrors = {}
  rows.forEach((p, i) => {
    if (!INT.test(p.seed.trim())) out[`${i}.seed`] = NEED_INT
    if (!INT.test(p.tenants.trim())) out[`${i}.tenants`] = NEED_INT
    p.entities.forEach((e, j) => {
      if (!INT.test(e.count.trim())) out[`${i}.entities.${j}.count`] = NEED_INT
      e.fields.forEach((f, k) => {
        const base = `${i}.entities.${j}.fields.${k}.generator`
        const g = f.gen
        for (const key of ['start', 'width', 'places', 'min_words', 'max_words'] as const) {
          if (GENERATORS[g.type]?.keys.includes(key) && g[key].trim() !== '' && !INT.test(g[key].trim())) out[`${base}.${key}`] = NEED_INT
        }
        if (g.type === 'bool_ratio' && g.ratio.trim() !== '' && !Number.isFinite(Number(g.ratio))) out[`${base}.ratio`] = 'Enter a number from 0 to 1'
        if (g.type === 'state') for (const [s, w] of Object.entries(g.weights)) if (w.trim() !== '' && !INT.test(w.trim())) out[`${base}.weights.${s}`] = NEED_INT
      })
    })
  })
  return out
}

// ── Backend issues ────────────────────────────────────────────────────────────
/** `entities[1].fields[2].generator.values[3]` -> `entities.1.fields.2.generator.values` (one control per list). */
export const normalizeKey = (rest: string) => rest.replace(/\[(\d+)\]/g, '.$1').replace(/\.values\.\d+$/, '.values')

export function seedIssues(issues: ValidationIssue[]): SectionIssues {
  const raw = issuesForSection('seed', issues)
  const rows: SectionIssues['rows'] = {}
  for (const [i, r] of Object.entries(raw.rows)) {
    const fields: Record<string, string[]> = {}
    for (const [f, msgs] of Object.entries(r.fields)) (fields[normalizeKey(f)] ??= []).push(...msgs)
    rows[Number(i)] = { fields, row: r.row }
  }
  return { section: raw.section, rows }
}

/** Keys the form uses for the controls of plan j / field k. */
export const planKey = (j: number, part: string) => `entities.${j}.${part}`
export const fieldKey = (j: number, k: number, part: string) => `entities.${j}.fields.${k}.${part}`

// ── How to run it ────────────────────────────────────────────────────────────
export function runCommands(name: string) {
  return {
    seed: `python -m app.seed --profile ${name}`,
    reset: `python -m app.seed --profile ${name} --reset`,
    check: 'python -m app.seed --check',
  }
}
export const GUARD_NOTE = 'Seeding refuses production-like environments: APP_ENV (and ENVIRONMENT, when set) must name a development one, for example APP_ENV=development.'
