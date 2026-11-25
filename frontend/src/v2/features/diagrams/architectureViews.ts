import type { Builder, Diagram, Node, Spec, Translate } from './model'
import { active, capabilities, cell, chain, choose, chooseRows, columns, graph, hub, named, objects, record, str, table, words } from './model'
import { lifecycle } from './dataViews'

function outsideSystems(spec: Spec, w: Translate): Node[] {
  const auth = record(spec.auth)
  const apps = objects(record(spec.api_platform).apps)
  const adapters = objects(record(spec.providers).adapters)
  const gateway = record(record(record(spec.packs).ai).gateway)
  return [
    ...(active(spec.providers) ? named(adapters, 'kind') : []),
    ...(active(spec.api_platform) ? named(apps, 'kind') : []),
    ...named(objects(gateway.providers), 'kind'),
    ...(active(spec.auth) && auth.provider === 'keycloak' ? named(objects(record(auth.keycloak).identity_providers).map(provider =>
      ({ name: provider.alias, kind: provider.type })), 'kind') : []),
    ...(active(spec.auth) && auth.smtp ? [{ name: w('smtp') }] : []),
    ...(active(spec.auth) && auth.sms_provider ? [{ name: str(auth.sms_provider), detail: w('sms') }] : []),
    ...(active(spec.payments) ? [{ name: str(record(spec.payments).provider), detail: w('payments') }] : []),
    ...(active(spec.storage) ? [{ name: str(record(spec.storage).backend), detail: w('storage') }] : []),
    ...(active(spec.webhooks) ? named(objects(record(spec.webhooks).inbound)) : []),
  ].filter(node => node.name)
}

export function localRuntime(spec: Spec, w: Translate): Diagram {
  const rows: Node[] = [{ name: w('generatedApi') }, { name: w('postgres'), detail: w('database') }]
  const edges: [number, number, string?][] = [[0, 1, w('queriesWrites')]]
  const add = (node: Node, from = 0) => {
    const i = rows.push(node) - 1
    edges.push([from, i])
    return i
  }
  const worker = (name: string, detail?: string) => {
    const i = rows.push({ name, detail }) - 1
    edges.push([i, 1, w('queriesWrites')])
  }
  if (active(spec.payments)) {
    worker(w('paymentsWorker'))
    if (record(record(spec.payments).scale).pgbouncer === true) {
      const pool = add({ name: w('pgbouncer') })
      edges[0] = [pool, 1, w('queriesWrites')]
    }
  }
  if (active(spec.jobs)) {
    for (const group of objects(record(spec.jobs).worker_groups)) {
      if (group.placement === 'same_server') worker(str(group.name), w('jobWorker'))
    }
  }
  if (active(spec.workflows)) worker(w('workflowWorker'))
  if (active(spec.storage)) {
    add({ name: w('clamav') })
    add({ name: w('objectStore'), detail: str(record(spec.storage).backend) })
  }
  const auth = record(spec.auth)
  if (active(auth) && Object.keys(auth).length) {
    if (auth.provider === 'builtin' && auth.token_store === 'redis') add({ name: w('redis'), detail: w('tokenStore') })
    if (auth.provider === 'keycloak') {
      const keycloak = add({ name: w('keycloak'), detail: w('identityProvider') })
      if (record(auth.keycloak).mode === 'own') add({ name: w('keycloakDb') }, keycloak)
    }
  }
  const observability = record(spec.observability)
  if (active(spec.observability) && observability.local_stack) {
    const collector = add({ name: w('collector') })
    add({ name: w('jaeger'), detail: w('traces') }, collector)
    if (observability.metrics) add({ name: w('prometheus'), detail: w('metrics') }, collector)
  }
  return { ...graph(rows, edges), note: w('inferred') }
}

const context: Builder = (spec, w) => {
  const project = record(spec.project)
  const roles = active(spec.auth) ? objects(record(spec.auth).roles) : []
  const external = outsideSystems(spec, w)
  const actors = roles.map(role => ({ name: str(role.label) || str(role.name), detail: w('role') }))
  return graph([{ name: str(project.name) || w('generatedApi'), detail: str(project.description) }, ...actors, ...external], [
    ...actors.map((_, i): [number, number] => [i + 1, 0]),
    ...external.map((_, i): [number, number] => [0, actors.length + i + 1]),
  ])
}

