import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import { authHeader, BASE_URL, notifySessionLost, refreshOutcome } from '../../../../api/session'
import type {
  AccessDiffRequest, ApiErrorBody, Entity, EntityOptions, Field, FieldInput, HistoryBody, MigrationPlanRequest,
  OnDelete, Relation, RelationKind, StateMachineBody,
} from '../../../../api/types'

export type Spec = Record<string, unknown>
export type CatalogField = Pick<Field, 'name' | 'type' | 'required' | 'enum_values' | 'default'>
export type CatalogEntity = { name: string; fields: CatalogField[] }

export const record = (value: unknown): Spec =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Spec : {}

export function catalog(spec: Spec): CatalogEntity[] {
  return Array.isArray(spec.entities) ? spec.entities : []
}

const projectKey = (id: string) => ['projects', id] as const
export const buildKeys = {
  project: projectKey,
  build: (id: string) => [...projectKey(id), 'build'] as const,
}
const options = { retry: false, retryOnMount: false, staleTime: 15_000 }
const query = <T>(id: string, key: readonly unknown[], queryFn: () => Promise<T>) =>
  ({ ...options, queryKey: [...buildKeys.build(id), ...key] as const, queryFn })

export const buildQueries = {
  entities: (id: string) => query(id, ['entities'], () => api.listEntities(id, 200)),
  fields: (id: string, entity: string) => query(id, ['fields', entity], () => api.listFields(entity, 200)),
  relations: (id: string) => query(id, ['relations'], async () => {
    const first = await api.listRelations(id, 200)
    if (first.total <= first.items.length) return first.items
    const next = await api.listRelations(id, 200, first.items.length)
    return [...first.items, ...next.items]
  }),
  machines: (id: string) => query(id, ['machines'], () => api.getStateMachines(id)),
  history: (id: string) => query(id, ['history'], () => api.getHistory(id)),
  issues: (id: string) => query(id, ['issues'], () => api.getBehaviorIssues(id)),
  roles: (id: string) => query(id, ['roles'], () => api.getBehaviorRoles(id)),
  ops: (id: string, page: number) => query(id, ['ops', page], () => api.listSpecOps(id, versionPageSize, (page - 1) * versionPageSize)),
  at: (id: string, seq?: number) => ({
    ...query(id, ['at', seq], () => api.getSpecAt(id, seq!)), enabled: seq !== undefined,
  }),
  spec: (id: string) => query(id, ['spec'], () => api.getSpecJson(id)),
  status: (id: string) => ({ ...options, queryKey: [...projectKey(id), 'status'] as const, queryFn: () => api.getProjectStatus(id) }),
  access: (id: string) => query(id, ['access'], async () => {
    const revision = await accessRevision(id)
    const [matrix, spec] = await Promise.all([api.getAccessMatrix(id), api.getSpecJson(id)])
    return { matrix, spec, ...revision }
  }),
}

export const versionPageSize = 20

async function accessRevision(id: string) {
  const [project, ops] = await Promise.all([api.getProject(id), api.listSpecOps(id, 1)])
  return { version: project.version, seq: ops.items[0]?.seq ?? 0 }
}

export const buildError = (error: unknown) => error instanceof ApiError ? error : undefined
export function serverIssues(error: unknown) {
  return (buildError(error)?.details ?? []).flatMap(detail => {
    const { path, code, message } = record(detail)
    return typeof path === 'string' && typeof message === 'string'
      ? [{ path, code: String(code ?? ''), message }] : []
  })
}

export function useBuildWrite<Input, Output>(id: string, write: (id: string, input: Input) => Promise<Output>) {
  const client = useQueryClient()
  return useMutation({
    scope: { id: 'build:' + id },
    mutationFn: (input: Input) => write(id, input),
    onSuccess: () => client.invalidateQueries({ queryKey: buildKeys.project(id),
      predicate: query => query.queryKey.at(-1) !== 'presence' }),
  })
}

type RelationInput = {
  kind: RelationKind; from_entity_id: string; to_entity_id: string; from_name: string; to_name: string
  on_delete: OnDelete; required: boolean
}
type EntityInput = { name: string; table_name?: string; plural_path?: string; options?: EntityOptions }
type ModelCommand =
  | { kind: 'addEntity'; data: EntityInput }
  | { kind: 'entity'; entity: Entity; data: EntityInput }
  | { kind: 'field'; entity: Entity; field?: Field; data: FieldInput & { position?: number } }
  | { kind: 'relation'; relation?: Relation; from: Entity; to: Entity; data: RelationInput }
  | { kind: 'removeEntity'; entity: Entity }
  | { kind: 'removeField'; entity: Entity; field: Field }
  | { kind: 'removeRelation'; relation: Relation }

