/** API platform logic: the `api_platform` spec block (app/core/spec_models.py SpecApiPlatform), the generated /platform answers, checks. */
import type { PreviewSession } from '../preview/previewSession'

export type Raw = Record<string, unknown>
const isObj = (v: unknown): v is Raw => !!v && typeof v === 'object' && !Array.isArray(v)
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])
const arr = (v: unknown): Raw[] => (Array.isArray(v) ? v.filter(isObj) : [])
const str = (v: unknown): string | null => (typeof v === 'string' ? v : null)

export const parseList = (t: string): string[] => t.split(',').map((s) => s.trim()).filter(Boolean)
export const listText = (v: string[]): string => v.join(', ')
let seq = 0
export const nextKey = () => ++seq

// ── Settings form ──────────────────────────────────────────────────────────
export interface EntityRow { k: number; entity: string; fields: string[]; sandbox: boolean }
export interface AppRow { k: number; name: string; title: string; scopes: string[]; events: string[] }
export interface Draft {
  enabled: boolean
  roles: string[]
  entities: EntityRow[]
  rateLimit: string
  sandboxRateLimit: string
  ttl: string
  apps: AppRow[]
}
const MANAGED = ['enabled', 'roles', 'entities', 'rate_limit', 'sandbox_rate_limit', 'key_ttl_days', 'apps']

export function draftFrom(raw: Raw | null): Draft {
  const r = raw ?? {}
  return {
    enabled: r.enabled === true,
    roles: strs(r.roles),
    entities: arr(r.entities).map((x) => ({ k: nextKey(), entity: String(x.entity ?? ''), fields: strs(x.fields), sandbox: x.sandbox === true })),
    rateLimit: typeof r.rate_limit === 'string' ? r.rate_limit : '60/minute',
    sandboxRateLimit: typeof r.sandbox_rate_limit === 'string' ? r.sandbox_rate_limit : '20/minute',
    ttl: r.key_ttl_days === undefined ? '90' : String(r.key_ttl_days),
    apps: arr(r.apps).map((x) => ({ k: nextKey(), name: String(x.name ?? ''), title: typeof x.title === 'string' ? x.title : '', scopes: strs(x.scopes), events: strs(x.events) })),
  }
}

/** The block sent to PUT /behavior/api_platform. Keys this form does not manage are carried over unchanged. */
export function toBlock(d: Draft, raw: Raw | null): Raw {
  const kept = Object.fromEntries(Object.entries(raw ?? {}).filter(([k]) => !MANAGED.includes(k)))
  return {
    ...kept,
    enabled: d.enabled,
    roles: d.roles,
    entities: d.entities.map((e) => ({ entity: e.entity.trim(), fields: e.fields, sandbox: e.sandbox })),
    rate_limit: d.rateLimit.trim(),
    sandbox_rate_limit: d.sandboxRateLimit.trim(),
    key_ttl_days: Number(d.ttl),
    apps: d.apps.map((a) => ({ name: a.name.trim(), title: a.title.trim(), scopes: a.scopes, events: a.events })),
  }
}

/** Same rule as the server (app/core/validation_api_platform.py LIMIT): 60/minute, 5/2hours. */
export const LIMIT = /^[1-9]\d{0,6}\/([1-9]\d{0,3})?(second|minute|hour|day)s?$/
export const SLUG = /^[a-z][a-z0-9_-]{0,39}$/
export const MAX_APPS = 32
export const MAX_ENTITIES = 64

