import type { Builder, Diagram, Spec, Translate } from './model'
import { active, cell, chain, choose, chooseRows, columns, graph, hub, named, objects, record, str, table, words } from './model'

export function relationship(spec: Spec, w: Translate, selection?: string, business = false): Diagram {
  const entities = objects(spec.entities)
  const entitiesByName = new Map(entities.map((entity, i) => [entity.name, i]))
  const relations = objects(spec.relations)
  const { picker, selected } = chooseRows(w('entity'), entities, selection)
  const entityNodes = entities.map(entity => ({
    name: str(entity.name), detail: business ? undefined : str(entity.table_name),
    members: business ? undefined : objects(entity.fields).map(field =>
      w('fieldMember', { name: str(field.name), type: str(field.type) })),
  }))
  const links = relations.flatMap((relation): [number, number, string][] => {
    const from = entitiesByName.get(relation.from_entity)
    const to = entitiesByName.get(relation.to_entity)
    return from === undefined || to === undefined ? [] : [[from, to, w(str(relation.kind))]]
  })
  return {
    ...graph(entityNodes, links),
    picker: business ? undefined : picker,
    tables: [
      columns(w, ['entity', 'relation', 'relatedEntity', 'relationName', 'onDelete', 'required'], relations,
        ['from_entity', 'kind', 'to_entity', 'from_name', 'on_delete', 'required'], w('relations')),
      ...(!business && selected ? [columns(w, ['field', 'type', 'required', 'unique', 'indexed'],
        [{ name: 'id', type: 'uuid', required: true }, ...objects(selected.fields)],
        ['name', 'type', 'required', 'unique', 'indexed'], w('fields'))] : []),
    ],
  }
}

function classes(spec: Spec, w: Translate, selection?: string): Diagram {
  const { picker, selected } = chooseRows(w('entity'), objects(spec.entities), selection)
  return {
    ...relationship(spec, w), picker,
    tables: selected ? [columns(w, ['field', 'type', 'required', 'unique', 'enumValues'], objects(selected.fields),
      ['name', 'type', 'required', 'unique', 'enum_values'], w('fields')),
    table([w('member'), w('kind')], [
      ...words(record(selected.options).operations).map(operation => [operation, w('apiOperation')]),
      ...objects(objects(spec.state_machines).find(machine => machine.entity === selected.name)?.transitions).map(step =>
        [str(step.name), w('transition')]),
      ...hooksFor(spec, str(selected.name)).map(hook => [str(hook.name), str(hook.point)]),
    ])] : [],
  }
}

function stateMachine(spec: Spec, w: Translate, selection?: string): Diagram {
  const { picker, selected } = chooseRows(w('stateMachine'), objects(spec.state_machines), selection, 'entity')
  if (!selected) return {}
  const fields = objects(objects(spec.entities).find(entity => entity.name === selected.entity)?.fields)
  const values = words(fields.find(field => field.name === selected.field)?.enum_values)
  const transitions = objects(selected.transitions)
  const states = [...new Set([...values, str(selected.initial), ...transitions.flatMap(item => [...words(item.from_states), str(item.to_state)])])].filter(Boolean)
  const links = transitions.flatMap((item): [number, number, string][] => words(item.from_states)
    .map(from => [states.indexOf(from), states.indexOf(str(item.to_state)), str(item.name)]))
  return {
    ...graph(states.map(name => ({ name, detail: name === selected.initial ? w('initialState') : undefined })), links),
    picker,
    tables: [columns(w, ['transition', 'fromState', 'toState', 'guard', 'roles', 'automatic'], transitions,
      ['name', 'from_states', 'to_state', 'when', 'roles', 'auto'])],
  }
}

export function hooksFor(spec: Spec, name: string) {
  return objects(spec.hooks).filter(hook => str(hook.point).startsWith(name + '.'))
}

