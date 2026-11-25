import { defaultFor } from '../../../../forms/schemaLogic'
import type { JsonSchema } from '../../../../forms/types'
import notificationsJson from '../../../../forms/schemas/notifications.json'
import webhooksJson from '../../../../forms/schemas/webhooks.json'
import type { ConnectSpec } from '../api/connect'
import { notificationChannels } from '../api/blocks'
import type { Notifications, Webhooks } from '../api/blocks'

function numberRange(minimum: number, maximum: number, value: number, type = 'integer'): JsonSchema {
  return { type, minimum, maximum, default: value }
}

const channel: JsonSchema = { type: 'string', enum: [...notificationChannels] }
const template: JsonSchema = {
  type: 'object', title: 'Template', required: ['channel', 'body'],
  properties: {
    channel, subject: { type: 'string', maxLength: 200 },
    body: { type: 'string', 'x-ui': { widget: 'textarea' } },
    html: { type: 'boolean' },
  },
}
const typeFields: JsonSchema = {
  type: 'object', title: 'Notification type', required: ['name'],
  properties: {
    name: { type: 'string', maxLength: 40, pattern: '^[a-z][a-z0-9_]{0,39}$' },
    category: { type: 'string', enum: ['optional', 'transactional'] },
    channels: { type: 'array', items: channel, maxItems: 3, 'x-ui': { itemLabel: 'Channel' } },
    variables: { type: 'array', items: { type: 'string' }, 'x-ui': { widget: 'csv' }, maxItems: 30 },
    default_enabled: { type: 'boolean', default: true },
    on_event: notificationsJson.$defs.SpecNotificationType.properties.on_event,
    recipient_key_field: notificationsJson.$defs.SpecNotificationType.properties.recipient_key_field,
    address_fields: { type: 'object', title: 'Address fields' },
    templates: { type: 'array', items: template, maxItems: 3, 'x-ui': { itemLabel: 'Template' } },
  },
}

export const notificationSchema: JsonSchema = {
  type: 'object', required: ['max_attempts', 'backoff_seconds', 'retention_days'],
  properties: {
    enabled: notificationsJson.properties.enabled,
    admin_role: notificationsJson.properties.admin_role,
    max_attempts: numberRange(1, 10, 5),
    backoff_seconds: numberRange(1, 3600, 30),
    retention_days: numberRange(1, 3650, 90),
    types: { type: 'array', items: typeFields, maxItems: 100, 'x-ui': { itemLabel: 'Type' } },
  },
}

export const webhookSchema: JsonSchema = {
  type: 'object',
  required: ['timeout_seconds', 'max_consecutive_failures', 'max_payload_bytes', 'secret_overlap_hours'],
  properties: {
    enabled: webhooksJson.properties.enabled,
    admin_role: webhooksJson.properties.admin_role,
    events: { type: 'array', items: { type: 'string' }, maxItems: 200, 'x-ui': { itemLabel: 'Event' } },
    allow_http: webhooksJson.properties.allow_http,
    allowed_ports: { type: 'array', items: { type: 'integer', minimum: 1, maximum: 65535 }, maxItems: 10, 'x-ui': { itemLabel: 'Port' } },
    timeout_seconds: numberRange(1, 60, 10, 'number'),
    max_consecutive_failures: numberRange(1, 100, 5),
    max_payload_bytes: numberRange(1024, 1048576, 262144),
    secret_overlap_hours: numberRange(1, 720, 24),
    inbound: { type: 'array', maxItems: 50, 'x-ui': { itemLabel: 'Receiver' }, items: {
      type: 'object', required: ['name', 'tolerance_seconds', 'max_body_bytes', 'dedupe_days'],
      properties: {
        name: { type: 'string', minLength: 2, maxLength: 40, pattern: '^[a-z][a-z0-9_]{1,39}$' },
        tolerance_seconds: numberRange(30, 3600, 300),
        max_body_bytes: numberRange(1024, 1048576, 262144),
        dedupe_days: numberRange(1, 90, 7),
      },
    } },
  },
}

export const notificationDefaults = defaultFor(notificationSchema, notificationSchema) as Notifications
export const webhookDefaults = defaultFor(webhookSchema, webhookSchema) as Webhooks
const eventPrefix = (name: string) => name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase()
export function specEvents(spec: ConnectSpec, transitions: boolean) {
  const machines = new Set(spec.state_machines?.map(row => row.entity))
  return spec.entities.flatMap(entity => {
    const operations = transitions && machines.has(entity.name) ? ['created', 'updated', 'deleted', 'transitioned'] : ['created', 'updated', 'deleted']
    return operations.map(operation => eventPrefix(entity.name) + '.' + operation)
  }).sort()
}

export function eventFields(spec: ConnectSpec, event: string | null) {
  const entity = spec.entities.find(entity => event?.split('.')[0] === eventPrefix(entity.name))
  return entity ? [...new Set(['id', ...entity.fields.filter(field => field.type !== 'json').map(field => field.name),
    ...(spec.relations ?? []).filter(relation => relation.kind === 'one_to_many' && relation.to_entity === entity.name)
      .map(relation => relation.to_name + '_id')])].sort() : []
}
