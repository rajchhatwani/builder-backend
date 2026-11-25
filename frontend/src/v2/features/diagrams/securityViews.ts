import type { Builder, Spec, Translate } from './model'
import { active, cell, chain, chooseRows, columns, graph, hub, objects, record, str, table, words } from './model'

const login: Builder = (spec, w) => {
  if (!active(spec.auth)) return {}
  const auth = record(spec.auth)
  return {
    ...chain(auth.provider === 'keycloak'
      ? [{ name: w('client') }, { name: w('keycloak'), detail: str(record(auth.keycloak).realm) },
        { name: w('generatedApi'), detail: w('validateToken') }]
      : [{ name: w('client') }, { name: w('verifyCredentials') }, { name: w('tokenStore'), detail: str(auth.token_store) },
        { name: w('issueSession') }]),
    tables: [table([w('tokenAlgorithm'), w('accessTokenMinutes'), w('refreshTokenDays')],
      [[cell(auth.jwt_algorithm), cell(auth.access_token_ttl_minutes), cell(auth.refresh_token_ttl_days)]])],
  }
}

const identity: Builder = (spec, w) => {
  if (!active(spec.auth)) return {}
  const auth = record(spec.auth)
  const keycloak = record(auth.keycloak)
  const suite = record(auth.suite)
  const providers = auth.provider === 'keycloak' ? objects(keycloak.identity_providers) : []
  const nodes = [{ name: w('generatedApi') }, { name: w(auth.provider === 'keycloak' ? 'keycloak' : 'builtInAuth'),
    detail: auth.provider === 'keycloak' ? str(keycloak.realm) : str(auth.token_store) },
  ...providers.map(provider => ({ name: str(provider.display_name) || str(provider.alias), detail: str(provider.type) }))]
  const edges: [number, number][] = [[0, 1], ...providers.map((_, i): [number, number] => [1, i + 2])]
  if (suite.suite_id) {
    edges.push([0, nodes.length])
    nodes.push({ name: str(suite.suite_id), detail: str(suite.hub_issuer) })
  }
  return {
    ...graph(nodes, edges),
    tables: [columns(w, ['identityProvider', 'type', 'issuer'], providers, ['alias', 'type', 'issuer']),
      ...(suite.suite_id ? [table([w('suite'), w('joinState'), w('migrationState'), w('dualUntil')],
        [[cell(suite.suite_id), cell(suite.join_state), cell(record(suite.migration).state), cell(record(suite.migration).dual_until)]])] : [])],
  }
}

const tenancy: Builder = (spec, w) => {
  if (!active(spec.auth)) return {}
  const enabled = record(spec.auth).multi_tenant === true
  return {
    ...chain([{ name: w(enabled ? 'multiTenant' : 'singleTenant') }, { name: w('auth') },
      ...(enabled ? [{ name: w('tenantFilter') }] : []), { name: w('database') }]),
    tables: [columns(w, ['entity', 'operation', 'roles'], objects(record(spec.auth).permissions).filter(rule => rule.row_rule === 'tenant'),
      ['entity', 'operation', 'roles'], w('tenantRules'))],
  }
}

const controlTables = (spec: Spec, w: Translate) => {
  const compliance = record(spec.compliance)
  const regulated = record(spec.regulated)
  const emergency = record(compliance.break_glass)
  return [
    columns(w, ['entity', 'field', 'treatment', 'searchable'], active(spec.regulated) ? objects(regulated.fields) : [],
      ['entity', 'field', 'mode', 'searchable'], w('protectedFields')),
    columns(w, ['entity', 'field', 'treatment'], active(spec.compliance) ? objects(compliance.export_fields) : [],
      ['entity', 'field', 'treatment'], w('exports')),
    ...(active(spec.compliance) && emergency.enabled ? [table([w('roles'), w('grantMinutes')],
      [[cell(emergency.roles), cell(emergency.max_minutes)]], w('breakGlass'))] : []),
  ]
}

