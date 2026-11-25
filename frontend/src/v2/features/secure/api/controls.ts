import { queryOptions, type QueryClient } from '@tanstack/react-query'
import { ApiError, api, saveBlob } from '../../../../api/client'
import type { AuthorizationSettings, AuthorizationWrite, SpecForPolicies } from '../../../../api/types'
import { secureKeys } from './security'

export type { AccessDiff, AccessDiffRequest, AuthOperation, AuthorizationModel, AuthorizationSettings, CoverageRow,
  DependencyRequest, Entity, FieldAccessRule, PermissionEntry, Policy, PolicyCondition, ProjectPermission, ProjectRole,
  RecommendAnswers, Recommendation, RowRule, SimulateRequest, SpecForPolicies } from '../../../../api/types'

const options = { retry: false, retryOnMount: false, staleTime: 30_000 }
const read = <T>(id: string, section: string, queryFn: () => Promise<T>, suffix = '') =>
  queryOptions({ ...options, queryKey: [...secureKeys.section(id, section), suffix], queryFn })

export const dependencyOptions = (id: string) => read(id, 'dependencies', async () => {
  const [policy, requests, blocks, hooks, locks] = await Promise.all([
    api.dependencyPolicy(id), api.listDependencyRequests(id), api.registryBlocks(id),
    api.registryHooks(id), api.registryDeps(id),
  ])
  return { policy, requests, blocks, hooks, locks }
})

export const accessOptions = (id: string) => read(id, 'access', async () => {
  const [settings, spec, issues, roles] = await Promise.all([
    api.getAuthorization(id), api.getSpecForPolicies(id), api.authorizationIssues(id), api.listRoles(id, 200),
  ])
  return { settings, spec: spec as ProjectSpec, issues: issues.issues, roles: roles.items }
})
type SpecEntity = SpecForPolicies['entities'][number]
export type ProjectSpec = Omit<SpecForPolicies, 'entities' | 'auth'> & {
  entities: (Omit<SpecEntity, 'fields'> & {
    fields: (SpecEntity['fields'][number] & { required?: boolean; unique?: boolean; indexed?: boolean })[]
  })[]
  relations?: { to_entity: string; to_name: string; kind: string }[]
  regulated?: Regulated | null
  auth: (NonNullable<SpecForPolicies['auth']> & {
  enabled?: boolean; provider?: string
}) | null }
export const permissionsOptions = (id: string) => read(id, 'access', async () => {
  const entities = []
  for (let offset = 0; ; offset += 200) {
    const { items, total } = await api.listEntities(id, 200, offset)
    entities.push(...items)
    if (!items.length || entities.length >= total) break
  }
  return { entities, permissions: await api.listAllPermissions(id) }
}, 'permissions')
export const matrixOptions = (id: string) => read(id, 'access', () => api.getAccessMatrix(id), 'matrix')
export const coverageOptions = (id: string) => read(id, 'access', () => api.authorizationCoverage(id), 'coverage')

export type Framework = 'soc2' | 'hipaa' | 'pci'
export type ControlStatus = 'met' | 'unmet' | 'not_applicable'
export type Control = {
  id: string; title: string; description: string; framework: Framework; status: ControlStatus; reason: string
  evidence: { fact: string; value: unknown }[]; tests: { file: string; name: string; where: string }[]
}
type ControlReport = Record<ControlStatus, number> & { controls: Control[] }
export type RetentionRule = { entity: string; days: number; date_field: string; action: 'purge' | 'anonymise'; anonymise_fields: string[] }
export type ExportEntity = { entity: string; subject_field: string | null }
export type ExportField = { entity: string; field: string; treatment: 'keep' | 'drop' | 'hash' | 'generalise' }
export type ProtectedField = { entity: string; field: string; mode: 'encrypt' | 'tokenise'; searchable: boolean }
export type Compliance = {
  enabled: boolean; roles: string[]; retention: RetentionRule[]; consent_purposes: string[]
  break_glass: { enabled: boolean; roles: string[]; max_minutes: number }
  export_entities: ExportEntity[]; export_fields: ExportField[]; export_consent_purpose: string | null
}
export type Regulated = { enabled: boolean; key_provider: 'file' | 'env' | 'command'; fields: ProtectedField[] }
export type ComplianceBlocks = { compliance: Compliance; regulated: Regulated }
export type BlockRead<K extends keyof ComplianceBlocks> = Record<K, ComplianceBlocks[K] | null> &
  { version: number; row_version: number | null; updated_at: string | null }

