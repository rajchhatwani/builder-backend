import type { HookBody, HookFieldBody } from '../../../api/types'
import type { Catalog, CatalogEntity } from './api/behavior'

const stages = ['before_save', 'validate', 'after_save', 'after_commit']
export const hookTypes = ['string', 'int', 'float', 'decimal', 'bool', 'date', 'datetime', 'uuid']
export const fixedOutput: Record<string, HookFieldBody[]> = {
  validate: [{ name: 'valid', type: 'bool', required: true }, { name: 'message', type: 'string', required: false }],
  transition_guard: [{ name: 'allowed', type: 'bool', required: true }, { name: 'reason', type: 'string', required: false }],
}
const fieldTypes: Record<string, string> = {
  string: 'string', text: 'string', enum: 'string', integer: 'int', bigint: 'int', float: 'float',
  decimal: 'decimal', boolean: 'bool', date: 'date', datetime: 'datetime', uuid: 'uuid',
}

export const pointStage = (point: string) => point.split('.')[1]?.split('(')[0] ?? ''
export const pointsFor = ({ entities }: Catalog) => entities.flatMap(entity => [
  ...stages.map(stage => ({ entity: entity.name, stage, transition: undefined, value: entity.name + '.' + stage })),
  ...(entity.machine?.transitions ?? []).filter(item => !item.auto).map(item => ({
    entity: entity.name, stage: 'transition_guard', transition: item.name,
    value: entity.name + '.transition_guard(' + item.name + ')',
  })),
])

export function hookFields(entity?: CatalogEntity): HookFieldBody[] {
  return entity ? [{ name: 'id', type: 'uuid', required: true }, ...entity.columns.flatMap(field =>
    fieldTypes[field.type] && field.name !== 'id' ? [{ name: field.name, type: fieldTypes[field.type], required: field.required }] : [])] : []
}

export const legalPolicies = (stage: string) => fixedOutput[stage] ? ['fail_closed'] : stage === 'after_commit'
  ? ['fail_open', 'fallback'] : ['fail_closed', 'fail_open', 'fallback']

export const ownerLocked = (hook: HookBody) => Boolean(hook.effects?.length || hook.effect_budget)
export const stubPath = (name: string) => 'app/custom/hooks/' + name + '.py'

const defaults = (name: string) => {
  const stem = name.split('_').map(part => part.charAt(0).toUpperCase() + part.slice(1)).join('')
  return { input: stem ? stem.slice(0, 35) + 'Input' : '', output: stem ? stem.slice(0, 34) + 'Result' : '' }
}
export function rename(hook: HookBody, name: string): HookBody {
  const previous = defaults(hook.name)
  const next = defaults(name)
  return { ...hook, name,
    input: { ...hook.input, name: hook.input.name === previous.input ? next.input : hook.input.name },
    output: { ...hook.output, name: hook.output.name === previous.output ? next.output : hook.output.name },
  }
}

export function retarget(hook: HookBody, point: string, kind: string, entity?: CatalogEntity): HookBody {
  const stage = pointStage(point)
  const effectiveKind = stage === 'after_commit' ? kind : 'pure'
  const newPoint = hook.point !== point
  const policy = hook.failure_policy && legalPolicies(stage).includes(hook.failure_policy) ? hook.failure_policy : null
  const fields = hookFields(entity)
  const keep = fields.filter(field => hook.input.fields?.some(previous => previous.name === field.name))
  const settable = fields.find(field => field.name !== 'id' && field.name !== entity?.machine?.field)
  const output = fixedOutput[stage] ?? (stage === 'before_save' ? settable ? [settable] : [] : [{ name: 'done', type: 'bool', required: true }])
  const effect = effectiveKind === 'effect'
  return { ...hook, point, kind: effectiveKind, failure_policy: policy,
    input: { ...hook.input, fields: newPoint ? keep.length ? keep : fields.slice(0, 1) : hook.input.fields },
    output: { ...hook.output, fields: newPoint ? output : hook.output.fields },
    fallback: policy === 'fallback' && !newPoint ? hook.fallback : null,
    budget: {
      cpu_ms: Math.min(hook.budget?.cpu_ms ?? 200, effect ? 4000 : 1000),
      rows: effect ? hook.budget?.rows ?? 0 : 0, outbound_calls: 0,
    },
    reads: effect ? hook.reads : [],
    effects: effect ? hook.effects : [],
    effect_budget: effect ? hook.effect_budget : null,
  }
}

export function blankHook(point: string, entity?: CatalogEntity): HookBody {
  return retarget({ name: '', point: '', input: { name: '' }, output: { name: '' } }, point, 'pure', entity)
}

export function stubFor(hook: HookBody) {
  const kind = hook.kind ?? 'pure'
  if (!/^[a-z][a-z0-9_]{0,39}$/.test(hook.name) || ![hook.input.name, hook.output.name].every(name =>
    /^[A-Z][A-Za-z0-9]{0,39}$/.test(name)) || !/^[A-Za-z][\w]*\.(before_save|validate|after_save|after_commit|transition_guard\([\w]+\))$/.test(hook.point) ||
    !['pure', 'effect'].includes(kind)) return null
  const path = stubPath(hook.name)
  const signature = 'def ' + hook.name + '(data: ' + hook.input.name + ') -> ' + hook.output.name + ':  # platform:signature (fixed)'
  return { path, signature, code: [
    '# ' + path, '# platform:hook ' + hook.name + '  point=' + hook.point + '  kind=' + kind + '  contract=v1',
    'from app.hooks_gen.contracts import ' + [hook.input.name, hook.output.name].sort().join(', '), '', '',
    signature, '    # <agent:body hook=' + hook.name + '>', '    raise NotImplementedError', '    # </agent:body>', '',
  ].join('\n') }
}
