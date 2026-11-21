/** Compliance page logic: API shapes (app/core/spec_models.py SpecCompliance + the controls report), form rows, checks. */

export type Framework = 'soc2' | 'hipaa' | 'pci'
export const FRAMEWORKS: { id: Framework | ''; label: string }[] = [
  { id: '', label: 'All' },
  { id: 'soc2', label: 'SOC 2' },
  { id: 'hipaa', label: 'HIPAA' },
  { id: 'pci', label: 'PCI' },
]

export type ControlStatus = 'met' | 'unmet' | 'not_applicable'
export interface Control {
  id: string
  framework: string
  title: string
  description: string
  status: ControlStatus
  reason: string
  evidence: Record<string, unknown>[]
  tests: { file: string; name: string }[]
}
export interface ControlsReport {
  framework: string | null
  met: number
  unmet: number
  not_applicable: number
  controls: Control[]
}

const STATUSES = new Set(['met', 'unmet', 'not_applicable'])
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)

/** Returns the report when the answer has the documented shape, else null (a 200 that is not the controls report). */
export function readControls(j: unknown): ControlsReport | null {
  if (!isObj(j) || !Array.isArray(j.controls)) return null
  for (const k of ['met', 'unmet', 'not_applicable'] as const) if (typeof j[k] !== 'number') return null
  const controls: Control[] = []
  for (const c of j.controls) {
    if (!isObj(c) || typeof c.id !== 'string' || typeof c.status !== 'string' || !STATUSES.has(c.status)) return null
    controls.push({
      id: c.id,
      framework: typeof c.framework === 'string' ? c.framework : '',
      title: typeof c.title === 'string' ? c.title : c.id,
      description: typeof c.description === 'string' ? c.description : '',
      status: c.status as ControlStatus,
      reason: typeof c.reason === 'string' ? c.reason : '',
      evidence: Array.isArray(c.evidence) ? c.evidence.filter(isObj) : [],
      tests: Array.isArray(c.tests)
        ? c.tests.filter(isObj).map((t) => ({ file: String(t.file ?? ''), name: String(t.name ?? '') }))
        : [],
    })
  }
  return {
    framework: typeof j.framework === 'string' ? j.framework : null,
    met: j.met as number, unmet: j.unmet as number, not_applicable: j.not_applicable as number, controls,
  }
}

export const STATUS_TEXT: Record<ControlStatus, { icon: string; text: string }> = {
  met: { icon: '✓', text: 'Met' },
  unmet: { icon: '✗', text: 'Unmet' },
  not_applicable: { icon: '–', text: 'Not applicable' },
}

/** One short line for an evidence entry (the server's objects are open-ended). */
export function evidenceLabel(e: Record<string, unknown>): string {
  for (const k of ['label', 'title', 'name', 'path', 'description', 'kind']) {
    if (typeof e[k] === 'string' && e[k]) {
      const rest = Object.entries(e).filter(([kk, v]) => kk !== k && (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'))
      return rest.length ? `${e[k]} (${rest.slice(0, 3).map(([kk, v]) => `${kk}: ${v}`).join(', ')})` : String(e[k])
    }
  }
  const s = JSON.stringify(e)
  return s.length > 120 ? `${s.slice(0, 117)}...` : s
}

// ── Settings form ──────────────────────────────────────────────────────────
export type Treatment = 'keep' | 'drop' | 'hash' | 'generalise'
export const TREATMENTS: Treatment[] = ['drop', 'hash', 'generalise', 'keep']
export interface RetRow { k: number; entity: string; days: string; date_field: string; action: 'purge' | 'anonymise'; anonymise_fields: string[] }
export interface ExpFieldRow { k: number; entity: string; field: string; treatment: Treatment }
export interface ExpEntityRow { k: number; entity: string; subject_field: string }
export interface Draft {
  enabled: boolean
  roles: string[]
  retention: RetRow[]
  purposes: string[]
  bgEnabled: boolean
  bgRoles: string[]
  bgMinutes: string
  expEntities: ExpEntityRow[]
  expFields: ExpFieldRow[]
  consentPurpose: string
}
export type Raw = Record<string, unknown>
const MANAGED = ['enabled', 'roles', 'retention', 'consent_purposes', 'break_glass', 'export_entities', 'export_fields', 'export_consent_purpose']

let seq = 0
export const nextKey = () => ++seq
export const parseList = (t: string): string[] => t.split(',').map((s) => s.trim()).filter(Boolean)
export const listText = (v: string[]): string => v.join(', ')

const arr = (v: unknown): Raw[] => (Array.isArray(v) ? v.filter(isObj) : [])
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])

