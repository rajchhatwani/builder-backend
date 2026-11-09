/** F4-6: pure spec diff. Compares a BASELINE spec with the CURRENT one; "added" means present now, absent in the baseline. */

export type Kind = 'added' | 'removed' | 'changed'
export type Change = { kind: Kind; label: string; before?: string; after?: string; redacted?: boolean }
export type DiffItem = { kind: Kind; key: string; changes: Change[] }
export type SectionId = 'entities' | 'relations' | 'roles' | 'permissions' | 'machines' | 'rules' | 'hooks' | 'other'
export type DiffSection = { id: SectionId; label: string; items: DiffItem[] }
export type DiffModel = { total: number; truncated: boolean; sections: DiffSection[] }
type Obj = Record<string, unknown>

export const MAX_ITEMS = 200
export const MAX_CHANGES = 50
export const REDACTED = '••• changed'
const SECRET = /secret|password|token|key/i

const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)
const asList = (v: unknown): Obj[] => (Array.isArray(v) ? v.filter(isObj) : [])
const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)
const str = (v: unknown) => (typeof v === 'string' ? v : '')
const isPrim = (v: unknown) => v === null || ['string', 'number', 'boolean'].includes(typeof v)

/** Text of one value: primitives as they are, lists of primitives joined, anything else as JSON. */
export function show(v: unknown): string {
  if (v === undefined || v === null) return 'none'
  if (Array.isArray(v)) return v.length === 0 ? '(empty)' : v.every(isPrim) ? v.map(String).join(', ') : JSON.stringify(v)
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** Every leaf of a value as dotted path -> leaf. Lists of primitives are one leaf; other lists are walked by index. */
export function flatten(v: unknown, prefix = '', out: Map<string, unknown> = new Map()): Map<string, unknown> {
  if (isObj(v) && Object.keys(v).length > 0) {
    for (const k of Object.keys(v)) flatten(v[k], prefix ? `${prefix}.${k}` : k, out)
  } else if (Array.isArray(v) && v.length > 0 && !v.every(isPrim)) {
    v.forEach((x, i) => flatten(x, `${prefix}[${i}]`, out))
  } else if (prefix) {
    out.set(prefix, v)
  }
  return out
}

const redacts = (path: string) => SECRET.test(path.split('.').pop() ?? path)

/** Attribute changes between two values, sorted by path. `label` maps a path to what the person reads. */
function attrChanges(a: unknown, b: unknown, label: (p: string) => string = (p) => p): Change[] {
  const fa = flatten(a)
  const fb = flatten(b)
  const paths = [...new Set([...fa.keys(), ...fb.keys()])].sort(cmp)
  const out: Change[] = []
  for (const p of paths) {
    const inA = fa.has(p)
    const inB = fb.has(p)
    if (inA && inB && show(fa.get(p)) === show(fb.get(p))) continue
    const kind: Kind = inA && inB ? 'changed' : inB ? 'added' : 'removed'
    if (redacts(p)) out.push({ kind, label: label(p), redacted: true })
    else out.push({ kind, label: label(p), before: inA ? show(fa.get(p)) : undefined, after: inB ? show(fb.get(p)) : undefined })
  }
  return out
}

/** Items present on one side only, or on both with differences. */
function diffKeyed(base: Obj[], cur: Obj[], key: (o: Obj) => string, changes: (a: Obj, b: Obj) => Change[]): DiffItem[] {
  const ma = new Map(base.map((o) => [key(o), o]))
  const mb = new Map(cur.map((o) => [key(o), o]))
  const items: DiffItem[] = []
  for (const k of [...new Set([...ma.keys(), ...mb.keys()])].sort(cmp)) {
    const a = ma.get(k)
    const b = mb.get(k)
    if (a && b) {
      const c = changes(a, b)
      if (c.length) items.push({ kind: 'changed', key: k, changes: c })
    } else {
      items.push({ kind: b ? 'added' : 'removed', key: k, changes: [] })
    }
  }
  return items
}

/** Changes of a keyed sub-list (fields of an entity, transitions of a machine) written flat, one label prefix each. */
function subList(word: string, base: unknown, cur: unknown, key: (o: Obj) => string): Change[] {
  const out: Change[] = []
  for (const it of diffKeyed(asList(base), asList(cur), key, (a, b) => attrChanges(a, b, (p) => `${word} ${key(b)} · ${p}`))) {
    if (it.kind === 'changed') out.push(...it.changes)
    else out.push({ kind: it.kind, label: `${word} ${it.key}` })
  }
  return out
}

const without = (o: Obj, ...keys: string[]): Obj => {
  const c = { ...o }
  for (const k of keys) delete c[k]
  return c
}

function entityChanges(a: Obj, b: Obj): Change[] {
  return [
    ...attrChanges(without(a, 'fields'), without(b, 'fields')),
    ...subList('field', a.fields, b.fields, (o) => str(o.name)),
  ]
}

function machineChanges(a: Obj, b: Obj): Change[] {
  return [
    ...attrChanges(without(a, 'transitions'), without(b, 'transitions')),
    ...subList('transition', a.transitions, b.transitions, (o) => str(o.name)),
  ]
}

const auth = (s: Obj): Obj => (isObj(s.auth) ? s.auth : {})
const authz = (s: Obj): Obj => (isObj(s.authorization) ? s.authorization : {})
const flat = (a: Obj, b: Obj) => attrChanges(a, b)

function rulesItems(a: Obj, b: Obj): DiffItem[] {
  const items = [
    ...diffKeyed(asList(authz(a).policies), asList(authz(b).policies), (o) => `policy ${str(o.id)}`, flat),
    ...diffKeyed(asList(authz(a).field_access), asList(authz(b).field_access), (o) => `field access ${str(o.entity)}.${str(o.field)}`, flat),
  ]
  const rest = attrChanges(without(authz(a), 'policies', 'field_access'), without(authz(b), 'policies', 'field_access'), (p) => p)
  if (rest.length) items.push({ kind: 'changed', key: 'authorization settings', changes: rest })
  return items.sort((x, y) => cmp(x.key, y.key))
}

/** Everything the typed sections above do not cover, compared as plain JSON paths. */
function otherItems(a: Obj, b: Obj): DiffItem[] {
  const strip = (s: Obj): Obj => ({ ...without(s, 'entities', 'relations', 'state_machines', 'hooks', 'authorization', 'auth'), auth: without(auth(s), 'roles', 'permissions') })
  const changes = attrChanges(strip(a), strip(b))
  return changes.length ? [{ kind: 'changed', key: 'other settings', changes }] : []
}

export function diffSpecs(baseline: Obj, current: Obj): DiffModel {
  const sec = (id: SectionId, label: string, items: DiffItem[]): DiffSection => ({ id, label, items })
  const all: DiffSection[] = [
    sec('entities', 'Entities and fields', diffKeyed(asList(baseline.entities), asList(current.entities), (o) => str(o.name), entityChanges)),
    sec('relations', 'Relations', diffKeyed(asList(baseline.relations), asList(current.relations), (o) => `${str(o.from_entity)}.${str(o.from_name)} -> ${str(o.to_entity)}.${str(o.to_name)}`, flat)),
    sec('roles', 'Roles', diffKeyed(asList(auth(baseline).roles), asList(auth(current).roles), (o) => str(o.name), flat)),
    sec('permissions', 'Permissions', diffKeyed(asList(auth(baseline).permissions), asList(auth(current).permissions), (o) => `${str(o.entity)}.${str(o.operation)}`, flat)),
    sec('machines', 'State machines', diffKeyed(asList(baseline.state_machines), asList(current.state_machines), (o) => `${str(o.entity)}.${str(o.field)}`, machineChanges)),
    sec('rules', 'Rules and policies', rulesItems(baseline, current)),
    sec('hooks', 'Hooks', diffKeyed(asList(baseline.hooks), asList(current.hooks), (o) => str(o.name), flat)),
    sec('other', 'Other settings', otherItems(baseline, current)),
  ].filter((s) => s.items.length > 0)

  const total = all.reduce((n, s) => n + s.items.length, 0)
  let left = MAX_ITEMS
  const sections = all
    .map((s) => {
      const items = s.items.slice(0, Math.max(left, 0)).map((i) => ({ ...i, changes: i.changes.slice(0, MAX_CHANGES) }))
      left -= items.length
      return { ...s, items }
    })
    .filter((s) => s.items.length > 0)
  const truncated = total > MAX_ITEMS || all.some((s) => s.items.some((i) => i.changes.length > MAX_CHANGES))
  return { total, truncated, sections }
}

/** One line for a change: marker, label and, when there is one, before -> after. Secret-looking values are never shown. */
export function changeText(c: Change): string {
  const mark = c.kind === 'added' ? '+' : c.kind === 'removed' ? '-' : '~'
  if (c.redacted) return `${mark} ${c.label}: ${REDACTED}`
  if (c.kind === 'changed') return `${mark} ${c.label}: ${c.before} -> ${c.after}`
  const v = c.kind === 'added' ? c.after : c.before
  return v === undefined ? `${mark} ${c.label}` : `${mark} ${c.label}: ${v}`
}

export const MARKS: Record<Kind, { mark: string; word: string }> = {
  added: { mark: '+', word: 'Added' },
  removed: { mark: '-', word: 'Removed' },
  changed: { mark: '~', word: 'Changed' },
}

export type Parsed = { ok: true; spec: Obj } | { ok: false; error: string }

export function parseSpecText(text: string): Parsed {
  if (!text.trim()) return { ok: false, error: 'Paste a spec as JSON first.' }
  try {
    const v: unknown = JSON.parse(text)
    return isObj(v) ? { ok: true, spec: v } : { ok: false, error: 'A spec must be a JSON object.' }
  } catch {
    return { ok: false, error: 'That is not valid JSON. Check for a missing comma, quote or bracket.' }
  }
}

export const baselineKey = (projectId: string) => `bb.specBaseline.${projectId}`
export type Baseline = { savedAt: string; spec: Obj }
type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

export function saveBaseline(store: Store, projectId: string, spec: Obj, now: Date = new Date()): Baseline | null {
  const b: Baseline = { savedAt: now.toISOString(), spec }
  try {
    store.setItem(baselineKey(projectId), JSON.stringify(b))
    return b
  } catch {
    return null
  }
}

export function loadBaseline(store: Store, projectId: string): Baseline | null {
  try {
    const raw = store.getItem(baselineKey(projectId))
    if (!raw) return null
    const v: unknown = JSON.parse(raw)
    return isObj(v) && typeof v.savedAt === 'string' && isObj(v.spec) ? { savedAt: v.savedAt, spec: v.spec } : null
  } catch {
    return null
  }
}

export function clearBaseline(store: Store, projectId: string) {
  try {
    store.removeItem(baselineKey(projectId))
  } catch {
    /* storage unavailable: nothing to clear */
  }
}
