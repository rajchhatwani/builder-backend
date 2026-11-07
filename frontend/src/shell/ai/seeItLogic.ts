import { buildRequestUrl, generatePayload, parseOperations, redactBodyText, redactPath, type Json, type Operation } from '../workbench/workbenchLogic'

/** F3-7 "See it work": pure helpers. The preview token is passed in and never returned, logged or stored. */

export const MAX_BODY_CHARS = 4000
export const REQUEST_TIMEOUT_MS = 15_000
export const READY_TIMEOUT_MS = 90_000
export const POLL_MS = 2000

const LIVE = ['starting', 'running', 'sleeping']
export const isLivePreview = (state: string) => LIVE.includes(state)
/** "running" is what the server calls ready; a sleeping preview wakes on its first request. */
export const isReady = (state: string) => state === 'running' || state === 'sleeping'
export const isDeadPreview = (state: string) => ['failed', 'killed', 'expired'].includes(state)

export const PREVIEW_STATE_TEXT: Record<string, string> = {
  starting: 'Starting up', running: 'Ready', sleeping: 'Asleep (wakes on the first request)', stopping: 'Going to sleep',
  failed: 'Could not start', killed: 'Switched off', expired: 'Expired',
}
export const previewStateText = (s: string) => PREVIEW_STATE_TEXT[s] ?? s

/** Kept for the page's lifetime in memory only (never storage, never the URL). */
const tokens = new Map<string, string>()
export const rememberToken = (previewId: string, token: string) => { tokens.set(previewId, token) }
export const tokenFor = (previewId: string): string | null => tokens.get(previewId) ?? null
export const forgetTokens = () => tokens.clear()

/** Full base URL of a preview: the builder origin plus the server's relative url_path. */
export function previewBase(baseUrl: string, urlPath: string): string {
  if (!urlPath.startsWith('/previews/') || urlPath.includes('..') || urlPath.includes('\\') || urlPath.startsWith('//')) throw new Error('The server sent an unexpected preview address')
  return `${baseUrl.replace(/\/+$/, '')}${urlPath.endsWith('/') ? urlPath.slice(0, -1) : urlPath}`
}

export interface Entity {
  name: string
  listPath: string
  list: Operation
  create: Operation | null
  read: Operation | null
  update: Operation | null
  idParam: string | null
}

const SKIP = new Set(['health', 'healthz', 'ready', 'readyz', 'openapi.json', 'docs', 'redoc', 'metrics', 'auth', 'login', 'logout', 'token', 'me'])

/** One entry per collection path (/things) with its list/create and item (/things/{id}) read/update operations. */
export function entitiesOf(doc: unknown): Entity[] {
  const ops = parseOperations(doc)
  const by = (path: string, method: string) => ops.find((o) => o.path === path && o.method === method) ?? null
  const out: Entity[] = []
  for (const o of ops) {
    if (o.method !== 'get' || !/^\/[A-Za-z0-9_-]+$/.test(o.path)) continue
    const name = o.path.slice(1)
    if (SKIP.has(name) || name.startsWith('_') || o.params.some((p) => p.in === 'path')) continue
    const item = ops.find((x) => x.method === 'get' && x.path.startsWith(`${o.path}/{`) && /^\/[A-Za-z0-9_-]+\/\{[A-Za-z0-9_]+\}$/.test(x.path))
    const itemPath = item?.path ?? null
    out.push({
      name, listPath: o.path, list: o, create: by(o.path, 'post'), read: item ?? null,
      update: itemPath ? (by(itemPath, 'patch') ?? by(itemPath, 'put')) : null,
      idParam: item?.params.find((p) => p.in === 'path')?.name ?? null,
    })
  }
  return out
}
export const crudComplete = (e: Entity) => !!(e.create && e.read && e.update && e.idParam)

const PREVIEW = 'preview-data'
/** Example body from the schema, with plain text values replaced by an obvious marker so nobody mistakes it for real data. */
export function exampleBody(doc: unknown, op: Operation | null): Json | undefined {
  if (!op?.bodySchema) return undefined
  const v = generatePayload(doc, op.bodySchema, 'valid')
  if (!v || typeof v !== 'object' || Array.isArray(v)) return v
  const out: { [k: string]: Json } = {}
  for (const [k, x] of Object.entries(v)) {
    out[k] = typeof x === 'string' && /^a+$/.test(x) ? (x.length <= PREVIEW.length ? PREVIEW.slice(0, Math.max(1, x.length)) : PREVIEW.padEnd(x.length, '-')) : x
  }
  return out
}

/** Same shape, first preview-data text swapped for another of the same length so the update visibly changes something. */
export function editedBody(body: Json | undefined): Json | undefined {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return body
  const out: { [k: string]: Json } = { ...body }
  for (const [k, x] of Object.entries(out)) {
    if (typeof x === 'string' && x.startsWith('preview-')) { out[k] = `edited--${x.slice(8)}`.slice(0, x.length).padEnd(x.length, '-'); break }
  }
  return out
}

export interface CallInput { base: string; token: string; method: string; path: string; body?: Json }
export interface CallResult { status: number; ms: number; text: string; json: unknown }

function checkPath(path: string) {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\') || path.includes('..') || path.startsWith('/-/')) throw new Error('Refusing a path that is not relative to the preview')
}

