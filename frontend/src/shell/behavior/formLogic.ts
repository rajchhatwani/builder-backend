/** Pure form logic for the Settings and Change-history pages (F1-6A): form state <-> API body and
 *  backend issue path -> form field. No React here, so it is unit-tested directly. The backend validator is
 *  the truth: its messages are shown as they come; only obvious shape problems are caught client side. */
import type {
  HistoryBody,
  ListBody,
  ListItemBody,
  SequenceBody,
  SettingBody,
  ValidationIssue,
} from '../../api/types'

export const SETTING_TYPES = ['string', 'int', 'bool', 'decimal'] as const
/** Same words as app/core/validation_runtime.py SECRET_WORDS (the backend refuses these names). */
export const SECRET_WORDS = ['secret', 'password', 'passwd', 'token', 'credential', 'private_key', 'api_key']

export const looksSecret = (name: string) => SECRET_WORDS.some((w) => name.toLowerCase().includes(w))

let nextKey = 1
export const newKey = () => nextKey++

export const rolesToText = (roles: string[] | undefined) => (roles ?? []).join(', ')
export const textToRoles = (text: string) =>
  text
    .split(/[\s,]+/)
    .map((r) => r.trim())
    .filter(Boolean)

const INT = /^-?\d+$/
/** "12" -> 12; anything else stays text so the backend can say what is wrong with it. */
const numOrRaw = (text: string): string | number | null => {
  const t = text.trim()
  if (!t) return null
  return INT.test(t) ? Number(t) : t
}

// ── Settings ────────────────────────────────────────────────────────────────
export interface SettingRow {
  k: number
  key: string
  type: string
  default: string
  label: string
  description: string
  minimum: string
  maximum: string
  max_length: string
  read_roles: string
  edit_roles: string
}

export const blankSetting = (): SettingRow => ({
  k: newKey(), key: '', type: 'string', default: '', label: '', description: '',
  minimum: '', maximum: '', max_length: '', read_roles: '', edit_roles: '',
})

const str = (v: string | number | boolean | null | undefined) => (v === null || v === undefined ? '' : String(v))

export const settingFromBody = (b: SettingBody): SettingRow => ({
  k: newKey(), key: b.key, type: b.type ?? 'string', default: str(b.default), label: b.label ?? '',
  description: b.description ?? '', minimum: str(b.minimum), maximum: str(b.maximum),
  max_length: str(b.max_length), read_roles: rolesToText(b.read_roles), edit_roles: rolesToText(b.edit_roles),
})

export function settingToBody(r: SettingRow): SettingBody {
  let def: string | number | boolean | null
  if (r.type === 'bool') def = r.default === 'true' ? true : r.default === 'false' ? false : null
  else if (r.type === 'int') def = numOrRaw(r.default)
  else def = r.type === 'string' ? r.default : r.default.trim() || null
  const maxLen = r.max_length.trim()
  return {
    key: r.key.trim(),
    type: r.type,
    default: def,
    label: r.label.trim() || null,
    description: r.description.trim() || null,
    minimum: r.type === 'int' ? numOrRaw(r.minimum) : r.minimum.trim() || null,
    maximum: r.type === 'int' ? numOrRaw(r.maximum) : r.maximum.trim() || null,
    // not an integer: send a value the API schema accepts; clientErrors() blocks the save first
    max_length: INT.test(maxLen) ? Number(maxLen) : null,
    read_roles: textToRoles(r.read_roles),
    edit_roles: textToRoles(r.edit_roles),
  }
}

// ── Sequences ───────────────────────────────────────────────────────────────
export interface SequenceRow {
  k: number
  name: string
  prefix: string
  padding: string
  start: string
  per_tenant: boolean
  reset_yearly: boolean
  view_roles: string
}

export const blankSequence = (): SequenceRow => ({
  k: newKey(), name: '', prefix: '', padding: '0', start: '1', per_tenant: false, reset_yearly: false, view_roles: '',
})

export const sequenceFromBody = (b: SequenceBody): SequenceRow => ({
  k: newKey(), name: b.name, prefix: b.prefix ?? '', padding: str(b.padding ?? 0), start: str(b.start ?? 1),
  per_tenant: !!b.per_tenant, reset_yearly: !!b.reset_yearly, view_roles: rolesToText(b.view_roles),
})

export const sequenceToBody = (r: SequenceRow): SequenceBody => ({
  name: r.name.trim(),
  prefix: r.prefix,
  padding: Number(r.padding.trim()),
  start: Number(r.start.trim()),
  per_tenant: r.per_tenant,
  reset_yearly: r.reset_yearly,
  view_roles: textToRoles(r.view_roles),
})

/** What the next number looks like, from the same rule the generated helper uses (prefix + year- + padded counter). */
export function previewNumber(r: SequenceRow, year = new Date().getFullYear()): string {
  const n = INT.test(r.start.trim()) ? r.start.trim().replace(/^-/, '') : '1'
  const pad = INT.test(r.padding.trim()) ? Math.min(Math.max(Number(r.padding), 0), 12) : 0
  return `${r.prefix}${r.reset_yearly ? `${year}-` : ''}${n.padStart(pad, '0')}`
}