export function lifecycle(spec: Spec, entity: Spec, w: Translate): Diagram {
  const name = str(entity.name)
  const hooks = hooksFor(spec, name)
  const hookNodes = (stage: string) => hooks.filter(hook => str(hook.point).slice(name.length + 1).startsWith(stage))
    .map(hook => ({ name: str(hook.name), detail: str(hook.failure_policy) }))
  return {
    ...chain([
      ...hookNodes('before_save'), { name: w('accessChecks') }, ...hookNodes('transition_guard('),
      ...hookNodes('validate'), { name: w('write'), detail: str(entity.table_name) },
      ...hookNodes('after_save'), { name: w('commit') }, ...hookNodes('after_commit'),
    ]),
    tables: [
      columns(w, ['hook', 'stage', 'kind', 'failurePolicy'], hooks, ['name', 'point', 'kind', 'failure_policy']),
      columns(w, ['sequence', 'field'], objects(spec.sequences).filter(sequence => sequence.entity === name), ['name', 'field']),
    ],
    note: active(spec.events) ? w('writesOutbox') : undefined,
  }
}

const verbs: Record<string, [string, boolean]> = {
  list: ['GET', false], get: ['GET', true], create: ['POST', false], replace: ['PUT', true],
  update: ['PATCH', true], delete: ['DELETE', true], head: ['HEAD', true],
}

function endpoints(spec: Spec, w: Translate, selection?: string): Diagram {
  const routes = objects(spec.entities).flatMap(entity => {
    const path = str(entity.plural_path)
    if (!path) return []
    const machine = objects(spec.state_machines).find(item => item.entity === entity.name)
    const crud = words(record(entity.options).operations).filter(op => Object.hasOwn(verbs, op)).map(op => {
      const [method, item] = verbs[op]
      const url = '/' + path + (item ? '/{item_id}' : '')
      return { value: method + ' ' + url, method, entity, transition: false }
    })
    return [...crud, ...objects(machine?.transitions).filter(item => !item.auto)
      .map(item => ({ value: 'POST /' + path + '/{item_id}/transitions/' + str(item.name), method: 'POST', entity, transition: true }))]
  })
  const picker = choose(w('endpoint'), routes.map(item => ({ value: item.value, label: item.value })), selection)
  const route = routes.find(item => item.value === picker.value)
  if (!route) return {}
  const write = route.method !== 'GET' && route.method !== 'HEAD'
  return { ...chain([
    { name: w('client'), detail: route.value },
    ...(active(spec.api_edge) ? [{ name: w('api_edge'), detail: w('applyChecks') }] : []),
    { name: w('generatedApi'), detail: w(route.transition ? 'checkTransition' : write ? 'validateWrite' : 'readAccessible') },
    { name: w('database'), detail: str(route.entity.table_name) },
    ...(write && active(spec.events) ? [{ name: w('outbox'), detail: w('relayAfterCommit') }] : []),
    { name: w('response'), detail: route.method === 'HEAD' ? w('headers') : undefined },
  ]), picker, tables: write ? lifecycle(spec, route.entity, w).tables : undefined }
}

function entityView(builder: (spec: Spec, entity: Spec, w: Translate) => Diagram): Builder {
  return (spec, w, selection) => {
    const { picker, selected } = chooseRows(w('entity'), objects(spec.entities), selection)
    return selected ? { ...builder(spec, selected, w), picker } : {}
  }
}

function roleView(spec: Spec, entity: Spec, w: Translate): Diagram {
  const auth = active(spec.auth) ? record(spec.auth) : {}
  const permissions = objects(auth.permissions).filter(permission => permission.entity === entity.name)
  const roles = objects(auth.roles)
  const assigned = permissions.flatMap(rule => words(rule.roles))
  const transitions = objects(objects(spec.state_machines).find(machine => machine.entity === entity.name)?.transitions)
    .filter(transition => !transition.auto)
  const roleNames = [...new Set([...roles.map(role => str(role.name)), ...assigned,
    ...transitions.flatMap(transition => words(transition.roles))])].filter(Boolean)
  const links = permissions.flatMap(rule => words(rule.roles).map((role): [number, number, string] =>
    [roleNames.indexOf(role), roleNames.length, str(rule.operation)]))
  links.push(...roles.flatMap((role): [number, number, string][] => roleNames.includes(str(role.inherits_from))
    ? [[roleNames.indexOf(str(role.name)), roleNames.indexOf(str(role.inherits_from)), w('inherits')]] : []))
  return {
    ...graph([...roleNames.map(name => ({ name, detail: str(roles.find(role => role.name === name)?.label) })),
      { name: str(entity.name), detail: w('entity') }], links),
    tables: [
      columns(w, ['operation', 'roles', 'rowRule'], permissions, ['operation', 'roles', 'row_rule']),
      columns(w, ['transition', 'roles', 'guard'], transitions, ['name', 'roles', 'when']),
    ],
  }
}

