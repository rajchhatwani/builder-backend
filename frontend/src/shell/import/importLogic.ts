import type { ImportCounts, ImportPreview, ImportRow, ImportRowError } from '../../api/types'

export type SpecField = { name: string; required: boolean }
export type SpecEntity = { name: string; fields: SpecField[] }

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

/** The entities (and their fields) the project spec declares. Anything malformed is skipped. */
export function entitiesOf(spec: Record<string, unknown>): SpecEntity[] {
  const list = Array.isArray(spec.entities) ? spec.entities : []
  const out: SpecEntity[] = []
  for (const e of list) {
    if (!isObj(e) || typeof e.name !== 'string') continue
    const fields = (Array.isArray(e.fields) ? e.fields : [])
      .filter((f): f is Record<string, unknown> => isObj(f) && typeof f.name === 'string')
      .map((f) => ({ name: f.name as string, required: f.required === true }))
    out.push({ name: e.name, fields })
  }
  return out
}

/** The body for PUT .../mapping after one select changed. An empty header means "do not import this field" (null). */
export function mappingBody(fields: SpecField[], current: Record<string, string>, field: string, header: string): Record<string, string | null> {
  const body: Record<string, string | null> = {}
  for (const f of fields) body[f.name] = current[f.name] || null
  body[field] = header === '' ? null : header
  return body
}

/** Pre-fills the selects: what the server holds now, else its suggestion. */
export function initialMapping(preview: Pick<ImportPreview, 'mapping' | 'suggested_mapping'>): Record<string, string> {
  return Object.keys(preview.mapping).length > 0 ? { ...preview.mapping } : { ...preview.suggested_mapping }
}

export type FieldErrors = { field: string; messages: string[] }

/** Groups a row's errors per field, first-seen order, duplicate messages collapsed. */
export function groupErrors(errors: ImportRowError[]): FieldErrors[] {
  const order: string[] = []
  const by = new Map<string, string[]>()
  for (const e of errors) {
    const key = e.field || '(row)'
    if (!by.has(key)) {
      by.set(key, [])
      order.push(key)
    }
    const msgs = by.get(key)!
    if (!msgs.includes(e.message)) msgs.push(e.message)
  }
  return order.map((field) => ({ field, messages: by.get(field)! }))
}

/** Fields a person can type into to fix a row: the ones that have errors and exist on the entity. */
export function fixableFields(row: ImportRow, fields: SpecField[]): string[] {
  const known = new Set(fields.map((f) => f.name))
  return groupErrors(row.errors).map((g) => g.field).filter((f) => known.has(f))
}

/** Starting text of a fix input: the file's cell for the mapped column, else empty. */
export function startValue(row: ImportRow, mapping: Record<string, string>, field: string): string {
  const header = mapping[field]
  return header ? (row.raw[header] ?? '') : ''
}

/** Only the inputs the person actually changed are sent. */
export function changedValues(edits: Record<string, string>, row: ImportRow, mapping: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(edits)) if (v !== startValue(row, mapping, k)) out[k] = v
  return out
}

export type Step = 'choose' | 'mapping' | 'review' | 'done'
export const STEPS: { id: Step; label: string }[] = [
  { id: 'choose', label: 'Choose a file' },
  { id: 'mapping', label: 'Match columns' },
  { id: 'review', label: 'Fix problem rows' },
  { id: 'done', label: 'Done' },
]

export function deriveStep(s: { preview: ImportPreview | null; reviewing: boolean; done: boolean }): Step {
  if (s.done) return 'done'
  if (!s.preview) return 'choose'
  return s.reviewing ? 'review' : 'mapping'
}

export function summarise(c: ImportCounts): string {
  const ready = c.accepted + c.fixed
  const parts = [`${c.total} ${c.total === 1 ? 'row' : 'rows'}`, `${ready} ready`, `${c.rejected} need fixing`]
  if (c.duplicate > 0) parts.push(`${c.duplicate} already imported`)
  return parts.join(', ')
}

/** Rows that will be written when committing. */
export const readyCount = (c: ImportCounts) => c.accepted + c.fixed

/** After one row was saved: move it from "needs fixing" to "fixed" when it is valid now. */
export function applyRowSave(c: ImportCounts, saved: ImportRow): ImportCounts {
  if (saved.status !== 'fixed') return c
  return { ...c, rejected: Math.max(0, c.rejected - 1), fixed: c.fixed + 1 }
}

type QuotaDetail = { metric?: unknown; limit?: unknown; used?: unknown; period_end?: unknown }

/** A plain message for a 429 quota_exceeded refusal, naming the limit when the server sent it. */
export function quotaMessage(details: unknown[]): string {
  const d = (details[0] ?? {}) as QuotaDetail
  const what = d.metric === 'imports.rows' ? 'imported rows' : d.metric === 'imports.batches' ? 'imports' : 'imports'
  const hasNums = typeof d.limit === 'number' && typeof d.used === 'number'
  const base = hasNums
    ? `Your plan allows ${d.limit} ${what} this period and ${d.used} are used.`
    : `Your plan's limit on ${what} is used up.`
  const until = typeof d.period_end === 'string' && d.period_end ? ` It resets on ${d.period_end.slice(0, 10)}.` : ''
  return `${base}${until} Nothing was imported. Your fixes are kept; commit again once there is room.`
}
