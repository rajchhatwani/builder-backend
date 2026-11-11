import { ApiError } from '../../api/client'
import type { MetricDefinition, MetricGroup, MetricRead, ReportBody, ReportMetricValue, ReportRead } from '../../api/types'

export type SpecField = { name: string; type: string }
export type SpecEntity = { name: string; fields: SpecField[] }

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

export const AGGS = [
  { id: 'count', label: 'Count of records' },
  { id: 'sum', label: 'Sum' },
  { id: 'avg', label: 'Average' },
  { id: 'min', label: 'Smallest' },
  { id: 'max', label: 'Largest' },
  { id: 'count_distinct', label: 'Count of different values' },
] as const

export const OPS = [
  { id: 'eq', label: 'is' },
  { id: 'ne', label: 'is not' },
  { id: 'gt', label: 'is above' },
  { id: 'gte', label: 'is at least' },
  { id: 'lt', label: 'is below' },
  { id: 'lte', label: 'is at most' },
  { id: 'in', label: 'is one of' },
] as const

const NUMERIC = new Set(['integer', 'bigint', 'float', 'decimal'])
const ORDERED = new Set([...NUMERIC, 'date', 'datetime'])
const SCALAR = new Set([...ORDERED, 'string', 'text', 'boolean', 'uuid', 'enum'])
const NUMERIC_AGGS = new Set(['sum', 'avg', 'min', 'max'])
const KEY_RE = /^[a-z][a-z0-9_]{0,59}$/
export const MAX_FILTERS = 10

/** The entities (and typed fields) the project spec declares. Anything malformed is skipped. */
export function entitiesOf(spec: Record<string, unknown>): SpecEntity[] {
  const out: SpecEntity[] = []
  for (const e of Array.isArray(spec.entities) ? spec.entities : []) {
    if (!isObj(e) || typeof e.name !== 'string') continue
    const fields = (Array.isArray(e.fields) ? e.fields : [])
      .filter((f): f is Record<string, unknown> => isObj(f) && typeof f.name === 'string')
      .map((f) => ({ name: f.name as string, type: typeof f.type === 'string' ? f.type : 'string' }))
    out.push({ name: e.name, fields })
  }
  return out
}

export const isNumericType = (t: string) => NUMERIC.has(t)

/** Fields the field select offers for an aggregate: numbers only for sum/avg/min/max. */
export function fieldsForAgg(entity: SpecEntity | undefined, agg: string): SpecField[] {
  if (!entity) return []
  if (NUMERIC_AGGS.has(agg)) return entity.fields.filter((f) => NUMERIC.has(f.type))
  return entity.fields.filter((f) => SCALAR.has(f.type))
}

/** Fields that can be filtered or grouped on (plain values, not files or json). */
export const scalarFields = (entity: SpecEntity | undefined): SpecField[] => (entity ? entity.fields.filter((f) => SCALAR.has(f.type)) : [])

/** Operators the filter row offers for a field type. */
export const opsFor = (type: string) => OPS.filter((o) => ['gt', 'gte', 'lt', 'lte'].includes(o.id) ? ORDERED.has(type) : true)

export type FilterForm = { field: string; op: string; value: string }
export type MetricForm = {
  key: string
  label: string
  entity: string
  agg: string
  field: string
  group_by: string
  unit: string
  filters: FilterForm[]
}

export const emptyMetricForm = (entity = ''): MetricForm => ({ key: '', label: '', entity, agg: 'count', field: '', group_by: '', unit: '', filters: [] })

const showValue = (v: unknown): string => (Array.isArray(v) ? v.map(String).join(', ') : String(v ?? ''))

export function definitionToForm(d: MetricDefinition): MetricForm {
  return {
    key: d.key,
    label: d.label,
    entity: d.entity,
    agg: d.agg,
    field: d.field ?? '',
    group_by: d.group_by ?? '',
    unit: d.unit ?? '',
    filters: (d.filter ?? []).map((f) => ({ field: f.field, op: f.op, value: showValue(f.value) })),
  }
}

/** A filter literal in the shape the server wants for the field type. Numbers stay TEXT so decimals keep every digit. */
function literal(raw: string, type: string): unknown {
  const t = raw.trim()
  if (type === 'boolean') return t.toLowerCase() === 'true'
  return t
}