function authorization(spec: Spec, entity: Spec, w: Translate): Diagram {
  const authz = record(spec.authorization)
  const fields = objects(authz.field_access).filter(rule => rule.entity === entity.name)
  const policies = objects(authz.policies).filter(policy =>
    words(policy.actions).some(action => action === '*' || action.startsWith(str(entity.name) + '.')))
  return {
    ...chain(['objectLayer', 'rowLayer', 'fieldLayer', 'policyLayer'].map(key => ({ name: w(key) }))),
    tables: [
      ...(roleView(spec, entity, w).tables ?? []),
      table(['field', 'readRoles', 'writeRoles'].map(key => w(key)), fields.map(field => [
        str(field.field), field.read_roles == null ? w('followsOperation') : cell(field.read_roles) ?? w('noRoles'),
        field.write_roles == null ? w('followsOperation') : cell(field.write_roles) ?? w('noRoles'),
      ])),
      table([w('policy'), w('effect'), w('actions'), w('attachedRoles')], policies.map(policy => [
        str(policy.id), str(policy.effect), cell(policy.actions),
        Object.entries(record(authz.attachments)).filter(([, ids]) => words(ids).includes(str(policy.id))).map(([role]) => role).join(', '),
      ])),
    ],
  }
}

function swimlane(spec: Spec, w: Translate, selection?: string): Diagram {
  const { picker, selected } = chooseRows(w('entity'), objects(spec.state_machines), selection, 'entity')
  if (!selected) return {}
  const transitions = objects(selected.transitions)
  const lanes = new Map<string, Spec[]>()
  for (const transition of transitions) {
    const roles = words(transition.roles)
    for (const role of roles.length ? roles : [w(transition.auto ? 'automatic' : 'updateAccess')]) {
      lanes.set(role, [...(lanes.get(role) ?? []), transition])
    }
  }
  return {
    picker, note: w('outline'),
    tables: [...lanes.entries()].map(([role, steps]) =>
      columns(w, ['transition', 'fromState', 'toState', 'guard'], steps, ['name', 'from_states', 'to_state', 'when'], role)),
  }
}

function useCases(spec: Spec, entity: Spec, w: Translate): Diagram {
  const name = str(entity.name)
  const payments = record(spec.payments)
  const roles = (block: Spec, keys: string[], label: string) => active(block) && Object.keys(block).length
    ? keys.map(key => [w(label), key, cell(record(block.roles)[key])]) : []
  return { ...roleView(spec, entity, w), note: w('outline'),
    tables: [
      ...(roleView(spec, entity, w).tables ?? []),
      table([w('feature'), w('action'), w('roles')], [
        ...(record(payments.payable).entity === name ? roles(payments, ['create', 'refund', 'approve_refund'], 'payments') : []),
        ...roles(record(spec.storage), ['upload', 'share', 'delete'], 'storage'),
        ...(active(spec.workflows) ? objects(record(spec.workflows).workflows).map(workflow => [w('workflows'), str(workflow.name), cell(workflow.roles)]) : []),
      ]),
    ],
  }
}

function dependencies(spec: Spec, entity: Spec, w: Translate): Diagram {
  const name = str(entity.name)
  const related = objects(spec.relations).filter(relation => relation.from_entity === name || relation.to_entity === name)
  const machine = objects(spec.state_machines).find(item => item.entity === name)
  return hub({ name, detail: w('entity') }, [
    ...related.map(relation => ({ name: str(relation.from_entity === name ? relation.to_entity : relation.from_entity), detail: w(str(relation.kind)) })),
    ...named(hooksFor(spec, name), 'point'),
    ...named(objects(spec.sequences).filter(sequence => sequence.entity === name), 'field'),
    ...(machine ? [{ name: str(machine.field), detail: w('stateMachine') }] : []),
  ])
}

export const dataViews = {
  D05: relationship, D06: classes, D07: stateMachine, D09: entityView(lifecycle), D10: endpoints,
  D12: entityView(roleView), D14: entityView(authorization), D24: swimlane,
  D25: entityView(useCases), D31: entityView(dependencies),
}