/** One request through the preview proxy. No cookies, no redirects, capped response, token only in the X-Preview-Token header. */
export async function callPreview(i: CallInput, doFetch: typeof fetch = fetch): Promise<CallResult> {
  checkPath(i.path)
  const url = `${i.base}${i.path}`
  if (new URL(url).origin !== new URL(i.base).origin) throw new Error('Refusing a URL outside the preview')
  const headers: Record<string, string> = { Accept: 'application/json', 'X-Preview-Token': i.token }
  if (i.body !== undefined) headers['Content-Type'] = 'application/json'
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), REQUEST_TIMEOUT_MS)
  const t0 = Date.now()
  try {
    const res = await doFetch(url, { method: i.method.toUpperCase(), headers, body: i.body === undefined ? undefined : JSON.stringify(i.body), credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal: ctl.signal })
    const raw = (await res.text()).slice(0, 200_000)
    let json: unknown = null
    try { json = raw ? JSON.parse(raw) : null } catch { json = null }
    return { status: res.status, ms: Date.now() - t0, text: raw, json }
  } catch (e) {
    if (ctl.signal.aborted) throw new Error('The preview did not answer in time')
    throw new Error(e instanceof TypeError ? 'Could not reach the preview (network error, CORS or a redirect)' : e instanceof Error ? e.message : 'Request failed')
  } finally { clearTimeout(timer) }
}

export const itemPath = (e: Entity, id: string): string => {
  if (!e.read || !e.idParam) throw new Error('This entity has no read endpoint')
  return buildRequestUrl('http://x.invalid', e.read.path, { [e.idParam]: id }, e.read.params).slice('http://x.invalid'.length)
}

/** The id of a created record, from a create response. */
export function createdId(json: unknown): string | null {
  if (!json || typeof json !== 'object') return null
  const id = (json as { id?: unknown }).id
  return typeof id === 'string' || typeof id === 'number' ? String(id) : null
}

export type StepId = 'preview' | 'endpoints' | 'list' | 'create' | 'read' | 'update'
export type Verdict = 'idle' | 'running' | 'pass' | 'fail'
export interface StepResult { verdict: Verdict; summary: string; request?: string; response?: string }
export const STEP_ORDER: StepId[] = ['preview', 'endpoints', 'list', 'create', 'read', 'update']
export const STEP_LABEL: Record<StepId, string> = {
  preview: 'Start a preview of the backend', endpoints: 'See the endpoints it generated', list: 'List records', create: 'Create a record (preview data)', read: 'Read it back', update: 'Update it',
}

const okStatus = (s: number, ...want: number[]) => want.includes(s)

/** Judge one call. Pass needs the expected status; read must return the created id; list must be JSON (array or {items}). */
export function judge(step: 'list' | 'create' | 'read' | 'update', r: CallResult, id?: string | null): { ok: boolean; summary: string } {
  const j = r.json as Record<string, unknown> | unknown[] | null
  if (step === 'list') {
    const items = Array.isArray(j) ? j : j && Array.isArray((j as { items?: unknown }).items) ? (j as { items: unknown[] }).items : null
    if (okStatus(r.status, 200) && items) return { ok: true, summary: `${r.status}: ${items.length} record${items.length === 1 ? '' : 's'} on the first page` }
    return { ok: false, summary: okStatus(r.status, 200) ? '200 but the answer is not a list' : `Expected 200, got ${r.status}` }
  }
  if (step === 'create') {
    const cid = createdId(r.json)
    if (okStatus(r.status, 200, 201) && cid) return { ok: true, summary: `${r.status}: created record ${cid}` }
    return { ok: false, summary: okStatus(r.status, 200, 201) ? 'Created, but the answer has no id' : `Expected 201, got ${r.status}` }
  }
  if (step === 'read') {
    if (okStatus(r.status, 200) && id && createdId(r.json) === id) return { ok: true, summary: `${r.status}: the record we created comes back` }
    return { ok: false, summary: okStatus(r.status, 200) ? 'A record came back, but not the one we created' : `Expected 200, got ${r.status}` }
  }
  if (okStatus(r.status, 200, 204)) return { ok: true, summary: `${r.status}: updated` }
  return { ok: false, summary: `Expected 200, got ${r.status}` }
}

/** Request and response as shown on screen: paths and bodies pass through the same redaction as the Workbench. */
export function evidence(method: string, path: string, body: Json | undefined, r: CallResult | null): { request: string; response: string } {
  const req = `${method.toUpperCase()} ${redactPath(path)}${body === undefined ? '' : `\n${redactBodyText(JSON.stringify(body, null, 2))}`}`
  const res = r ? `${r.status} in ${r.ms} ms\n${redactBodyText(r.text).slice(0, MAX_BODY_CHARS)}` : 'No answer'
  return { request: req, response: res }
}

export interface Acceptance { passed: number; failed: number; total: number; done: boolean; accepted: boolean; text: string }
export function acceptance(results: Partial<Record<StepId, StepResult>>): Acceptance {
  const all = STEP_ORDER.map((s) => results[s]?.verdict ?? 'idle')
  const passed = all.filter((v) => v === 'pass').length
  const failed = all.filter((v) => v === 'fail').length
  const done = passed + failed === all.length
  const accepted = passed === all.length
  const text = accepted ? 'All checks passed: the backend answers as built.' : failed ? `${failed} check${failed === 1 ? '' : 's'} failed. Look at the evidence, then ask the agent to fix it or change it yourself.` : `${passed} of ${all.length} checks done.`
  return { passed, failed, total: all.length, done, accepted, text }
}

/** Friendly text for a refused preview (server message first, a hint after). */
export function previewRefusal(code: string | undefined, message: string): string {
  const hint: Record<string, string> = {
    email_not_verified: 'Verify your e-mail address first, then try again.',
    previews_disabled: 'Previews are switched off right now.',
    previews_off: 'Previews are switched off right now.',
    preview_quota: 'Use the button below to get a new token for a preview you already have, or stop one of your other previews.',
    previews_unavailable: 'Previews are not set up on this server.',
  }
  return hint[code ?? ''] ? `${message} ${hint[code ?? '']}` : message
}