export function formToDefinition(form: MetricForm, entity: SpecEntity | undefined): MetricDefinition {
  const typeOf = (name: string) => entity?.fields.find((f) => f.name === name)?.type ?? 'string'
  const def: MetricDefinition = {
    key: form.key.trim(),
    label: form.label.trim(),
    entity: form.entity,
    agg: form.agg,
    filter: form.filters.map((f) => ({
      field: f.field,
      op: f.op,
      value: f.op === 'in' ? f.value.split(',').map((p) => literal(p, typeOf(f.field))) : literal(f.value, typeOf(f.field)),
    })),
  }
  if (form.field) def.field = form.field
  if (form.group_by) def.group_by = form.group_by
  if (form.unit.trim()) def.unit = form.unit.trim()
  return def
}

export type FormProblem = { field: string; message: string }

/** Hints shown before the request; the server stays the judge (metric_invalid). */
export function validateMetricForm(form: MetricForm, entities: SpecEntity[], editing: boolean, takenKeys: string[]): FormProblem[] {
  const out: FormProblem[] = []
  if (!KEY_RE.test(form.key.trim())) out.push({ field: 'key', message: 'Use lowercase letters, digits and underscores, starting with a letter (for example open_invoices).' })
  else if (!editing && takenKeys.includes(form.key.trim())) out.push({ field: 'key', message: 'A metric with this key already exists.' })
  if (!form.label.trim()) out.push({ field: 'label', message: 'Give the metric a name people will recognise.' })
  const entity = entities.find((e) => e.name === form.entity)
  if (!entity) {
    out.push({ field: 'entity', message: 'Choose which entity to measure.' })
    return out
  }
  if (form.agg !== 'count' && !form.field) out.push({ field: 'field', message: `${AGGS.find((a) => a.id === form.agg)?.label ?? form.agg} needs a field${NUMERIC_AGGS.has(form.agg) ? ' with numbers' : ''}.` })
  if (form.field && !fieldsForAgg(entity, form.agg).some((f) => f.name === form.field)) out.push({ field: 'field', message: 'This field cannot be used with the chosen calculation.' })
  if (form.filters.length > MAX_FILTERS) out.push({ field: 'filters', message: `At most ${MAX_FILTERS} filters.` })
  form.filters.forEach((f, i) => {
    if (!f.field) out.push({ field: `filter-${i}`, message: `Filter ${i + 1}: choose a field.` })
    else if (f.value.trim() === '') out.push({ field: `filter-${i}`, message: `Filter ${i + 1}: enter a value.` })
    else if (f.op !== 'in') {
      const t = entity.fields.find((x) => x.name === f.field)?.type ?? ''
      if (NUMERIC.has(t) && !/^[+-]?\d+(\.\d+)?$/.test(f.value.trim())) out.push({ field: `filter-${i}`, message: `Filter ${i + 1}: ${f.field} is a number.` })
    }
  })
  return out
}

// -- values ---------------------------------------------------------------------------------------

/** Adds thousands separators to the digits of an exact decimal text without ever going through a float. */
export function groupDigits(text: string): string {
  const m = /^([+-]?)(\d+)(\.\d+)?$/.exec(text)
  if (!m) return text
  return `${m[1]}${m[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${m[3] ?? ''}`
}

/** What a metric value looks like on screen. Decimal strings keep every digit; null is "No value yet". */
export function formatValue(value: number | string | null | undefined, unit?: string | null): string {
  if (value === null || value === undefined) return 'No value yet'
  const text = groupDigits(String(value))
  return unit ? `${text} ${unit}` : text
}

export function formatGroups(groups: MetricGroup[] | null | undefined, unit?: string | null): { label: string; value: string }[] {
  return (groups ?? []).map((g) => ({ label: g.key === null || g.key === '' ? '(none)' : String(g.key), value: formatValue(g.value, unit) }))
}

/** One metric's slot out of a report payload; tolerates a bare value or a stored error. */
export function slotOf(values: Record<string, ReportMetricValue | string | number | null>, key: string): ReportMetricValue {
  if (!(key in values)) return { error: 'No value was stored for this metric.' }
  const v = values[key]
  if (isObj(v)) return v as ReportMetricValue
  return { value: v as string | number | null }
}