const dataFlow: Builder = (spec, w, selection) => {
  const entities = objects(spec.entities)
  const options = [{ value: 'context', label: w('level0') }, { value: 'processes', label: w('level1') },
    ...entities.map(entity => ({ value: 'entity:' + str(entity.name), label: w('level2', { value: str(entity.name) }) }))]
  const picker = choose(w('detailLevel'), options, selection)
  const entity = entities.find(row => 'entity:' + str(row.name) === picker.value)
  if (entity) return { ...lifecycle(spec, entity, w), picker }
  if (picker.value === 'context') return {
    ...context(spec, w), picker,
    tables: [columns(w, ['entity', 'storage'], entities, ['name', 'table_name'])],
  }
  const base = localRuntime(spec, w)
  const topology = base.nodes ?? []
  const nodes = [...topology]
  const edges = [...(base.edges ?? [])]
  const add = (name: string, from: number, label: string) => {
    const to = nodes.push({ name }) - 1
    edges.push({ from, to, label })
    return to
  }
  if (active(spec.events)) {
    const outbox = add(w('outbox'), 1, w('transactionalEvents'))
    const relay = add(w('relay'), outbox, w('relayAfterCommit'))
    if (active(spec.notifications)) add(w('notifications'), relay, w('configuredEvents'))
    if (active(spec.webhooks)) add(w('webhooks'), relay, w('configuredEvents'))
  }
  if (active(spec.jobs)) add(w('queue'), 1, w('jobs'))
  return { ...base, nodes, edges, picker }
}

const cloudResources: Record<string, string[]> = {
  aws: ['loadBalancer', 'ecs', 'rds', 'secretsManager'],
  azure: ['azureApps', 'azurePostgres', 'azureVault'],
  gcp: ['cloudRun', 'cloudSql', 'secretManager'],
}
const deployment: Builder = (spec, w, selection) => {
  if (!active(spec.deployment)) return {}
  const block = record(spec.deployment)
  const { picker, selected } = chooseRows(w('environment'), objects(block.environments), selection)
  if (!selected) return {}
  const cloud = str(block.cloud)
  const resources = Object.hasOwn(cloudResources, cloud) ? cloudResources[cloud] : []
  return {
    ...hub({ name: str(selected.name), detail: [cloud, str(block.region)].filter(Boolean).join(' · ') },
      resources.map(name => ({ name: w(name) }))), picker,
    tables: [table([w('profile'), w('minInstances'), w('maxInstances'), w('databaseStorage'), w('highAvailability'), w('deletionProtection')],
      [[cell(selected.profile), cell(selected.min_instances), cell(selected.max_instances), cell(selected.db_storage_gb),
        cell(selected.db_high_availability), cell(selected.deletion_protection)]])],
  }
}

const registries = { aws: 'ecr', azure: 'acr', gcp: 'artifactRegistry' } as const
const ci: Builder = (spec, w, selection) => {
  const block = record(spec.deployment)
  const cloud = str(block.cloud)
  const picker = choose(w('workflowTemplate'), ['aws', 'azure', 'gcp'].map(value => ({ value, label: w(value) })), selection || cloud)
  const registry = registries[picker.value as keyof typeof registries]
  return {
    ...chain(['checks', 'cloudSignIn', 'publishImage', 'terraform', 'migrate', 'rollout'].map(key => ({
      name: w(key), detail: key === 'publishImage' ? w(registry) : undefined,
    }))), picker,
    tables: [
      table([w('ciJob'), w('detail')], ['ciTest', 'ciImage', 'ciTerraform'].map(key => [w(key), w(key + 'Detail')])),
      ...(cloud === picker.value ? [table([w('repository'), w('environments')],
        [[cell(block.github_repo), objects(block.environments).map(row => str(row.name)).join(', ')]])] : []),
    ],
  }
}

