/** Pure logic of the Workbench (F2-5): which origin may be called, operations from an OpenAPI document,
 *  payload generation from JSON Schema, and redaction for the in-memory request history.
 *  SECURITY: nothing here touches storage; tokens never pass through this file's history types. */

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json }
type Obj = Record<string, unknown>

export const METHODS = ['get', 'post', 'put', 'patch', 'delete'] as const
export type Method = (typeof METHODS)[number]
export const MAX_RESPONSE_CHARS = 200_000
export const MAX_HISTORY = 30
export const REQUEST_TIMEOUT_MS = 15_000

const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)

/** The only origin the console may call: the generated preview API. Returns null when unset/invalid.
 *  Only http(s) with no credentials; path, query and hash are dropped. `forbidden` (the builder API origin)
 *  is refused so a role token is never sent to the builder itself. */
export function resolvePreviewOrigin(raw: string | undefined, forbidden: string[] = []): string | null {
  if (!raw) return null
  try {
    const u = new URL(raw)
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null
    if (u.username || u.password) return null
    if (forbidden.some((f) => safeOrigin(f) === u.origin)) return null
    return u.origin
  } catch {
    return null
  }
}

function safeOrigin(u: string): string | null {
  try {
    return new URL(u).origin
  } catch {
    return null
  }
}

export interface PathParam { name: string; in: 'path' | 'query'; required: boolean; schema: Obj }
export interface Operation {
  id: string
  method: Method
  path: string
  summary: string
  params: PathParam[]
  /** JSON request body schema (already $ref-resolved at one level by `generatePayload`), if any. */
  bodySchema: Obj | null
}

/** Operations of an OpenAPI 3 document. Keys come from the document, so only the five allowed methods
 *  and paths that start with a single "/" are listed (anything else is ignored). */
export function parseOperations(doc: unknown): Operation[] {
  if (!isObj(doc) || !isObj(doc.paths)) return []
  const out: Operation[] = []
  for (const path of Object.keys(doc.paths)) {
    if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\') || path.includes('..')) continue
    const item = (doc.paths as Obj)[path]
    if (!isObj(item)) continue
    const shared = Array.isArray(item.parameters) ? item.parameters : []
    for (const method of METHODS) {
      const op = item[method]
      if (!isObj(op)) continue
      const params = [...shared, ...(Array.isArray(op.parameters) ? op.parameters : [])]
        .map((p) => deref(doc, p))
        .filter((p): p is Obj => isObj(p) && (p.in === 'path' || p.in === 'query') && typeof p.name === 'string')
        .map((p) => ({
          name: String(p.name),
          in: p.in as 'path' | 'query',
          required: p.in === 'path' || p.required === true,
          schema: isObj(p.schema) ? p.schema : {},
        }))
      out.push({
        id: `${method.toUpperCase()} ${path}`,
        method,
        path,
        summary: typeof op.summary === 'string' ? op.summary : '',
        params,
        bodySchema: bodySchemaOf(doc, op),
      })
    }
  }
  return out
}

function bodySchemaOf(doc: Obj, op: Obj): Obj | null {
  const rb = deref(doc, op.requestBody)
  if (!isObj(rb) || !isObj(rb.content)) return null
  const json = (rb.content as Obj)['application/json']
  return isObj(json) && isObj(json.schema) ? json.schema : null
}

/** Resolve a local "#/..." reference; any other ref (remote, odd) resolves to undefined. */
export function deref(doc: Obj, node: unknown, depth = 0): unknown {
  let cur = node
  for (let i = 0; i < 16 && isObj(cur) && typeof cur.$ref === 'string'; i++) {
    const ref = cur.$ref
    if (!ref.startsWith('#/')) return undefined
    let target: unknown = doc
    for (const raw of ref.slice(2).split('/')) {
      const key = raw.replace(/~1/g, '/').replace(/~0/g, '~')
      if (key === '__proto__' || key === 'constructor' || key === 'prototype') return undefined
      if (!isObj(target) || !Object.prototype.hasOwnProperty.call(target, key)) return undefined
      target = target[key]
    }
    cur = target
  }
  return depth > 16 ? undefined : cur
}

