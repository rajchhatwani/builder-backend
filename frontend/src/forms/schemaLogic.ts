import type { JsonSchema, PathErrors, UiHint } from './types'

export type Path = (string | number)[]
export const pathKey = (p: Path) => p.join('.')

/** A schema with $ref / allOf-wrapped refs / nullable anyOf folded in. */
export interface Resolved extends JsonSchema {
  nullable?: boolean
  /** More than one non-null branch (e.g. str | int | bool): rendered as free text. */
  mixed?: boolean
  /** Cyclic $ref chain or nesting beyond MAX_DEPTH: rendered as an inline message, never recursed into. */
  tooDeep?: boolean
}

export const MAX_DEPTH = 16
export const TOO_DEEP_MSG = 'Schema too deep or cyclic: this field cannot be rendered.'
/** Never run a backend-supplied pattern against longer input than this (ReDoS guard). */
export const MAX_PATTERN_INPUT = 10_000

function deref(root: JsonSchema, ref: string): JsonSchema {
  const m = ref.match(/^#\/\$defs\/(.+)$/)
  const found = m ? root.$defs?.[m[1]] : undefined
  if (!found) throw new Error(`Unsupported or missing $ref ${ref}`)
  return found
}

export function resolve(root: JsonSchema, s: JsonSchema, depth = 0, seen: readonly string[] = []): Resolved {
  if (depth > MAX_DEPTH) return { tooDeep: true }
  let out: Resolved = { ...s }
  if (out.$ref) {
    const { $ref, ...rest } = out
    if (seen.includes($ref)) return { tooDeep: true }
    out = { ...resolve(root, deref(root, $ref), depth + 1, [...seen, $ref]), ...rest }
  }
  if (out.allOf?.length === 1) {
    const { allOf, ...rest } = out
    out = { ...resolve(root, allOf[0], depth + 1, seen), ...rest }
  }
  if (out.anyOf) {
    const { anyOf, ...rest } = out
    const branches = anyOf.map((b) => resolve(root, b, depth + 1, seen))
    const real = branches.filter((b) => b.type !== 'null')
    const nullable = real.length < branches.length
    out = real.length === 1 ? { ...real[0], ...rest, nullable } : { ...rest, type: 'string', nullable, mixed: true }
  }
  return out
}

export const humanize = (key: string) => {
  const t = key.replace(/_/g, ' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}

export function uiOf(s: JsonSchema | Resolved): UiHint {
  return s['x-ui'] ?? {}
}

/** Property names of an object schema in display order. */
export function orderedKeys(s: Resolved): string[] {
  const keys = Object.keys(s.properties ?? {})
  const order = (uiOf(s).order ?? []).filter((k) => keys.includes(k))
  return [...order, ...keys.filter((k) => !order.includes(k))]
}

/** The value a freshly added row / empty field starts with, from the schema's defaults. */
export function defaultFor(root: JsonSchema, schema: JsonSchema, depth = 0): unknown {
  const s = resolve(root, schema)
  if (s.tooDeep || depth > MAX_DEPTH) return undefined
  if (s.default !== undefined) return structuredClone(s.default)
  if (s.nullable) return null
  switch (s.type) {
    case 'object': {
      const o: Record<string, unknown> = {}
      for (const [k, p] of Object.entries(s.properties ?? {})) {
        const v = defaultFor(root, p, depth + 1)
        if (v !== undefined) o[k] = v
      }
      return o
    }
    case 'array':
      return []
    case 'boolean':
      return false
    case 'string':
      return s.enum ? s.enum[0] : ''
    default:
      return undefined
  }
}

export function isShown(hint: UiHint, siblings: Record<string, unknown> | undefined, siblingDefaults?: (k: string) => unknown): boolean {
  if (hint.hidden) return false
  const w = hint.showWhen
  if (!w) return true
  const raw = siblings?.[w.field]
  const v = raw === undefined ? siblingDefaults?.(w.field) : raw
  return w.in ? w.in.includes(v) : v === w.equals
}

const isEmpty = (v: unknown) => v === undefined || v === null || v === ''

/** Pydantic's wording for the same constraint, so a client hint and the backend's message are the same text. */
export const MSG = {
  required: 'Field required',
  integer: 'Input should be a valid integer',
  number: 'Input should be a valid number',
  ge: (n: number) => `Input should be greater than or equal to ${n}`,
  le: (n: number) => `Input should be less than or equal to ${n}`,
  gt: (n: number) => `Input should be greater than ${n}`,
  lt: (n: number) => `Input should be less than ${n}`,
  minLen: (n: number) => `String should have at least ${n} character${n === 1 ? '' : 's'}`,
  maxLen: (n: number) => `String should have at most ${n} character${n === 1 ? '' : 's'}`,
  pattern: (p: string) => `String should match pattern '${p}'`,
  minItems: (n: number, got: number) => `List should have at least ${n} item${n === 1 ? '' : 's'} after validation, not ${got}`,
  maxItems: (n: number, got: number) => `List should have at most ${n} item${n === 1 ? '' : 's'} after validation, not ${got}`,
}

/** Immediate hints for one scalar value, from the schema keywords only. First failing keyword wins. */
export function scalarHint(s: Resolved, value: unknown, required: boolean): string | null {
  if (isEmpty(value)) return required && !s.nullable ? MSG.required : null
  if (s.type === 'integer' || s.type === 'number') {
    if (typeof value !== 'number' || Number.isNaN(value)) return s.type === 'integer' ? MSG.integer : MSG.number
    if (s.type === 'integer' && !Number.isInteger(value)) return MSG.integer
    if (s.minimum !== undefined && value < s.minimum) return MSG.ge(s.minimum)
    if (s.maximum !== undefined && value > s.maximum) return MSG.le(s.maximum)
    if (s.exclusiveMinimum !== undefined && value <= s.exclusiveMinimum) return MSG.gt(s.exclusiveMinimum)
    if (s.exclusiveMaximum !== undefined && value >= s.exclusiveMaximum) return MSG.lt(s.exclusiveMaximum)
  }
  if (s.type === 'string' && typeof value === 'string') {
    if (s.minLength !== undefined && value.length < s.minLength) return MSG.minLen(s.minLength)
    if (s.maxLength !== undefined && value.length > s.maxLength) return MSG.maxLen(s.maxLength)
    if (s.pattern && typeof s.pattern === 'string' && value.length <= MAX_PATTERN_INPUT) {
      try {
        if (!new RegExp(s.pattern).test(value)) return MSG.pattern(s.pattern)
      } catch {
        /* Python-only regex syntax: leave it to the backend */
      }
    }
  }
  return null
}

/** Client-side hints for a whole value, keyed by path. Hidden (showWhen) fields are skipped. */
export function validateValue(root: JsonSchema, schema: JsonSchema, value: unknown, path: Path = [], required = true, out: PathErrors = Object.create(null)): PathErrors {
  const s = resolve(root, schema)
  if (s.tooDeep || path.length > MAX_DEPTH) return out
  const key = pathKey(path)
  const put = (m: string | null) => {
    if (m) out[key] = [m]
  }
  if (s.type === 'object' && s.properties) {
    // An optional (nullable) object that is not set has no required children to check (F2-2: payments.payable).
    if (s.nullable && (value === null || value === undefined)) return out
    const obj = (value ?? {}) as Record<string, unknown>
    for (const k of orderedKeys(s)) {
      const child = s.properties[k]
      if (!isShown(uiOf(child), obj, (f) => (s.properties![f] ? defaultFor(root, s.properties![f]) : undefined))) continue
      validateValue(root, child, obj[k], [...path, k], !!s.required?.includes(k), out)
    }
  } else if (s.type === 'array') {
    const arr = Array.isArray(value) ? value : []
    if (s.minItems !== undefined && arr.length < s.minItems) put(MSG.minItems(s.minItems, arr.length))
    else if (s.maxItems !== undefined && arr.length > s.maxItems) put(MSG.maxItems(s.maxItems, arr.length))
    if (s.items && uiOf(s).widget !== 'csv') arr.forEach((item, i) => validateValue(root, s.items!, item, [...path, i], true, out))
  } else if (s.type !== 'boolean') {
    put(scalarHint(s, value, required))
  }
  return out
}

const UNSAFE_SEGMENTS = new Set(['__proto__', 'constructor', 'prototype'])
const MAX_SEGMENT = 200
const MAX_LOC = 32

/** Backend (FastAPI 422) `detail` entries -> messages by path, text untouched. `loc` starts with 'body'.
 *  Locations are untrusted: the result has a null prototype, dangerous segments are neutralised, nothing throws. */
export function issuesFromDetail(detail: unknown): PathErrors {
  const out: PathErrors = Object.create(null)
  if (!Array.isArray(detail)) return out
  for (const d of detail as unknown[]) {
    const e = d as { loc?: unknown; msg?: unknown } | null
    if (typeof e?.msg !== 'string') continue
    const raw = Array.isArray(e.loc) ? e.loc.slice(0, MAX_LOC) : []
    const loc = raw
      .filter((x, i) => !(i === 0 && x === 'body'))
      .map((x) => {
        const s = typeof x === 'string' || typeof x === 'number' ? String(x) : ''
        const c = s.length > MAX_SEGMENT ? s.slice(0, MAX_SEGMENT) : s
        return UNSAFE_SEGMENTS.has(c) ? `_${c}` : c
      })
    const key = loc.join('.')
    ;(out[key] ??= []).push(e.msg)
  }
  return out
}

/** CSV widget helpers. */
export const csvToList = (t: string) => t.split(',').map((x) => x.trim()).filter(Boolean)
export const listToCsv = (v: unknown) => (Array.isArray(v) ? v.join(', ') : '')
