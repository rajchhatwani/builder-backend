import { queryOptions } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import { BASE_URL, authHeader, notifySessionLost, refreshOutcome } from '../../../../api/session'
import type { CustomFieldDef, PromoteCheck, PromoteResult, ValidationIssue } from '../../../../api/types'

const root = (id: string) => ['projects', id, 'behavior-authoring'] as const
const options = { retry: false, retryOnMount: false, staleTime: 15_000 } as const

export const behaviorKeys = {
  root,
  section: (id: string, name: string) => [...root(id), name] as const,
  fields: (id: string, entity: string) => [...root(id), 'customfields', entity] as const,
}

export type Versioned<T> = { value: T; version: number; updated_at?: string | null; row_version?: number }
type Read<T> = Omit<Versioned<T>, 'value'>
export function versioned<T>(meta: Read<T>, value: T): Versioned<T> {
  return { value, version: meta.version, updated_at: meta.updated_at, row_version: meta.row_version }
}

export function section<T>(name: string, load: (id: string) => Promise<Versioned<T>>,
  save: (id: string, value: T, version: number) => Promise<Versioned<T>>) {
  return { name, save, query: (id: string) => queryOptions({
    ...options, queryKey: behaviorKeys.section(id, name), queryFn: () => load(id),
  }) }
}

export type Events = { enabled: boolean; adapter: string; retention_days: number }
export type Effects = { enabled: boolean; trusted_authors_only: boolean; webhook_hosts: string[] }

function decodeBlock<T>(body: Record<string, unknown>, key: string): Versioned<T | null> {
  if (typeof body.version !== 'number' || !Number.isInteger(body.version) || body.version < 0) {
    throw new Error('Expected a behavior section version')
  }
  return {
    value: (body[key] ?? null) as T | null,
    version: body.version,
    updated_at: typeof body.updated_at === 'string' ? body.updated_at : null,
    row_version: typeof body.row_version === 'number' ? body.row_version : undefined,
  }
}

function block<T>(name: string, key: string) {
  return section(name,
    async id => decodeBlock<T>(await api.getBlock(id, name), key),
    async (id, value: T | null, expected_version) => decodeBlock<T>(
      await api.putBlock(id, name, { [key]: value, expected_version }), key),
  )
}

export const eventsSection = block<Events>('events', 'events')
export const effectsSection = block<Effects>('hook-effects', 'hook_effects')
export const hooksSection = section('hooks', async id => {
  const result = await api.getHooks(id)
  return versioned(result, result.hooks)
}, async (id, value, version) => {
  const result = await api.putHooks(id, value, version)
  return versioned(result, result.hooks)
})
export const seedSection = section('seed', async id => {
  const result = await api.getSeed(id)
  return versioned(result, result.seed)
}, async (id, value, version) => {
  const result = await api.putSeed(id, value, version)
  return versioned(result, result.seed)
})
export const settingsSection = section('settings', async id => {
  const result = await api.getSettings(id)
  return versioned(result, result.settings)
}, async (id, value, version) => {
  const result = await api.putSettings(id, value, version)
  return versioned(result, result.settings)
})
export const sequenceSection = section('sequences', async id => {
  const result = await api.getSequences(id)
  return versioned(result, result.sequences)
}, async (id, value, version) => {
  const result = await api.putSequences(id, value, version)
  return versioned(result, result.sequences)
})
export const listSection = section('lists', async id => {
  const result = await api.getLists(id)
  return versioned(result, result.lists)
}, async (id, value, version) => {
  const result = await api.putLists(id, value, version)
  return versioned(result, result.lists)
})

export const issuesOptions = (id: string) => queryOptions({
  ...options, queryKey: behaviorKeys.section(id, 'issues'), queryFn: () => api.getBehaviorIssues(id),
})
export const specOptions = (id: string) => queryOptions({
  ...options, queryKey: behaviorKeys.section(id, 'spec'), queryFn: () => api.getSpecJson(id),
})
export const rolesOptions = (id: string) => queryOptions({
  ...options, queryKey: behaviorKeys.section(id, 'roles'), queryFn: () => api.getBehaviorRoles(id),
})
export const fieldsOptions = (id: string, entity: string) => queryOptions({
  ...options, queryKey: behaviorKeys.fields(id, entity), queryFn: () => api.listCustomFields(id, entity), enabled: Boolean(entity),
})

async function allPages<T>(load: (offset: number) => Promise<{ items: T[]; total: number }>) {
  const items: T[] = []
  while (true) {
    const page = await load(items.length)
    items.push(...page.items)
    if (items.length >= page.total || !page.items.length) return items
  }
}