/** The text a slot shows. */
export function slotText(slot: ReportMetricValue, unit?: string | null): string {
  if (slot.error) return slot.error === 'quota_exceeded' ? 'Not computed: plan limit reached' : `Not computed: ${slot.error}`
  return formatValue(slot.value, unit)
}

// -- schedules ------------------------------------------------------------------------------------

export const CRON_PRESETS = [
  { id: 'daily', label: 'Every day at 08:00', cron: '0 8 * * *' },
  { id: 'weekdays', label: 'Weekdays at 08:00', cron: '0 8 * * 1-5' },
  { id: 'monday', label: 'Every Monday at 08:00', cron: '0 8 * * 1' },
  { id: 'monthly', label: 'First day of the month at 08:00', cron: '0 8 1 * *' },
  { id: 'hourly', label: 'Every hour', cron: '0 * * * *' },
] as const

export const TIMEZONES = ['UTC', 'America/New_York', 'America/Los_Angeles', 'Europe/London', 'Europe/Berlin', 'Asia/Kolkata', 'Asia/Tokyo', 'Australia/Sydney']

/** The preset id for a cron text, or 'custom'. */
export function presetOf(cron: string): string {
  return CRON_PRESETS.find((p) => p.cron === cron.trim())?.id ?? 'custom'
}

export function cronLabel(cron: string): string {
  const p = CRON_PRESETS.find((x) => x.cron === cron.trim())
  return p ? p.label : `Custom schedule (${cron.trim()})`
}

/** Five space-separated fields made of digits and , - * / only. The server checks the rest. */
export function cronHint(cron: string): string | null {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5 || parts.some((p) => !/^[\d*,\-/]+$/.test(p))) return 'A schedule has five parts: minute, hour, day of month, month, day of week (for example 0 8 * * 1).'
  return null
}

export type ReportForm = { name: string; metric_keys: string[]; schedule: string; timezone: string; enabled: boolean }
export const emptyReportForm = (): ReportForm => ({ name: '', metric_keys: [], schedule: CRON_PRESETS[0].cron, timezone: 'UTC', enabled: true })
export const reportToForm = (r: ReportRead): ReportForm => ({ name: r.name, metric_keys: [...r.metric_keys], schedule: r.schedule, timezone: r.timezone, enabled: r.enabled })
export const formToReport = (f: ReportForm): ReportBody => ({ name: f.name.trim(), metric_keys: f.metric_keys, schedule: f.schedule.trim(), timezone: f.timezone.trim() || 'UTC', enabled: f.enabled })

export function validateReportForm(f: ReportForm): FormProblem[] {
  const out: FormProblem[] = []
  if (!f.name.trim()) out.push({ field: 'name', message: 'Give the report a name.' })
  if (f.metric_keys.length === 0) out.push({ field: 'metrics', message: 'Pick at least one metric.' })
  const hint = cronHint(f.schedule)
  if (hint) out.push({ field: 'schedule', message: hint })
  return out
}

export const toggleKey = (keys: string[], key: string): string[] => (keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key])

export const unitOf = (metrics: MetricRead[], key: string): string | null => metrics.find((m) => m.key === key)?.definition.unit ?? null

/** A plain message for a failed call, with the stable codes spelled out. */
export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.code === 'quota_exceeded') return quotaMessage(err.details)
    if (err.code === 'metric_in_use') return `This metric is still used by a report, so it was kept. ${err.message}. Remove it from the report first.`
    if (err.code === 'metric_too_large') return `This metric covers too many records to compute. Add a filter to narrow it. ${err.message}`
    if (err.code === 'metric_invalid') return `The metric is not valid: ${err.message}`
    if (err.code === 'report_invalid') return `The report is not valid: ${err.message}`
    return err.message
  }
  return err instanceof Error ? err.message : fallback
}

export function quotaMessage(details: unknown[]): string {
  const d = (details[0] ?? {}) as { limit?: unknown; used?: unknown; period_end?: unknown }
  const nums = typeof d.limit === 'number' && typeof d.used === 'number'
  const base = nums ? `Your plan allows ${d.limit} this period and ${d.used} are used.` : "Your plan's limit is used up."
  const until = typeof d.period_end === 'string' && d.period_end ? ` It resets on ${d.period_end.slice(0, 10)}.` : ''
  return `${base}${until} Nothing was changed; try again once there is room.`
}