/** Build the request URL. Throws when the result would leave `origin` (defence in depth: the path comes
 *  from a document, the origin from config). */
export function buildRequestUrl(origin: string, path: string, values: Record<string, string>, params: PathParam[]): string {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\')) throw new Error('Refusing a path that is not relative to the preview API')
  let p = path
  for (const prm of params.filter((x) => x.in === 'path')) {
    const v = values[prm.name] ?? ''
    if (!v) throw new Error(`Path parameter "${prm.name}" is required`)
    p = p.split(`{${prm.name}}`).join(encodeURIComponent(v))
  }
  if (/\{[^}]*\}/.test(p)) throw new Error('Path has parameters that are not filled in')
  const url = new URL(origin + p)
  for (const prm of params.filter((x) => x.in === 'query')) {
    const v = values[prm.name]
    if (v) url.searchParams.set(prm.name, v)
  }
  if (url.origin !== origin) throw new Error('Refusing a URL outside the preview API origin')
  return url.toString()
}

// ── payload generation ───────────────────────────────────────────────────────

const MAX_GEN_DEPTH = 8

function genValue(doc: Obj, schema: unknown, depth: number): Json {
  const s = deref(doc, schema)
  if (!isObj(s) || depth > MAX_GEN_DEPTH) return null
  if ('example' in s) return s.example as Json
  if ('default' in s) return s.default as Json
  if (Array.isArray(s.enum) && s.enum.length) return s.enum[0] as Json
  if ('const' in s) return s.const as Json
  const alt = (s.oneOf ?? s.anyOf) as unknown
  if (Array.isArray(alt) && alt.length) {
    const first = alt.map((a) => deref(doc, a)).find((a) => isObj(a) && a.type !== 'null') ?? alt[0]
    return genValue(doc, first, depth + 1)
  }
  if (Array.isArray(s.allOf)) {
    const merged: Obj = {}
    for (const part of s.allOf) {
      const r = deref(doc, part)
      if (isObj(r)) {
        Object.assign(merged, r, {
          properties: { ...(isObj(merged.properties) ? merged.properties : {}), ...(isObj(r.properties) ? r.properties : {}) },
          required: [...(Array.isArray(merged.required) ? merged.required : []), ...(Array.isArray(r.required) ? r.required : [])],
        })
      }
    }
    return genValue(doc, merged, depth + 1)
  }
  const type = Array.isArray(s.type) ? (s.type.find((t) => t !== 'null') ?? 'null') : s.type
  switch (type) {
    case 'string': return genString(s)
    case 'integer': return numBound(s, true)
    case 'number': return numBound(s, false)
    case 'boolean': return false
    case 'array': {
      const n = Math.min(Math.max(typeof s.minItems === 'number' ? s.minItems : 0, 0), 3)
      return Array.from({ length: n }, () => genValue(doc, s.items, depth + 1))
    }
    case 'object':
    case undefined: {
      if (!isObj(s.properties)) return type === 'object' ? {} : null
      const required = new Set(Array.isArray(s.required) ? s.required.map(String) : [])
      const out: { [k: string]: Json } = Object.create(null)
      for (const k of Object.keys(s.properties)) {
        if (k === '__proto__') continue
        if (required.has(k)) out[k] = genValue(doc, (s.properties as Obj)[k], depth + 1)
      }
      return Object.assign({}, out)
    }
    default: return null
  }
}

function numBound(s: Obj, int: boolean): number {
  const min = typeof s.minimum === 'number' ? s.minimum : typeof s.exclusiveMinimum === 'number' ? s.exclusiveMinimum + (int ? 1 : 0.1) : undefined
  const max = typeof s.maximum === 'number' ? s.maximum : undefined
  let v = min ?? 0
  if (max !== undefined && v > max) v = max
  return int ? Math.ceil(v) : v
}

function genString(s: Obj): string {
  switch (s.format) {
    case 'email': return 'user@example.com'
    case 'uuid': return '00000000-0000-4000-8000-000000000000'
    case 'date': return '2026-01-31'
    case 'date-time': return '2026-01-31T12:00:00Z'
    case 'uri': case 'url': return 'https://example.com/'
    default: break
  }
  const min = typeof s.minLength === 'number' ? Math.min(s.minLength, 200) : 1
  const max = typeof s.maxLength === 'number' ? s.maxLength : Infinity
  return 'a'.repeat(Math.max(1, Math.min(min, max)))
}

