import type { PathErrors } from '../../forms/types'

type T = (key: string, variables?: Record<string, string | number>) => string
type Data = Record<string, unknown>
const rows = (value: unknown): Data[] => Array.isArray(value) ? value : []
const strings = (value: unknown): string[] => Array.isArray(value) ? value : []
const text = (value: unknown) => typeof value === 'string' ? value : ''
const pythonKeywords = new Set('False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield'.split(' '))

export function validCron(value: string) {
  const fields = value.trim().split(/\s+/)
  const ranges = [[0, 59], [0, 23], [1, 31], [1, 12], [0, 6]]
  return fields.length === ranges.length && fields.every((field, index) => {
    const [low, high] = ranges[index]
    const inRange = (part: string) => /^\d{1,2}$/.test(part) && +part >= low && +part <= high
    return field.split(',').every(part => {
      const match = /^(\*|\d{1,2}(?:-\d{1,2})?)(?:\/(\d{1,2}))?$/.exec(part)
      if (!match) return false
      const [, body, step] = match
      const [start, end] = body.split('-')
      if (step && (+step < 1 || +step > high - low + 1 || body !== '*' && !end)) return false
      return body === '*' || inRange(start) && (!end || inRange(end) && +start <= +end)
    })
  })
}

export function validZone(value: string) {
  if (!value || /^[+-]/.test(value)) return false
  try {
    new Intl.DateTimeFormat('en', { timeZone: value })
    return true
  } catch {
    return false
  }
}

export function observationValidation(value: Data, t: T): PathErrors {
  const errors: PathErrors = {}
  if (!value.enabled) return errors
  const add = (field: string, key: string) => { errors[field] = [t('operate.validation.' + key)] }
  const name = value.service_name
  const ratio = value.sample_ratio
  const rps = value.expected_rps
  const paths = strings(value.exclude_paths)
  if (name && !/^[a-z][a-z0-9_-]{0,62}$/.test(text(name))) add('service_name', 'service')
  if (typeof ratio !== 'number' || !Number.isFinite(ratio) || ratio < 0 || ratio > 1) add('sample_ratio', 'ratio')
  if (rps != null && (typeof rps !== 'number' || !Number.isInteger(rps) || rps < 1 || rps > 1_000_000)) add('expected_rps', 'rps')
  if (paths.some(path => !/^\/[a-zA-Z0-9/_.-]{0,100}$/.test(path))) add('exclude_paths', 'path')
  else if (new Set(paths).size !== paths.length) add('exclude_paths', 'duplicatePath')
  if (strings(value.extra_redact_keys).some(key => !/^[a-z][a-z0-9_.-]{1,39}$/.test(key))) add('extra_redact_keys', 'key')
  return errors
}

export function jobValidation(value: Data, t: T): PathErrors {
  const errors: PathErrors = {}
  if (!value.enabled) return errors
  const add = (field: string, key: string) => { errors[field] = [t('operate.validation.' + key)] }
  const jobs = rows(value.jobs)
  const names = jobs.map(job => job.name)
  const queues = jobs.map(job => job.queue)
  if ((value.queue as Data | undefined)?.backend !== 'postgres') add('queue.backend', 'backend')
  jobs.forEach((job, index) => {
    const handler = text(job.handler)
    if (!/^[a-z_][a-z0-9_]{0,59}$/.test(handler) || pythonKeywords.has(handler)) add(`jobs.${index}.handler`, 'handler')
  })
  for (const collection of ['jobs', 'worker_groups', 'schedules']) {
    const items = rows(value[collection])
    items.forEach((row, index) => {
      if (items.findIndex(item => item.name === row.name) < index) add(`${collection}.${index}.name`, 'duplicate')
    })
  }
  rows(value.worker_groups).forEach((group, index) => {
    strings(group.queues).forEach((queue, position) => {
      if (!queues.includes(queue)) add(`worker_groups.${index}.queues.${position}`, 'pickQueue')
    })
  })
  rows(value.schedules).forEach((schedule, index) => {
    const path = `schedules.${index}`
    if (!names.includes(schedule.job)) add(path + '.job', 'pickJob')
    if (!validCron(text(schedule.cron))) add(path + '.cron', 'cron')
    if (!validZone(text(schedule.timezone))) add(path + '.timezone', 'zone')
  })
  return errors
}

export function workflowValidation(value: Data, t: T, jobNames?: string[]): PathErrors {
  const errors: PathErrors = {}
  if (!value.enabled) return errors
  const add = (field: string, key: string) => { errors[field] = [t('operate.validation.' + key)] }
  if (value.runtime !== 'postgres') add('runtime', 'runtime')
  const flows = rows(value.workflows)
  flows.forEach((flow, i) => {
    const path = `workflows.${i}`
    if (flows.findIndex(item => item.name === flow.name) < i) add(path + '.name', 'duplicate')
    const steps = rows(flow.steps)
    steps.forEach((step, j) => {
      const stepPath = path + `.steps.${j}`
      if (steps.findIndex(item => item.name === step.name) < j) add(stepPath + '.name', 'duplicate')
      if (step.kind === 'job' && (!step.job || jobNames && !jobNames.includes(text(step.job)))) add(stepPath + '.job', 'stepJob')
      if (step.kind === 'hook' && step.job) add(stepPath + '.job', 'hookJob')
    })
  })
  return errors
}

export function reportValidation(value: {
  name: string; metric_keys: string[]; schedule: string; timezone: string
}, t: T): Record<string, string> {
  const out: Record<string, string> = {}
  if (!value.name.trim() || value.name.trim().length > 120) out.name = t('operate.validation.reportName')
  if (value.metric_keys.length < 1 || value.metric_keys.length > 20) out.metric_keys = t('operate.validation.take')
  if (value.schedule.trim().length > 100 || !validCron(value.schedule)) out.schedule = t('operate.validation.cron')
  if (value.timezone.trim().length > 64 || !validZone(value.timezone.trim())) out.timezone = t('operate.validation.zone')
  return out
}

export function metricTextValidation(value: { label: string; unit: string }, t: T): Record<string, string> {
  const out: Record<string, string> = {}
  if (!value.label.trim() || value.label.trim().length > 120) out.label = t('operate.validation.metricName')
  if (value.unit.trim().length > 30) out.unit = t('operate.validation.metricUnit')
  return out
}

export function metricFilterValidation(value: string, op: string, type: string, t: T) {
  const items = op === 'in' ? value.split(',').map(part => part.trim()) : [value.trim()]
  if (items.length > 100) return t('operate.validation.filterLimit')
  if (items.some(item => !item)) return t('operate.validation.filterValue')
  if (type === 'date' && items.some(item => !/^\d{4}-\d{2}-\d{2}$/.test(item) || Number.isNaN(Date.parse(item)) ||
    new Date(item).toISOString().slice(0, 10) !== item)) return t('operate.validation.filterDate')
  if (type === 'datetime' && items.some(item => !/^\d{4}-\d{2}-\d{2}T/.test(item) || !Number.isFinite(Date.parse(item)))) return t('operate.validation.filterDateTime')
}
