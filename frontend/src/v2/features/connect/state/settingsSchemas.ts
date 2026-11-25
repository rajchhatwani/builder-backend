import { defaultFor } from '../../../../forms/schemaLogic'
import type { JsonSchema } from '../../../../forms/types'
import type { ApiEdge, ApiPlatform, Providers } from '../api/blocks'

const text: JsonSchema = { type: 'string' }
const bool: JsonSchema = { type: 'boolean' }
const identifier = { ...text, pattern: '^[a-z][a-z0-9_]{0,39}$' }
const slug = { ...text, pattern: '^[a-z][a-z0-9_-]{0,39}$' }
const number = (minimum: number, maximum: number, value: number, type = 'integer'): JsonSchema =>
  ({ type, default: value, minimum, maximum })
const object = (properties: Record<string, JsonSchema>, required: string[] = []): JsonSchema =>
  ({ type: 'object', properties, required })
const optional = (schema: JsonSchema): JsonSchema => ({ anyOf: [schema, { type: 'null' }], 'x-ui': { optional: true } })
const rows = (itemLabel: string, items: JsonSchema, maxItems: number): JsonSchema =>
  ({ type: 'array', items, maxItems, 'x-ui': { itemLabel } })

export const providerKinds = ['email', 'sms', 'push', 'payments', 'storage', 'llm', 'generic']
export const providersSchema = object({
  enabled: bool, admin_role: { ...text, default: 'admin' },
  adapters: rows('Adapter', object({
    kind: { ...text, enum: providerKinds },
    name: { ...text, pattern: '^[a-z][a-z0-9_]{1,39}$' },
    settings: { type: 'object' },
  }, ['kind', 'name']), 50),
  timeout_seconds: number(0.1, 120, 10, 'number'),
  max_attempts: number(1, 10, 3),
  breaker_failures: number(1, 100, 5),
  breaker_reset_seconds: number(0.1, 3600, 30, 'number'),
}, ['admin_role', 'timeout_seconds', 'max_attempts', 'breaker_failures', 'breaker_reset_seconds'])

const mutationMethods = ['POST', 'PUT', 'PATCH', 'DELETE']
const allMethods = ['GET', 'HEAD', ...mutationMethods]
const methods = (choices: string[]) => rows('Method', { ...text, enum: choices }, choices.length)
const bucket = (capacity: number, refill: number) => object({
  capacity: number(1, 1_000_000, capacity), refill_per_second: number(0.001, 100_000, refill, 'number'),
}, ['capacity', 'refill_per_second'])
const route = { ...text, default: '/', pattern: '^/(?!.*(?:\\.\\.|//))[a-zA-Z0-9_./-]*$', maxLength: 200 }
const date = { ...text, pattern: '^\\d{4}-\\d{2}-\\d{2}$' }
export const edgeSchema = object({
  enabled: bool,
  idempotency: optional(object({
    methods: { ...methods(mutationMethods), default: ['POST'], minItems: 1 },
    ttl_hours: number(1, 168, 24),
    max_response_bytes: number(1024, 1_048_576, 65536),
  }, ['ttl_hours', 'max_response_bytes'])),
  rate_limits: optional(object({
    user: bucket(120, 2), tenant: optional(bucket(120, 2)), anonymous: bucket(30, 0.5), read_fail_open: bool,
    groups: rows('Group', object({
      name: identifier, path_prefix: route, methods: methods(allMethods),
      user: optional(bucket(120, 2)), tenant: optional(bucket(120, 2)), cost: number(1, 1_000_000, 1),
    }, ['name', 'path_prefix', 'cost']), 50),
  })),
  quotas: rows('Quota', object({
    meter: identifier, period: { ...text, enum: ['day', 'month'], default: 'month' },
    limit: number(1, 1_000_000_000_000, 1000), path_prefix: route, methods: methods(allMethods), cost: number(1, 1_000_000_000_000, 1),
  }, ['meter', 'period', 'limit', 'path_prefix', 'cost']), 50),
  versioning: optional(object({
    default: date, versions: { ...rows('Version', object({ date, note: { ...text, maxLength: 300 } }, ['date']), 50), minItems: 1 },
  }, ['default'])),
})

const rate = { ...text, pattern: '^[1-9][0-9]{0,6}/([1-9][0-9]{0,3})?(second|minute|hour|day)s?$' }
export const platformSchema = object({
  enabled: { ...bool, 'x-ui': { label: 'Public API and apps enabled' } },
  roles: { ...rows('Role', text, Number.MAX_SAFE_INTEGER), 'x-ui': { label: 'Roles that manage keys and apps', itemLabel: 'Role' } },
  rate_limit: { ...rate, default: '60/minute', 'x-ui': { label: 'Rate limit (production keys)' } },
  sandbox_rate_limit: { ...rate, default: '20/minute', 'x-ui': { label: 'Rate limit (sandbox keys)' } },
  key_ttl_days: { ...number(1, 365, 90), 'x-ui': { label: 'Key lifetime (days)' } },
  entities: { ...rows('Exposed entity', object({
    entity: text, fields: { type: 'array', items: text, 'x-ui': { label: 'Fields returned', itemLabel: 'Field' } },
    sandbox: { ...bool, 'x-ui': { label: 'Readable with a sandbox key too' } },
  }, ['entity']), 64), 'x-ui': { label: 'Exposed entities', itemLabel: 'Exposed entity' } },
  apps: rows('App', object({
    name: slug, title: text, scopes: { type: 'array', items: text, 'x-ui': { itemLabel: 'Scope' } },
    events: { type: 'array', items: slug, 'x-ui': { itemLabel: 'Event' } },
  }, ['name']), 32),
}, ['rate_limit', 'sandbox_rate_limit', 'key_ttl_days'])

export const providersDefaults = defaultFor(providersSchema, providersSchema) as Providers
export const edgeDefaults = defaultFor(edgeSchema, edgeSchema) as ApiEdge
export const platformDefaults = defaultFor(platformSchema, platformSchema) as ApiPlatform
