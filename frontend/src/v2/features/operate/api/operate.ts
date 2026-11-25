import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import type { ObservabilityWrite, MetricDefinition, ReportBody } from '../../../../api/types'
import type { SpecJobs, SpecWorkflows } from '../../../../shell/connect/specTypes'
import { issuesFromDetail } from '../../../../forms/schemaLogic'
import type { operateSections } from '../../../projectNavigation'

export type OperateProps = {
  projectId: string
  role?: string | null
  rolePending?: boolean
  roleError?: unknown
  retryRole?: () => void
}
export const canWrite = ({ role, rolePending, roleError }: OperateProps) =>
  !rolePending && !roleError && (role === 'owner' || role === 'editor')

type Blocks = { jobs: SpecJobs; workflows: SpecWorkflows }
type Block = keyof Blocks
type BlockReply<K extends Block> = Record<K, Blocks[K] | null> & { version: number; updated_at: string | null }

export const operateKeys = {
  root: (id: string) => ['projects', id, 'operate'] as const,
  item: (id: string, ...parts: (string | number)[]) => [...operateKeys.root(id), ...parts] as const,
}
const readOptions = { staleTime: 15_000, retry: false, retryOnMount: false }
const read = <T>(id: string, parts: (string | number)[], queryFn: () => Promise<T>) =>
  queryOptions({ ...readOptions, queryKey: operateKeys.item(id, ...parts), queryFn })
export const observationOptions = (id: string) => read(id, ['observability'], () => api.getObservability(id))
export const observationIssues = (id: string) => read(id, ['observability', 'issues'], () => api.observabilityIssues(id))
export const blockOptions = <K extends Block>(id: string, block: K) =>
  read(id, [block], async () => await api.getBlock(id, block) as BlockReply<K>)
export const specOptions = (id: string) => read(id, ['spec'], () => api.getSpecJson(id))
export const workerSpecOptions = (id: string) => read(id, ['worker-spec'], () => api.getSpecBlocks(id))
export const issuesOptions = (id: string) => read(id, ['issues'], () => api.getBehaviorIssues(id))
export const advisorOptions = (id: string) => read(id, ['advisor'], () => api.getAdvisor(id))
export const rolesOptions = (id: string) => read(id, ['roles'], () => api.getBehaviorRoles(id))

export const metricsOptions = (id: string) => read(id, ['metrics'], () => api.listMetrics(id))
export const reportsOptions = (id: string) => read(id, ['reports'], () => api.listReports(id))
export const metricValueOptions = (id: string, key: string) => read(id, ['metric-value', key], () => api.getMetricValue(id, key))
export const reportValueOptions = (id: string, report: string) => read(id, ['report-value', report], () => api.getReportValue(id, report))
// The existing client accepts a cumulative limit. Keep the network limit within the route's 200-run ceiling.
export const runsOptions = (id: string, report: string, limit: number) =>
  read(id, ['runs', report, limit], () => api.listReportRuns(id, report, limit))

type SearchResult = { entity: string; as_role: string | null; adapter: string; total: number; hits: Record<string, unknown>[] }
type IndexResult = { index: string; indexed: number; entities: { entity: string; searchable_fields: number; records: number }[] }
export const searchOptions = (id: string, entity: string, q: string, limit: number, role: string) => ({
  ...read(id, ['search', entity, q, limit, role], async () => await api.searchProject(id, entity, q, limit, role) as SearchResult),
  enabled: Boolean(entity && q),
})
export function useReindex(id: string) {
  return useMutation({ mutationFn: async () => await api.reindexSearch(id) as IndexResult })
}

export function useObservationWrite(id: string) {
  const client = useQueryClient()
  return useMutation({
    scope: { id: 'observability:' + id },
    mutationFn: (body: ObservabilityWrite) => api.putObservability(id, body),
    onSuccess: value => refreshProject(client, id, observationOptions(id).queryKey, value),
  })
}

export function useBlockWrite<K extends Block>(id: string, block: K) {
  const client = useQueryClient()
  return useMutation({
    scope: { id: 'operate:' + id + ':' + block },
    mutationFn: async ({ value, version }: { value: Blocks[K]; version: number }) =>
      await api.putBlock(id, block, { [block]: value, expected_version: version }) as BlockReply<K>,
    onSuccess: value => refreshProject(client, id, blockOptions(id, block).queryKey, value),
  })
}

async function refreshProject<T>(client: QueryClient, id: string, key: readonly unknown[], value: T) {
  await client.cancelQueries({ queryKey: key, exact: true })
  client.setQueryData(key, value)
  await client.invalidateQueries({ queryKey: ['projects', id], predicate: query =>
    query.queryKey.length !== key.length || query.queryKey.some((part, index) => part !== key[index]) })
}

export type MetricAction =
  | { type: 'metric-save'; key?: string; definition: MetricDefinition }
  | { type: 'report-save'; key?: string; body: ReportBody }
  | { type: 'metric-delete' | 'report-delete' | 'report-run'; key: string }

export function useMetricAction(id: string) {
  const client = useQueryClient()
  return useMutation({
    scope: { id: 'metrics:' + id },
    mutationFn: async (action: MetricAction) => {
      switch (action.type) {
        case 'metric-save': return action.key ? api.updateMetric(id, action.key, action.definition) : api.createMetric(id, action.definition)
        case 'metric-delete': return api.deleteMetric(id, action.key)
        case 'report-save': return action.key ? api.updateReport(id, action.key, action.body) : api.createReport(id, action.body)
        case 'report-delete': return api.deleteReport(id, action.key)
        case 'report-run': return api.runReport(id, action.key)
      }
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: operateKeys.root(id) })
    },
  })
}

export function errorInfo(error: unknown) {
  return error instanceof ApiError ? error : undefined
}

export function fieldErrors(error: unknown, prefix?: string) {
  const apiError = errorInfo(error)
  const entries = apiError?.status === 422 ? Object.entries(issuesFromDetail(apiError.details)) : []
  return Object.fromEntries(entries.map(([path, messages]) =>
    [prefix && path.startsWith(prefix + '.') ? path.slice(prefix.length + 1) : path, messages]))
}

export function prefetchOperate(client: QueryClient, id: string, section: typeof operateSections[number]) {
  switch (section) {
    case 'observability': return client.prefetchQuery(observationOptions(id))
    case 'jobs':
    case 'workflows': return client.prefetchQuery(blockOptions(id, section))
    case 'workers': return client.prefetchQuery(workerSpecOptions(id))
    case 'metrics': return client.prefetchQuery(metricsOptions(id))
    case 'search': return client.prefetchQuery(specOptions(id))
  }
}

export type { ObservabilitySettings, ObservabilityWrite, MetricRead, MetricDefinition, ReportRead, ReportBody, ReportMetricValue, ValidationIssue } from '../../../../api/types'
export type { SpecJobs, SpecWorkflows } from '../../../../shell/connect/specTypes'