export const catalogOptions = (id: string) => queryOptions({
  ...options, queryKey: behaviorKeys.section(id, 'catalog'), queryFn: async () => {
    const [entities, relations, machines] = await Promise.all([
      allPages(offset => api.listEntities(id, 200, offset)),
      allPages(offset => api.listRelations(id, 200, offset)),
      api.getStateMachines(id),
    ])
    const columns = await Promise.all(entities.map(entity => allPages(offset => api.listFields(entity.id, 200, offset))))
    return {
      entities: entities.map((entity, index) => ({
        ...entity,
        columns: columns[index],
        machine: machines.state_machines.find(machine => machine.entity === entity.name),
        references: relations.filter(relation => relation.to_entity_id === entity.id &&
          (relation.kind === 'one_to_one' || relation.kind === 'one_to_many')).map(relation => ({
          column: relation.to_name + '_id', target: entities.find(target => target.id === relation.from_entity_id)?.name ?? '',
          required: relation.required, unique: relation.kind === 'one_to_one',
        })),
      })),
    }
  },
})

export type Catalog = Awaited<ReturnType<NonNullable<ReturnType<typeof catalogOptions>['queryFn']>>>
export type CatalogEntity = Catalog['entities'][number]

export function errorStatus(error: unknown) {
  return error instanceof ApiError ? error.status : undefined
}

export function saveErrorKey(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 413) return 'behavior.saveTooLarge'
    if (error.code === 'secret_in_spec') return 'behavior.saveSecret'
  }
  return 'behavior.saveError'
}

export function errorIssues(error: unknown): ValidationIssue[] {
  return error instanceof ApiError ? error.details.flatMap(detail => {
    if (!detail || typeof detail !== 'object') return []
    const value = detail as Record<string, unknown>
    const path = typeof value.path === 'string' ? value.path
      : Array.isArray(value.loc) ? value.loc.filter(part => part !== 'body').join('.') : undefined
    const message = value.message ?? value.msg
    if (!path || typeof message !== 'string') return []
    return [{ path, message, code: String(value.code ?? value.type ?? '') }]
  }) : []
}

export type MigrationStep = { kind: string; safety: string; reason: string; sql_hint?: string | null }
export type Promotion = PromoteResult & { migration_steps?: MigrationStep[] }

function customFieldPath(id: string, entity: string, name: string) {
  return '/projects/' + encodeURIComponent(id) + '/entities/' + encodeURIComponent(entity) +
    '/custom-fields/' + encodeURIComponent(name)
}

// These two request shapes are missing from the read-only legacy client. Share its session primitives.
async function customFieldRequest<T>(path: string, method: 'PATCH' | 'POST', body: unknown): Promise<T> {
  const send = () => fetch(BASE_URL + path, {
    method, credentials: 'include', headers: { 'Content-Type': 'application/json', ...authHeader('app') },
    body: JSON.stringify(body),
  })
  let response = await send()
  if (response.status === 401) {
    const outcome = await refreshOutcome('app')
    if (outcome === 'ok') response = await send()
    if (outcome === 'lost') notifySessionLost('app')
  }
  const payload = await response.json().catch(() => null)
  if (!response.ok || !payload) throw new ApiError(response.status, {
    code: typeof payload?.code === 'string' ? payload.code : 'bad_response',
    message: typeof payload?.message === 'string' ? payload.message : '',
    details: Array.isArray(payload?.details) ? payload.details : [],
  })
  return payload as T
}

export function updateCustomField(id: string, entity: string, name: string, value: CustomFieldDef) {
  return customFieldRequest<CustomFieldDef>(customFieldPath(id, entity, name), 'PATCH', value)
}

export function checkCustomFieldSamples(id: string, entity: string, name: string, samples: unknown[]) {
  return customFieldRequest<PromoteCheck>(customFieldPath(id, entity, name) + '/promote-check', 'POST', { samples })
}

export const customFieldsApi = {
  define: api.defineCustomField,
  remove: api.removeCustomField,
  check: api.checkPromoteCustomField,
  promote: async (...args: Parameters<typeof api.promoteCustomField>): Promise<Promotion> => api.promoteCustomField(...args),
}

export function prefetchBehavior(client: QueryClient, id: string, name: string) {
  if (name !== 'customfields') void client.prefetchQuery(issuesOptions(id))
  switch (name) {
    case 'hooks':
      void client.prefetchQuery(hooksSection.query(id))
      void client.prefetchQuery(catalogOptions(id))
      void client.prefetchQuery(effectsSection.query(id))
      break
    case 'hookeffects':
      void client.prefetchQuery(effectsSection.query(id))
      void client.prefetchQuery(hooksSection.query(id))
      void client.prefetchQuery(specOptions(id))
      break
    case 'events':
      void client.prefetchQuery(eventsSection.query(id))
      void client.prefetchQuery(specOptions(id))
      break
    case 'settings':
      void client.prefetchQuery(settingsSection.query(id))
      void client.prefetchQuery(sequenceSection.query(id))
      void client.prefetchQuery(listSection.query(id))
      void client.prefetchQuery(rolesOptions(id))
      break
    case 'seed':
      void client.prefetchQuery(seedSection.query(id))
      void client.prefetchQuery(sequenceSection.query(id))
      void client.prefetchQuery(catalogOptions(id))
      void client.prefetchQuery(specOptions(id))
      break
    case 'customfields':
      void client.prefetchQuery(specOptions(id))
      break
  }
}