// ── Lists ───────────────────────────────────────────────────────────────────
export interface ListItemRow {
  k: number
  value: string
  label: string
  color: string
  locked: boolean
}
export interface ListRow {
  k: number
  name: string
  label: string
  max_items: string
  edit_roles: string
  items: ListItemRow[]
}

export const blankItem = (): ListItemRow => ({ k: newKey(), value: '', label: '', color: '', locked: false })
export const blankList = (): ListRow => ({ k: newKey(), name: '', label: '', max_items: '100', edit_roles: '', items: [] })

export const listFromBody = (b: ListBody): ListRow => ({
  k: newKey(), name: b.name, label: b.label ?? '', max_items: str(b.max_items ?? 100), edit_roles: rolesToText(b.edit_roles),
  items: (b.items ?? []).map((i) => ({ k: newKey(), value: i.value, label: i.label, color: i.color ?? '', locked: !!i.locked })),
})

export const listToBody = (r: ListRow): ListBody => ({
  name: r.name.trim(),
  label: r.label.trim() || null,
  max_items: Number(r.max_items.trim()),
  edit_roles: textToRoles(r.edit_roles),
  items: r.items.map((i): ListItemBody => ({ value: i.value.trim(), label: i.label, color: i.color.trim() || null, locked: i.locked })),
})

// ── Change history ──────────────────────────────────────────────────────────
export interface HistoryRow {
  k: number
  entity: string
  fields: string[]
  retention_days: string
  view_roles: string
}

export const blankHistory = (entity: string): HistoryRow => ({ k: newKey(), entity, fields: [], retention_days: '365', view_roles: '' })

export const historyFromBody = (b: HistoryBody): HistoryRow => ({
  k: newKey(), entity: b.entity, fields: [...(b.fields ?? [])], retention_days: str(b.retention_days), view_roles: rolesToText(b.view_roles),
})

export const historyToBody = (r: HistoryRow): HistoryBody => ({
  entity: r.entity,
  fields: r.fields,
  retention_days: Number(r.retention_days.trim()),
  view_roles: textToRoles(r.view_roles),
})

// ── Client-side checks: only "is this even a number" (the API schema would answer 422 otherwise) ─────────
export type FieldErrors = Record<string, string> // key: `${rowIndex}.${field}`

const nonNegInt = (t: string) => /^\d+$/.test(t.trim())
const NEED_INT = 'Enter a whole number'

export function clientErrors(section: 'settings' | 'sequences' | 'lists' | 'history', rows: unknown[]): FieldErrors {
  const out: FieldErrors = {}
  rows.forEach((row, i) => {
    if (section === 'settings') {
      const r = row as SettingRow
      if (r.max_length.trim() && !nonNegInt(r.max_length)) out[`${i}.max_length`] = NEED_INT
    } else if (section === 'sequences') {
      const r = row as SequenceRow
      if (!nonNegInt(r.padding)) out[`${i}.padding`] = NEED_INT
      if (!nonNegInt(r.start)) out[`${i}.start`] = NEED_INT
    } else if (section === 'lists') {
      const r = row as ListRow
      if (!nonNegInt(r.max_items)) out[`${i}.max_items`] = NEED_INT
    } else {
      const r = row as HistoryRow
      if (!/^-?\d+$/.test(r.retention_days.trim())) out[`${i}.retention_days`] = NEED_INT
    }
  })
  return out
}

// ── Backend issue path -> form field ─────────────────────────────────────────
export interface RowIssues {
  /** form field key -> messages. Keys: `key`, `default`, `view_roles`, `items[2].value`, `fields[1]`, ... */
  fields: Record<string, string[]>
  /** issues on the row itself (path `settings[0]`) */
  row: string[]
}
export interface SectionIssues {
  /** issues on the whole section (path `settings`, e.g. too_many) */
  section: string[]
  rows: Record<number, RowIssues>
}

/** `settings[0].read_roles[1]` -> {index 0, field 'read_roles'}; `lists[1].items[2].value` -> field 'items[2].value'. */
export function parseIssuePath(path: string): { section: string; index: number | null; field: string | null } {
  const m = /^([a-z_]+)(?:\[(\d+)\])?(?:\.(.+))?$/.exec(path)
  if (!m) return { section: path, index: null, field: null }
  const field = m[3] ? m[3].replace(/^(\w*_roles)\[\d+\]$/, '$1') : null
  return { section: m[1], index: m[2] === undefined ? null : Number(m[2]), field }
}

export function issuesForSection(section: string, issues: ValidationIssue[]): SectionIssues {
  const out: SectionIssues = { section: [], rows: {} }
  for (const issue of issues) {
    const p = parseIssuePath(issue.path)
    if (p.section !== section) continue
    if (p.index === null) {
      out.section.push(issue.message)
      continue
    }
    const row = (out.rows[p.index] ??= { fields: {}, row: [] })
    if (p.field === null) row.row.push(issue.message)
    else (row.fields[p.field] ??= []).push(issue.message)
  }
  return out
}

export const countIssues = (s: SectionIssues) =>
  s.section.length + Object.values(s.rows).reduce((n, r) => n + r.row.length + Object.values(r.fields).flat().length, 0)