const controls: Builder = (spec, w) => {
  const regulated = record(spec.regulated)
  const compliance = record(spec.compliance)
  const nodes = [
    ...(active(spec.regulated) ? objects(regulated.fields).map(field => ({
      name: str(field.entity) + '.' + str(field.field), detail: str(field.mode),
    })) : []),
    ...(active(spec.compliance) && objects(compliance.retention).length ? [{ name: w('retention') }] : []),
    ...(active(spec.compliance) && record(compliance.break_glass).enabled ? [{ name: w('breakGlass') }] : []),
    ...(active(spec.compliance) && words(compliance.consent_purposes).length ? [{ name: w('consent'), detail: words(compliance.consent_purposes).join(', ') }] : []),
  ]
  return { ...(nodes.length ? hub({ name: w('generatedApi') }, nodes) : {}), tables: controlTables(spec, w) }
}

const boundaries: Builder = (spec, w) => ({
  ...chain([
    { name: w('client'), detail: w('externalBoundary') },
    ...(active(spec.api_edge) ? [{ name: w('api_edge'), detail: w('requestBuckets') }] : []),
    { name: w('generatedApi'), detail: active(spec.auth) ? w('auth') : undefined },
    { name: w('database'), detail: w('dataBoundary') },
  ]),
  tables: controlTables(spec, w),
})

const retention: Builder = (spec, w) => {
  const configured = active(spec.compliance) ? objects(record(spec.compliance).retention) : []
  const history = objects(spec.history)
  const events = active(spec.events)
  if (!configured.length && !history.length && !events) return {}
  return {
    ...chain([{ name: w('recordCreated') }, { name: w('retention') }, { name: w('applyRetention') }]),
    tables: [
      columns(w, ['entity', 'field', 'retentionDays', 'action'], configured, ['entity', 'date_field', 'days', 'action']),
      columns(w, ['entity', 'fields', 'retentionDays', 'roles'], history, ['entity', 'fields', 'retention_days', 'view_roles'], w('history')),
      ...(events ? [table([w('data'), w('retentionDays')], [[w('outbox'), cell(record(spec.events).retention_days)]])] : []),
      ...controlTables(spec, w).filter(item => item.heading === w('exports')),
    ],
  }
}

const journey: Builder = (spec, w, selection) => {
  const roles = active(spec.auth) ? objects(record(spec.auth).roles) : []
  const { picker, selected } = chooseRows(w('role'), roles, selection)
  const rules = objects(record(spec.auth).permissions).filter(rule => words(rule.roles).includes(picker.value))
  const transitions = objects(spec.state_machines).flatMap(machine => objects(machine.transitions)
    .filter(item => words(item.roles).includes(picker.value)).map(item => [str(machine.entity), str(item.name)]))
  return {
    note: w('journeyOutline'), picker,
    ...(selected && (rules.length || transitions.length)
      ? hub({ name: str(selected.label) || picker.value }, [...new Set([...rules.map(rule => str(rule.entity)),
        ...transitions.map(([entity]) => entity)])].map(name => ({ name }))) : {}),
    tables: [
      columns(w, ['entity', 'operation'], rules, ['entity', 'operation']),
      table([w('entity'), w('transition')], transitions),
    ],
  }
}

const metrics: Builder = (spec, w, selection) => {
  const { picker, selected } = chooseRows(w('metric'), objects(record(spec.metrics_layer).definitions), selection, 'key')
  if (!selected) return {}
  return {
    ...chain([{ name: str(selected.entity), detail: str(selected.field) },
      { name: str(selected.label) || str(selected.key), detail: str(selected.agg) }]), picker,
    tables: [table([w('aggregation'), w('groupBy'), w('unit')], [[cell(selected.agg), cell(selected.group_by), cell(selected.unit)]]),
      columns(w, ['field', 'operation', 'value'], objects(selected.filter), ['field', 'op', 'value'])],
  }
}

const geo: Builder = (spec, w) => {
  const config = record(record(spec.packs).operations)
  const blocks = ['geo', 'location', 'matching'].filter(block => Boolean(config[block]))
  return {
    ...(blocks.length ? hub({ name: w('generatedApi') }, blocks.map(name => ({ name: w(name) }))) : {}),
    note: w('liveMap'),
    tables: [table([w('feature'), w('readRoles'), w('writeRoles')], blocks.map(block =>
      [w(block), cell(record(config[block]).read_roles), cell(record(config[block]).write_roles)]))],
  }
}

export const securityViews = {
  D15: login, D16: identity, D17: tenancy, D26: journey, D38: controls, D39: boundaries, D40: retention, D44: metrics, D45: geo,
}