export function draftFrom(raw: Raw | null): Draft {
  const r = raw ?? {}
  const bg = isObj(r.break_glass) ? r.break_glass : {}
  return {
    enabled: r.enabled === true,
    roles: strs(r.roles),
    retention: arr(r.retention).map((x) => ({
      k: nextKey(), entity: String(x.entity ?? ''), days: x.days === undefined ? '' : String(x.days), date_field: String(x.date_field ?? 'created_at'),
      action: x.action === 'anonymise' ? 'anonymise' : 'purge', anonymise_fields: strs(x.anonymise_fields),
    })),
    purposes: strs(r.consent_purposes),
    bgEnabled: bg.enabled === true,
    bgRoles: strs(bg.roles),
    bgMinutes: bg.max_minutes === undefined ? '60' : String(bg.max_minutes),
    expEntities: arr(r.export_entities).map((x) => ({ k: nextKey(), entity: String(x.entity ?? ''), subject_field: typeof x.subject_field === 'string' ? x.subject_field : '' })),
    expFields: arr(r.export_fields).map((x) => ({
      k: nextKey(), entity: String(x.entity ?? ''), field: String(x.field ?? ''),
      treatment: (TREATMENTS as string[]).includes(String(x.treatment)) ? (x.treatment as Treatment) : 'drop',
    })),
    consentPurpose: typeof r.export_consent_purpose === 'string' ? r.export_consent_purpose : '',
  }
}

/** The block sent to PUT /behavior/compliance. Keys this form does not manage are carried over unchanged. */
export function toBlock(d: Draft, raw: Raw | null): Raw {
  const kept = Object.fromEntries(Object.entries(raw ?? {}).filter(([k]) => !MANAGED.includes(k)))
  return {
    ...kept,
    enabled: d.enabled,
    roles: d.roles,
    retention: d.retention.map((r) => ({ entity: r.entity.trim(), days: Number(r.days), date_field: r.date_field.trim(), action: r.action, anonymise_fields: r.anonymise_fields })),
    consent_purposes: d.purposes,
    break_glass: { enabled: d.bgEnabled, roles: d.bgRoles, max_minutes: Number(d.bgMinutes) },
    export_entities: d.expEntities.map((e) => ({ entity: e.entity.trim(), subject_field: e.subject_field.trim() || null })),
    export_fields: d.expFields.map((f) => ({ entity: f.entity.trim(), field: f.field.trim(), treatment: f.treatment })),
    export_consent_purpose: d.consentPurpose.trim() || null,
  }
}

const isInt = (t: string) => /^\d+$/.test(t.trim())

/** Client checks; keys are `retention.<k>.days` style so the form can show each next to its field. */
export function checkDraft(d: Draft): Record<string, string> {
  const e: Record<string, string> = {}
  for (const r of d.retention) {
    if (!r.entity.trim()) e[`ret.${r.k}.entity`] = 'Name the entity.'
    if (!isInt(r.days) || Number(r.days) < 1 || Number(r.days) > 36500) e[`ret.${r.k}.days`] = 'Days must be a whole number from 1 to 36500.'
    if (!r.date_field.trim()) e[`ret.${r.k}.date_field`] = 'Name the date field.'
    if (r.action === 'anonymise' && r.anonymise_fields.length === 0) e[`ret.${r.k}.anonymise_fields`] = 'List the fields to anonymise.'
  }
  if (new Set(d.purposes).size !== d.purposes.length) e.purposes = 'Each purpose may appear only once.'
  if (!isInt(d.bgMinutes) || Number(d.bgMinutes) < 5 || Number(d.bgMinutes) > 240) e.bgMinutes = 'Minutes must be a whole number from 5 to 240.'
  for (const f of d.expFields) {
    if (!f.entity.trim()) e[`exp.${f.k}.entity`] = 'Name the entity.'
    if (!f.field.trim()) e[`exp.${f.k}.field`] = 'Name the field.'
  }
  for (const x of d.expEntities) if (!x.entity.trim()) e[`ent.${x.k}.entity`] = 'Name the entity.'
  return e
}

/** Messages of the server's validator that concern the compliance block, one line each. */
export function complianceIssues(issues: { path: string; message: string }[]): string[] {
  return issues.filter((i) => i.path === 'compliance' || i.path.startsWith('compliance.') || i.path.startsWith('compliance[')).map((i) => `${i.path}: ${i.message}`)
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
