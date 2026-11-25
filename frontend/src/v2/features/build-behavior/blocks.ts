import { looksSecretName } from '../../validators'

export const entityNames = (spec?: Record<string, unknown>) => {
  const entities = spec?.entities
  if (Array.isArray(entities)) return entities.flatMap(entity => typeof entity?.name === 'string' ? [entity.name] : []).sort()
  return entities && typeof entities === 'object' ? Object.keys(entities).sort() : []
}

export function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function recordList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(objectValue) : []
}

export const eventPrefix = (name: string) => name.replace(/([a-z0-9])(?=[A-Z])/g, '$1_').toLowerCase()
export const effectKinds = ['email', 'sms', 'webhook', 'notification']
export const effectBudget = { calls_per_effect: 1, payload_bytes: 10000, outbound_per_minute: 30 }

export function provenance(author?: string | null) {
  return author === 'ai' || author === 'external' ? author : !author || author === 'trusted' ? 'human' : 'unknown'
}

const hiddenEventKey = /(pass(word|wd)?|secret|token|authorization|signature|api[-_]?key|cookie|credential|private[-_]?key|client[-_]?secret)/i
const hiddenEventTerms = ['accesskey', 'signingkey', 'secretkey', 'privatekey', 'apikey', 'secret', 'password', 'passwd',
  'passcode', 'passphrase', 'credential', 'authorization', 'bearer', 'cookie', 'creditcard', 'cardnumber', 'oauth']
const hiddenEventWords = new Set(['salt', 'totp', 'otp', 'pan', 'cvv', 'cvc', 'iban', 'ssn', 'pin', 'auth',
  'session', 'seed', 'pwd', 'token', 'signature', 'cookie', 'bearer'])

function eventKeyIsPublic(name: string, extra: string[]) {
  const lower = name.toLowerCase()
  const compact = lower.replace(/[^a-z0-9]/g, '')
  const words = name.split(/[^a-zA-Z0-9]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])/)
  return !looksSecretName(name) && !hiddenEventKey.test(name) && !extra.some(key => lower.includes(key)) &&
    !hiddenEventTerms.some(term => compact.includes(term)) &&
    !words.some(word => hiddenEventWords.has(word.toLowerCase()) || hiddenEventWords.has(word.toLowerCase().replace(/s$/, '')))
}

export function eventDataFields(spec: Record<string, unknown>, entity: string) {
  const regulated = objectValue(spec.regulated)
  const observability = objectValue(spec.observability)
  const extra = Array.isArray(observability.extra_redact_keys) ? observability.extra_redact_keys.flatMap(key =>
    typeof key === 'string' ? [key.toLowerCase()] : []) : []
  const protectedNames = new Set(regulated.enabled === true ? recordList(regulated.fields)
    .filter(rule => rule.entity === entity).map(rule => rule.field) : [])
  const columns = recordList(spec.entities).find(item => item.name === entity)?.fields
  const fields = recordList(columns).flatMap(field => typeof field.name === 'string' && field.type !== 'json' &&
    !protectedNames.has(field.name) && eventKeyIsPublic(field.name, extra) ? [field.name] : [])
  const refs = recordList(spec.relations).flatMap(relation => {
    if (relation.to_entity !== entity || typeof relation.to_name !== 'string' ||
      !['one_to_one', 'one_to_many'].includes(String(relation.kind))) return []
    const column = relation.to_name + '_id'
    return eventKeyIsPublic(column, extra) ? [column] : []
  })
  return ['id', ...fields, ...refs, 'created_at', 'updated_at']
}