export const frameworks = ['soc2', 'hipaa', 'pci'] as const
export const controlStatuses = ['met', 'unmet', 'not_applicable'] as const
function controlsReport(value: unknown): ControlReport {
  if (!value || typeof value !== 'object' || !('controls' in value) || !Array.isArray(value.controls) ||
    !('met' in value) || typeof value.met !== 'number' || !('unmet' in value) || typeof value.unmet !== 'number' ||
    !('not_applicable' in value) || typeof value.not_applicable !== 'number') {
    throw new ApiError(200, { code: 'bad_response', message: '', details: [] })
  }
  return { met: value.met, unmet: value.unmet, not_applicable: value.not_applicable,
    controls: value.controls.filter((row): row is Control => row && typeof row.id === 'string' &&
      typeof row.title === 'string' && controlStatuses.includes(row.status) && frameworks.includes(row.framework) &&
      Array.isArray(row.evidence) && Array.isArray(row.tests)) }
}
export const complianceControlsOptions = (id: string, framework?: Framework) => read(id, 'compliance',
  async () => controlsReport(await api.getComplianceControls(id, framework)), framework ?? 'all')
export const complianceBlockOptions = <K extends keyof ComplianceBlocks>(id: string, block: K) =>
  read(id, 'compliance', async () => {
    const value = await api.getBlock(id, block)
    if (typeof value.version !== 'number' || !(block in value) ||
      (value[block] !== null && (typeof value[block] !== 'object' || Array.isArray(value[block])))) {
      throw new ApiError(200, { code: 'bad_response', message: '', details: [] })
    }
    return value as BlockRead<K>
  }, block)
export const complianceChoicesOptions = (id: string) => read(id, 'compliance', async () => {
  const [spec, roles] = await Promise.all([api.getSpecForPolicies(id), api.getBehaviorRoles(id)])
  return { spec: spec as ProjectSpec, roles: roles.roles }
}, 'choices')
export const complianceIssuesOptions = (id: string) => read(id, 'compliance', () => api.getBehaviorIssues(id), 'issues')

function putAuthorization(id: string, settings: AuthorizationSettings, confirm: boolean) {
  const { model, policies, attachments, field_access, version } = settings
  const body: AuthorizationWrite & { confirm_weakening: boolean } =
    { model, policies, attachments, field_access, expected_version: version, confirm_weakening: confirm }
  return api.putAuthorization(id, body)
}
export const controlsApi = {
  requestDependency: api.requestDependency,
  approveDependency: api.approveDependency,
  denyDependency: api.denyDependency,
  revokeDependency: api.revokeDependency,
  approveRegistryHook: api.approveRegistryHook,
  putAuthorization,
  recommendAuthorization: api.recommendAuthorization,
  recommendFromProject: api.recommendFromProject,
  simulateAuthorization: api.simulateAuthorization,
  createRole: api.createRole,
  updateRole: api.updateRole,
  deleteRole: api.deleteRole,
  bulkUpsertPermissions: api.bulkUpsertPermissions,
  deletePermission: api.deletePermission,
  diffAccess: api.diffAccess,
  async downloadComplianceEvidence(id: string, framework: Framework) {
    const { blob, filename } = await api.downloadComplianceEvidence(id, framework)
    saveBlob(blob, filename)
    return filename
  },
  putBlock<K extends keyof ComplianceBlocks>(id: string, block: K, data: ComplianceBlocks[K], version: number) {
    return api.putBlock(id, block, { [block]: data, expected_version: version })
  },
}
export function prefetchSecureControls(client: QueryClient, id: string, section: 'access' | 'dependencies' | 'compliance') {
  if (section === 'access') return client.prefetchQuery(accessOptions(id))
  if (section === 'dependencies') return client.prefetchQuery(dependencyOptions(id))
  return client.prefetchQuery(complianceControlsOptions(id))
}

export function weakeningDetails(error: unknown) {
  if (!(error instanceof ApiError) || error.code !== 'access_weakened') return []
  return error.details.flatMap(item => {
    if (!item || typeof item !== 'object') return []
    const detail = item as Record<string, unknown>
    return typeof detail.role === 'string' && typeof detail.entity === 'string' && typeof detail.target === 'string'
      ? [{ role: detail.role, entity: detail.entity, target: detail.target,
        before: String(detail.before ?? ''), after: String(detail.after ?? '') }] : []
  })
}

export function editableError(error: unknown) {
  return error instanceof ApiError && (error.status === 409 || error.status === 422) ? error.message : undefined
}