export type ModelWrite = ModelCommand & { confirm?: boolean }

export async function writeModel(id: string, command: ModelWrite): Promise<unknown> {
  switch (command.kind) {
    case 'addEntity': return api.createEntity(id, command.data)
    case 'entity': return command.confirm ? api.applySpecOp(id, 'update_entity', { name: command.entity.name, changes: command.data }, true)
      : api.updateEntity(command.entity.id, command.data)
    case 'field': return command.field ? api.updateField(command.field.id, command.data) : api.createField(command.entity.id, command.data)
    case 'relation': {
      if (!command.relation) return api.createRelation(id, command.data)
      const { from_name, to_name, on_delete, required } = command.data
      return api.applySpecOp(id, 'update_relation', {
        from_entity: command.from.name, to_entity: command.to.name, from_name: command.relation.from_name,
        changes: { from_name, to_name, on_delete, required },
      }, command.confirm)
    }
    case 'removeEntity': return command.confirm ? api.applySpecOp(id, 'remove_entity', { name: command.entity.name }, true)
      : api.deleteEntity(command.entity.id)
    case 'removeField': return command.confirm ? api.applySpecOp(id, 'remove_field', { entity: command.entity.name, name: command.field.name }, true)
      : api.deleteField(command.field.id)
    case 'removeRelation': return api.deleteRelation(command.relation.id)
  }
}

type Versioned<T> = { rows: T[]; version: number }

export const saveHistory = (id: string, input: Versioned<HistoryBody>) => api.putHistory(id, input.rows, input.version)

export const saveMachines = (id: string, input: Versioned<StateMachineBody>) =>
  api.putBlock(id, 'state-machines', { state_machines: input.rows, expected_version: input.version })

export type TimelineAction = ({ kind: 'undo' | 'redo' } | { kind: 'restore'; seq: number }) & { confirm?: boolean; head?: number }
export async function writeTimeline(id: string, action: TimelineAction) {
  if (action.head !== undefined) {
    const latest = await api.listSpecOps(id, 1)
    if ((latest.items[0]?.seq ?? 0) !== action.head) {
      throw new ApiError(409, { code: 'spec_conflict', message: '', details: [] })
    }
  }
  if (action.kind === 'restore') return api.restoreSpec(id, action.seq, action.confirm)
  if (action.kind === 'undo') return api.undoSpec(id, action.confirm)
  return api.redoSpec(id, action.confirm)
}

export const reviewAccess = (id: string, edits: AccessDiffRequest) => api.diffAccess(id, edits)
export const checkGuard = (id: string, input: { entity: string; expression: string }) => api.checkExpression(id, input.entity, input.expression)
export const planMigration = (id: string, input: { body: MigrationPlanRequest; accept: boolean }) => api.migrationPlan(id, input.body, input.accept)
export const generationOptions = (id: string) => query(id, ['generations'], () => api.listGenerations(id, 200))

export async function replaceAccess(id: string, input: { spec: Spec; version: number; seq: number; confirm: boolean }) {
  const revision = await accessRevision(id)
  if (revision.version !== input.version || revision.seq !== input.seq) {
    throw new ApiError(409, { code: 'version_conflict', message: '', details: [] })
  }
  const params = new URLSearchParams({ expected_version: String(input.version) })
  if (input.confirm) params.set('confirm_weakening', 'true')
  const send = () => fetch(`${BASE_URL}/projects/${encodeURIComponent(id)}/spec?${params}`, {
    method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json', ...authHeader('app') },
    body: JSON.stringify(input.spec),
  })
  let response = await send()
  if (response.status === 401) {
    const outcome = await refreshOutcome('app')
    if (outcome === 'ok') response = await send()
    if (outcome === 'lost') notifySessionLost('app')
  }
  const body = await response.json().catch(() => null) as Spec | Partial<ApiErrorBody> | null
  if (!response.ok || !body) {
    const error = record(body)
    throw new ApiError(response.status, {
      code: typeof error.code === 'string' ? error.code : 'bad_response',
      message: typeof error.message === 'string' ? error.message : '',
      details: Array.isArray(error.details) ? error.details : [],
    })
  }
  return body
}

export function prefetchBuild(section: string, id: string, page = 1) {
  const q = buildQueries
  switch (section) {
    case 'model': return [q.entities(id), q.relations(id), q.spec(id), q.status(id)]
    case 'machines': return [q.machines(id), q.spec(id), q.issues(id), q.roles(id)]
    case 'history': return [q.history(id), q.machines(id), q.spec(id), q.issues(id), q.roles(id)]
    case 'timeline': return [q.ops(id, page)]
    case 'specdiff': return [q.spec(id), q.ops(id, page)]
    case 'permissions': return [q.access(id)]
    default: return []
  }
}
