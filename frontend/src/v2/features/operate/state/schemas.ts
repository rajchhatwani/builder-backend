import { defaultFor, resolve } from '../../../../forms/schemaLogic'
import type { JsonSchema } from '../../../../forms/types'
import jobs from '../../../../forms/schemas/jobs.json'
import workflows from '../../../../forms/schemas/workflows.json'
import observability from '../../../../forms/schemas/observability.json'

const bounds = (maximum: number) => ({ minimum: 1, maximum })
const choices = (...values: string[]) => ({ enum: values })
const name = (length = 40) => ({ pattern: `^[a-z][a-z0-9_]{0,${length - 1}}$`, maxLength: length })
const hint = (value: NonNullable<JsonSchema['x-ui']>) => ({ 'x-ui': value })
const collection = (maximum: number, itemLabel: string) => ({ maxItems: maximum, ...hint({ itemLabel }) })

type Changes = Record<string, Partial<JsonSchema>>
function decorate(original: JsonSchema, root: Changes, definitions: Record<string, Changes> = {}) {
  const update = (schema: JsonSchema, changes: Changes) => ({
    ...schema,
    properties: Object.fromEntries(Object.entries(schema.properties ?? {}).map(([key, value]) => [
      key, { ...value, ...changes[key], 'x-ui': { ...value['x-ui'], ...changes[key]?.['x-ui'] } },
    ])),
  })
  return {
    ...update(original, root),
    $defs: Object.fromEntries(Object.entries(original.$defs ?? {}).map(([key, schema]) => [key, update(schema, definitions[key] ?? {})])),
  }
}

const retry = (maximum: number) => ({
  max_attempts: bounds(maximum), backoff_seconds: bounds(86_400), backoff: choices('exponential', 'fixed'),
})

export const jobsSchema = {
  ...decorate(jobs, {
    jobs: collection(100, 'Job'), worker_groups: collection(20, 'Worker group'), schedules: collection(50, 'Schedule'),
  }, {
    SpecJob: { name: name(), queue: name(), timeout_seconds: bounds(21_600) },
    SpecJobQueue: { backend: choices('postgres', 'redis', 'rabbitmq') },
    SpecJobRetry: retry(50),
    SpecWorkerGroup: {
      name: name(30), concurrency: bounds(64), queues: { default: ['default'], minItems: 1, ...hint({ itemLabel: 'Queue' }) },
      placement: choices('same_server', 'separate_server'),
    },
    SpecJobSchedule: { name: name(), missed: choices('skip', 'catch_up_one') },
  }),
  ...hint({ order: ['enabled', 'queue', 'jobs', 'worker_groups', 'schedules'] }),
}

export const workflowSchema = {
  ...decorate(workflows, { runtime: choices('postgres', 'dbos', 'temporal'), workflows: collection(50, 'Workflow') }, {
    SpecWorkflowWorker: { concurrency: bounds(64) },
    SpecWorkflow: { name: name(), steps: collection(30, 'Step'), roles: hint({ itemLabel: 'Role' }),
      on_failure: choices('compensate', 'fail'), timeout_seconds: bounds(30 * 86_400) },
    SpecWorkflowStep: { name: name(), kind: choices('hook', 'job'), timeout_seconds: bounds(21_600) },
    SpecWorkflowRetry: retry(20),
  }),
  ...hint({ order: ['enabled', 'runtime', 'worker', 'workflows'] }),
}

export const obsSchema = decorate(observability as JsonSchema, {
  enabled: { default: false },
  sample_ratio: { minimum: 0, maximum: 1 },
  exclude_paths: { default: ['/health', '/ready'], maxItems: 20 },
  extra_redact_keys: { maxItems: 50 },
  service_name: hint({ label: 'Service name' }),
  db_spans: hint({ label: 'Database spans' }),
  expected_rps: hint({ label: 'Peak requests per second' }),
})

export function withDefaults(root: JsonSchema, raw: unknown, schema: JsonSchema = root): unknown {
  if (raw === undefined) return defaultFor(root, schema)
  if (raw === null) return null
  const node = resolve(root, schema)
  if (node.type === 'object' && node.properties && typeof raw === 'object') {
    const value = raw as Record<string, unknown>
    return Object.fromEntries(Object.entries(node.properties).map(([key, child]) =>
      [key, withDefaults(root, value[key], child)]))
  }
  if (node.type === 'array' && node.items && Array.isArray(raw)) {
    const item = node.items
    return raw.map(row => withDefaults(root, row, item))
  }
  return raw
}