/** `valid`: required fields only, satisfying simple constraints. `invalid`: a copy of the valid payload that
 *  breaks one rule (drops a required field, else flips the first field's type) so error responses can be tried. */
export function generatePayload(doc: unknown, schema: unknown, mode: 'valid' | 'invalid'): Json {
  const root = isObj(doc) ? doc : {}
  const valid = genValue(root, schema, 0)
  if (mode === 'valid') return valid
  const s = deref(root, schema)
  if (isObj(valid) && isObj(s)) {
    const keys = Object.keys(valid)
    const copy: { [k: string]: Json } = { ...valid }
    if (keys.length) {
      delete copy[keys[0]]
      if (!Object.keys(copy).length) copy.unexpected_field = 12345
      return copy
    }
    return { unexpected_field: 12345 }
  }
  return typeof valid === 'string' ? 12345 : 'not-valid'
}

// ── redaction & history ──────────────────────────────────────────────────────

const SECRET_KEY = /(pass(word|wd|code)?|secret|token|jwt|bearer|otp|pin|auth|credential|cookie|session|private|signature|(^|[-_.])key($|[-_.])|api[-_]?key|access[-_]?key|[a-z]Key$)/i
const JWT_ONE = /\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*/
const JWT = /\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*/g

/** A path with its query: values of secret-looking parameters are replaced. */
export function redactPath(pathAndQuery: string): string {
  const i = pathAndQuery.indexOf('?')
  if (i < 0) return pathAndQuery
  const q = new URLSearchParams(pathAndQuery.slice(i + 1))
  const out: string[] = []
  for (const [k, v] of q) out.push(`${encodeURIComponent(k)}=${SECRET_KEY.test(k) || JWT_ONE.test(v) ? '[redacted]' : encodeURIComponent(v)}`)
  return pathAndQuery.slice(0, i) + (out.length ? `?${out.join('&')}` : '')
}

/** Replace the value of secret-looking keys, deeply. Pure; returns a new value. */
export function redactJson(v: unknown, depth = 0): Json {
  if (depth > 12) return '[truncated]'
  if (Array.isArray(v)) return v.map((x) => redactJson(x, depth + 1))
  if (isObj(v)) {
    const out: { [k: string]: Json } = {}
    for (const k of Object.keys(v)) {
      if (k === '__proto__') continue
      out[k] = SECRET_KEY.test(k) ? '[redacted]' : redactJson(v[k], depth + 1)
    }
    return out
  }
  return v as Json
}

/** Redact a text body: JSON is redacted by key, anything else is kept only if short and never echoes bearer values. */
export function redactBodyText(text: string): string {
  try {
    return JSON.stringify(redactJson(JSON.parse(text)), null, 2)
  } catch {
    return text
      .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [redacted]')
      .replace(JWT, '[redacted]')
      .replace(/([A-Za-z0-9_.-]+)(\s*[=:]\s*)("?)([^\s&",;]+)/g, (m, k: string, sep: string, q: string) => (SECRET_KEY.test(k) ? `${k}${sep}${q}[redacted]` : m))
      .slice(0, 2000)
  }
}

export interface HistoryEntry {
  id: number
  at: string
  method: string
  path: string
  role: string
  status: number | null
  ms: number
  /** Always shows the header as redacted: the token itself is never stored. */
  authorization: 'none' | '[redacted]'
  requestBody: string
  responseBody: string
  error: string
}

/** Newest first, capped. Pure. */
export function pushHistory(list: HistoryEntry[], entry: HistoryEntry, max = MAX_HISTORY): HistoryEntry[] {
  return [entry, ...list].slice(0, max)
}

/** Text shown for a response: pretty JSON when it parses, else raw, capped. Always plain text. */
export function formatResponseText(raw: string): string {
  const capped = raw.length > MAX_RESPONSE_CHARS ? raw.slice(0, MAX_RESPONSE_CHARS) + '\n… truncated' : raw
  try {
    return JSON.stringify(JSON.parse(capped), null, 2)
  } catch {
    return capped
  }
}