/** Client checks; keys are `ent.<k>.fields` style so the form can show each next to its field. */
export function checkDraft(d: Draft): Record<string, string> {
  const e: Record<string, string> = {}
  if (!LIMIT.test(d.rateLimit.trim())) e.rateLimit = 'Use a limit like 60/minute (second, minute, hour or day).'
  if (!LIMIT.test(d.sandboxRateLimit.trim())) e.sandboxRateLimit = 'Use a limit like 20/minute (second, minute, hour or day).'
  if (!/^\d+$/.test(d.ttl.trim()) || Number(d.ttl) < 1 || Number(d.ttl) > 365) e.ttl = 'Days must be a whole number from 1 to 365.'
  if (d.entities.length > MAX_ENTITIES) e.entities = `At most ${MAX_ENTITIES} public entities.`
  if (d.apps.length > MAX_APPS) e.apps = `At most ${MAX_APPS} apps.`
  const seenEnt = new Set<string>()
  for (const x of d.entities) {
    const n = x.entity.trim()
    if (!n) e[`ent.${x.k}.entity`] = 'Name the entity.'
    else if (seenEnt.has(n)) e[`ent.${x.k}.entity`] = `${n} is listed twice.`
    seenEnt.add(n)
    if (x.fields.length === 0) e[`ent.${x.k}.fields`] = 'List the fields the public API returns (nothing is shared by default).'
    else if (new Set(x.fields).size !== x.fields.length) e[`ent.${x.k}.fields`] = 'A field is listed twice.'
  }
  const seenApp = new Set<string>()
  for (const a of d.apps) {
    const n = a.name.trim()
    if (!SLUG.test(n)) e[`app.${a.k}.name`] = 'Use a slug: lowercase letters, digits, - and _, starting with a letter.'
    else if (seenApp.has(n)) e[`app.${a.k}.name`] = `${n} is listed twice.`
    seenApp.add(n)
    if (a.scopes.length === 0) e[`app.${a.k}.scopes`] = 'An app asks for at least one entity.'
    if (a.events.some((v) => !SLUG.test(v))) e[`app.${a.k}.events`] = 'Event types are slugs (lowercase letters, digits, - and _).'
  }
  return e
}

/** Messages of the server's validator that concern the api_platform block, one line each. */
export function platformIssues(issues: { path: string; message: string }[]): string[] {
  return issues.filter((i) => i.path === 'api_platform' || i.path.startsWith('api_platform.') || i.path.startsWith('api_platform[')).map((i) => `${i.path}: ${i.message}`)
}

/** Issues in the error body of a refused save (422 details), when the server lists them. */
export function detailLines(details: unknown[]): string[] {
  return details.map((d) => {
    if (typeof d === 'string') return d
    if (isObj(d) && typeof d.message === 'string') return typeof d.path === 'string' ? `${d.path}: ${d.message}` : d.message
    if (isObj(d) && typeof d.msg === 'string') return Array.isArray(d.loc) ? `${d.loc.join('.')}: ${d.msg}` : d.msg
    return ''
  }).filter(Boolean)
}

// ── Generated app: /platform answers ──────────────────────────────────────
export interface CatalogueEntity { entity: string; fields: string[]; sandbox: boolean }
export interface Catalogue { entities: CatalogueEntity[]; rate_limit: string; sandbox_rate_limit: string; key_ttl_days: number }
export type KeyStatus = 'active' | 'revoked' | 'expired'
export interface KeyRow {
  id: string; name: string; prefix: string; kind: string; app: string | null; environment: string; scopes: string[]
  created_at: string; expires_at: string; revoked_at: string | null; last_used_at: string | null; status: KeyStatus
}
export interface KeyCreated { id: string; name: string; prefix: string; environment: string; scopes: string[]; expires_at: string; key: string }
export interface AppItem {
  name: string; title: string; scopes: string[]; events: string[]; installed: boolean
  installation_id: string | null; granted_scopes: string[]; installed_at: string | null
}
export interface Installed { installation_id: string; app: string; granted_scopes: string[]; token: string; signing_secret: string }
export interface AuditRow { id: string; at: string; actor: string; action: string; target: string | null; detail: Raw }

const STATUSES = new Set(['active', 'revoked', 'expired'])

export function readCatalogue(j: unknown): Catalogue | null {
  if (!isObj(j) || !Array.isArray(j.entities)) return null
  const entities: CatalogueEntity[] = []
  for (const e of j.entities) {
    if (!isObj(e) || typeof e.entity !== 'string') return null
    entities.push({ entity: e.entity, fields: strs(e.fields), sandbox: e.sandbox === true })
  }
  return {
    entities,
    rate_limit: str(j.rate_limit) ?? '',
    sandbox_rate_limit: str(j.sandbox_rate_limit) ?? '',
    key_ttl_days: typeof j.key_ttl_days === 'number' ? j.key_ttl_days : 365,
  }
}

function keyRow(k: unknown): KeyRow | null {
  if (!isObj(k) || typeof k.id !== 'string' || typeof k.name !== 'string' || typeof k.status !== 'string' || !STATUSES.has(k.status)) return null
  return {
    id: k.id, name: k.name, prefix: str(k.prefix) ?? '', kind: str(k.kind) ?? 'key', app: str(k.app), environment: str(k.environment) ?? '', scopes: strs(k.scopes),
    created_at: str(k.created_at) ?? '', expires_at: str(k.expires_at) ?? '', revoked_at: str(k.revoked_at), last_used_at: str(k.last_used_at), status: k.status as KeyStatus,
  }
}
export function readKeys(j: unknown): KeyRow[] | null {
  if (!Array.isArray(j)) return null
  const out: KeyRow[] = []
  for (const k of j) { const r = keyRow(k); if (!r) return null; out.push(r) }
  return out
}
export const readKey = keyRow