const observe: Builder = (spec, w) => {
  if (!active(spec.observability)) return {}
  const config = record(spec.observability)
  const outputs = config.local_stack ? [{ name: w('jaeger'), detail: w('traces') },
    ...(config.metrics ? [{ name: w('prometheus'), detail: w('metrics') }] : [])] : []
  return {
    ...graph([{ name: str(config.service_name) || w('generatedApi'), detail: w('openTelemetry') },
      { name: config.local_stack ? w('collector') : w('externalCollector') }, ...outputs],
      [[0, 1, w(config.metrics ? 'tracesAndMetrics' : 'traces')], ...outputs.map((_, i): [number, number] => [1, i + 2])]),
    tables: [table([w('sampleRate'), w('dbSpans'), w('excludedPaths'), w('redaction')],
      [[cell(config.sample_ratio), cell(config.db_spans), cell(config.exclude_paths), cell(config.redact_keys)]])],
  }
}

const edgeChecks: Builder = (spec, w) => {
  if (!active(spec.api_edge)) return {}
  const edge = record(spec.api_edge)
  const checks = [
    ...(edge.idempotency ? [{ name: w('idempotency'), detail: w('replayWrites') }] : []),
    ...(edge.rate_limits ? [{ name: w('rateLimits'), detail: w('requestBuckets') }] : []),
    ...(objects(edge.quotas).length ? [{ name: w('quotas'), detail: w('quotaMeters') }] : []),
    ...(edge.versioning ? [{ name: w('versioning'), detail: str(record(edge.versioning).default) }] : []),
  ]
  return { nodes: checks, tables: [columns(w, ['version', 'note'], objects(record(edge.versioning).versions), ['date', 'note']),
    columns(w, ['quota', 'period', 'limit'], objects(edge.quotas), ['meter', 'period', 'limit'])], note: w('unspecifiedOrder') }
}

export const architectureViews = {
  D01: context, D02: localRuntime, D04: (spec: Spec, w: Translate) => ({ nodes: capabilities(spec, w) }),
  D18: dataFlow, D32: deployment,
  D33: (spec: Spec, w: Translate) => {
    const runtime = localRuntime(spec, w)
    const telemetry = record(spec.observability)
    const keycloak = record(record(spec.auth).keycloak)
    return { ...runtime, tables: [table([w('service'), w('defaultAddress')], [
      [w('generatedApi'), w('apiPort')], [w('postgres'), w('postgresPort')],
      ...(active(spec.auth) && record(spec.auth).provider === 'keycloak' && keycloak.mode === 'own' ? [[w('keycloak'), w('keycloakPort')]] : []),
      ...(active(spec.storage) && record(spec.storage).download_mode === 'presigned' ? [[w('objectStore'), w('objectStorePort')]] : []),
      ...(active(spec.observability) && telemetry.local_stack ? [[w('jaeger'), w('jaegerPort')],
        ...(telemetry.metrics ? [[w('prometheus'), w('prometheusPort')]] : [])] : []),
    ])] }
  },
  D34: ci, D35: observe, D37: edgeChecks,
  D42: (spec: Spec, w: Translate) => ({
    ...chain(['validate', 'hashSpec', 'renderModules', 'previewFiles', 'reviewMigration', 'download'].map(key => ({ name: w(key) }))),
    tables: [table([w('feature'), w('detail')], capabilities(spec, w).map(node => [node.name, node.detail]), w('enabledFeatures'))],
  }),
}

export function integrations(spec: Spec, w: Translate): Diagram {
  const adapters = objects(record(spec.providers).adapters)
  const rows = outsideSystems(spec, w)
  const notifications = objects(record(spec.notifications).types)
  return {
    ...hub({ name: w('generatedApi') }, rows),
    tables: [
      columns(w, ['kind', 'adapter'], active(spec.providers) ? adapters : [], ['kind', 'name']),
      columns(w, ['notification', 'channels', 'event'], active(spec.notifications) ? notifications : [], ['name', 'channels', 'on_event']),
      table([w('hook'), w('effects')], objects(spec.hooks).filter(hook => words(hook.effects).length)
        .map(hook => [str(hook.name), cell(hook.effects)])),
    ],
  }
}
