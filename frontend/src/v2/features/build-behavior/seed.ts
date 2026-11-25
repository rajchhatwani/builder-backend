import type { SeedEntityBody, SeedGeneratorBody, SeedProfileBody, SequenceBody } from '../../../api/types'
import { looksSecretName } from '../../validators'
import type { CatalogEntity } from './api/behavior'
import { objectValue, recordList } from './blocks'

export const wholeTypes = ['integer', 'bigint']
const seedable = ['string', 'text', 'integer', 'bigint', 'float', 'decimal', 'boolean', 'date', 'datetime', 'enum']
const generators: Record<string, string[]> = {
  constant: seedable, one_of: seedable, sequence: ['string', 'text', ...wholeTypes], int_range: wholeTypes,
  decimal_range: ['decimal', 'float'], date_range: ['date', 'datetime'], bool_ratio: ['boolean'],
  words: ['string', 'text'], email: ['string', 'text'],
}
export type Column = CatalogEntity['columns'][number]
type Reference = CatalogEntity['references'][number]
export type SeedTarget = { name: string; column?: Column; reference?: Reference; state?: boolean; options: string[]; required: boolean }

export function targetsFor(entity: CatalogEntity, sequences: SequenceBody[]): SeedTarget[] {
  const numbered = new Set(sequences.filter(sequence => sequence.entity === entity.name).map(sequence => sequence.field))
  return [
    ...entity.columns.filter(column => !numbered.has(column.name)).map(column => {
      const state = column.name === entity.machine?.field
      const options = state ? ['state'] : Object.entries(generators).filter(([generator, types]) =>
        types.includes(column.type) && (!column.unique || ['sequence', 'email'].includes(generator)) &&
        (!looksSecretName(column.name) || !['constant', 'one_of', 'words'].includes(generator))).map(([name]) => name)
      return { name: column.name, column, options, state, required: column.required && column.default == null && !state }
    }),
    ...entity.references.map(reference => ({ name: reference.column, reference, options: ['reference'], required: reference.required })),
  ]
}

export function reachable(entity: CatalogEntity) {
  const machine = entity.machine
  if (!machine) return []
  const declared = entity.columns.find(column => column.name === machine.field)?.enum_values ?? []
  const states = new Set([machine.initial])
  for (const _ of declared) {
    for (const transition of machine.transitions ?? []) {
      if (transition.from_states?.some(state => states.has(state))) states.add(transition.to_state)
    }
  }
  return declared.filter(state => states.has(state))
}

export function tenantScoped(spec: Record<string, unknown> | undefined, entity: CatalogEntity) {
  const auth = objectValue(spec?.auth)
  if (auth.enabled !== true || auth.multi_tenant !== true) return false
  const model = objectValue(spec?.authorization).model
  if (model === 'abac' || model === 'pbac') return true
  return recordList(auth.permissions).some(permission => permission.entity === entity.name &&
    permission.row_rule === 'tenant' && typeof permission.operation === 'string' && entity.options?.operations.includes(permission.operation))
}

export function freshProfile(profiles: SeedProfileBody[]) {
  const names = new Set(profiles.map(profile => profile.name))
  let name = ['demo', 'dev', 'test'].find(item => !names.has(item))
  if (!name) {
    let suffix = 1
    while (names.has('profile_' + suffix)) suffix++
    name = 'profile_' + suffix
  }
  return { name, seed: 42, as_of: '2026-01-01', tenants: 0, entities: [] }
}

export function freshPlan(entity: string): SeedEntityBody {
  return { entity, count: 10, fields: [] }
}

export function typedSeedValue(value: string, type?: string) {
  if (type === 'boolean' && /^(true|false)$/i.test(value)) return value.toLowerCase() === 'true'
  if (type && [...wholeTypes, 'float'].includes(type) && value.trim() && Number.isFinite(Number(value))) return Number(value)
  return value
}

export function preferredGenerator(target: SeedTarget) {
  if (target.reference || target.state) return target.options[0]
  const preferred: Partial<Record<Column['type'], string>> = {
    enum: 'one_of', boolean: 'bool_ratio', date: 'date_range', datetime: 'date_range', integer: 'int_range',
    bigint: 'int_range', float: 'decimal_range', decimal: 'decimal_range', string: 'words', text: 'words',
  }
  const kind = target.column?.type && preferred[target.column.type]
  if (target.column?.unique && /mail/i.test(target.name) && target.options.includes('email')) return 'email'
  return kind && target.options.includes(kind) ? kind : target.options[0]
}

export function makeGenerator(type: string, target: SeedTarget, entity: CatalogEntity, asOf: string): SeedGeneratorBody {
  const column = target.column
  const clip = (number: number) => Math.min(column?.max_value ?? Infinity, Math.max(column?.min_value ?? -Infinity, number))
  const year = /^\d{4}/.exec(asOf)?.[0] ?? '2026'
  switch (type) {
    case 'constant': return { type, value: column?.type === 'boolean' ? true : column?.enum_values?.[0] ?? '' }
    case 'one_of': return { type, values: column?.type === 'boolean' ? [true, false] : column?.enum_values ?? [] }
    case 'sequence': return { type, start: 1, ...(wholeTypes.includes(column?.type ?? '') ? {} : { prefix: '', width: 5 }) }
    case 'int_range': return { type, min: clip(1), max: clip(100) }
    case 'decimal_range': return { type, min: String(clip(0)), max: String(clip(100)), places: 2 }
    case 'date_range': return { type, min: year + '-01-01', max: year + '-12-28' }
    case 'bool_ratio': return { type, ratio: 0.5 }
    case 'words': return { type, min_words: 1, max_words: Math.max(1, Math.min(3, Math.floor(((column?.max_length ?? 23) + 1) / 8))) }
    case 'email': return { type, prefix: 'user' }
    case 'reference': return { type, entity: target.reference?.target, pick: target.reference?.unique ? 'cycle' : 'random' }
    case 'state': return { type, weights: Object.fromEntries(reachable(entity).map(state => [state, state === entity.machine?.initial ? 1 : 0])) }
    default: return { type }
  }
}