export function readKeyCreated(j: unknown): KeyCreated | null {
  if (!isObj(j) || typeof j.id !== 'string' || typeof j.key !== 'string' || !j.key) return null
  return { id: j.id, name: str(j.name) ?? '', prefix: str(j.prefix) ?? '', environment: str(j.environment) ?? '', scopes: strs(j.scopes), expires_at: str(j.expires_at) ?? '', key: j.key }
}

export function readApps(j: unknown): AppItem[] | null {
  if (!Array.isArray(j)) return null
  const out: AppItem[] = []
  for (const a of j) {
    if (!isObj(a) || typeof a.name !== 'string') return null
    out.push({
      name: a.name, title: str(a.title) || a.name, scopes: strs(a.scopes), events: strs(a.events), installed: a.installed === true,
      installation_id: str(a.installation_id), granted_scopes: strs(a.granted_scopes), installed_at: str(a.installed_at),
    })
  }
  return out
}

export function readInstalled(j: unknown): Installed | null {
  if (!isObj(j) || typeof j.token !== 'string' || !j.token || typeof j.signing_secret !== 'string' || !j.signing_secret) return null
  return { installation_id: str(j.installation_id) ?? '', app: str(j.app) ?? '', granted_scopes: strs(j.granted_scopes), token: j.token, signing_secret: j.signing_secret }
}

export function readAudit(j: unknown): AuditRow[] | null {
  if (!Array.isArray(j)) return null
  const out: AuditRow[] = []
  for (const a of j) {
    if (!isObj(a) || typeof a.id !== 'string' || typeof a.action !== 'string') return null
    out.push({ id: a.id, at: str(a.at) ?? '', actor: str(a.actor) ?? '', action: a.action, target: str(a.target), detail: isObj(a.detail) ? a.detail : {} })
  }
  return out
}

// ── Calls and messages ─────────────────────────────────────────────────────
export const FORBIDDEN_MESSAGE =
  'The preview account is not allowed to manage keys and apps. Add one of its roles to api_platform.roles in the Settings above, or sign in to the preview with an account that has one of those roles (a multi-tenant project also needs an account that belongs to a tenant).'

/** Readable message for a refused /platform call. 403 names the setting that controls access; others show the server's own message. */
export function platformError(status: number, json: unknown): string {
  if (status === 403) return FORBIDDEN_MESSAGE
  if (status === 401) return 'The preview session expired. Sign in to the preview again.'
  if (isObj(json)) {
    if (typeof json.message === 'string' && json.message) return json.message
    if (typeof json.detail === 'string' && json.detail) return json.detail
  }
  return `The request failed (status ${status}).`
}

export interface PlatformResult { status: number; json: unknown }
/** One call through the preview session; the answer text is parsed here only (never logged or stored). */
export async function platformCall(request: PreviewSession['request'], method: string, path: string, body?: unknown): Promise<PlatformResult> {
  const r = await request(method, path, body)
  let json: unknown = null
  try { json = r.text ? JSON.parse(r.text) : null } catch { json = null }
  return { status: r.status, json }
}
export const ok = (r: PlatformResult) => r.status >= 200 && r.status < 300

/** Short `YYYY-MM-DD HH:MM` (UTC) of an ISO instant; empty stays empty. */
export function shortWhen(iso: string | null): string {
  if (!iso) return ''
  const t = Date.parse(iso)
  return Number.isNaN(t) ? iso : new Date(t).toISOString().slice(0, 16).replace('T', ' ') + ' UTC'
}

export const KEY_STATUS_TEXT: Record<KeyStatus, { icon: string; text: string }> = {
  active: { icon: '✓', text: 'Active' },
  revoked: { icon: '✗', text: 'Revoked' },
  expired: { icon: '–', text: 'Expired' },
}

export function auditDetail(d: Raw): string {
  const s = JSON.stringify(d)
  return s === '{}' ? '' : s.length > 120 ? `${s.slice(0, 117)}...` : s
}
