import { queryOptions, useQuery } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import { authHeader, BASE_URL, notifySessionLost, refreshOutcome } from '../../../../api/session'
import type { AccessMatrix, GenerationSummary, SpecOp } from '../../../../api/types'
import { aiApi } from '../../../../shell/ai/aiApi'
import type { RequirementsMap } from '../../../../shell/ai/types'
import type { DiagramId } from '../catalogue'
import type { Spec } from '../model'

export type { AccessMatrix, GenerationSummary, RequirementsMap, SpecOp }

export const diagramKeys = {
  project: (id: string) => ['projects', id, 'diagrams'] as const,
  spec: (id: string) => [...diagramKeys.project(id), 'spec'] as const,
  source: (id: string, kind: string, selection?: string | number) =>
    [...diagramKeys.project(id), kind, selection ?? null] as const,
}

const options = { retry: false, retryOnMount: false, staleTime: 15_000 }
export const specOptions = (id: string) => queryOptions({
  ...options, queryKey: diagramKeys.spec(id), queryFn: () => api.getSpecJson(id),
})

type GenerationDetail = GenerationSummary & { file_manifest: { path: string; size: number }[] }

// The existing client exposes generation summaries. Fetch its detail with the same session and refresh behavior.
async function readGeneration(generationId: string, signal: AbortSignal): Promise<string[]> {
  const send = () => fetch(`${BASE_URL}/generations/${encodeURIComponent(generationId)}`, {
    credentials: 'include', headers: authHeader('app'), signal,
  })
  let response = await send()
  if (response.status === 401) {
    const outcome = await refreshOutcome('app')
    if (outcome === 'ok') response = await send()
    if (outcome === 'lost') notifySessionLost('app')
  }
  const body = await response.json().catch(() => null)
  if (!response.ok || !body) {
    throw new ApiError(response.status, { code: body?.code ?? 'bad_response', message: body?.message ?? '', details: body?.details ?? [] })
  }
  const generation = body as GenerationDetail
  return generation.file_manifest.filter(file => typeof file.path === 'string').map(file => file.path)
}

export function sourceError(error: unknown) {
  return error && typeof error === 'object' && 'status' in error ? error.status : undefined
}

export type DiagramSources = {
  matrix?: AccessMatrix
  ops?: SpecOp[]
  before?: Spec
  requirements?: RequirementsMap
  generations?: GenerationSummary[]
  paths?: string[]
  version?: number
  totalOps?: number
}

export const historyPageSize = 25

export function useDiagramSources(id: string, view: DiagramId, selection: string | undefined, page: number, ready: boolean) {
  const matrix = useQuery({
    ...options, queryKey: diagramKeys.source(id, 'access'), queryFn: () => api.getAccessMatrix(id),
    enabled: ready && view === 'D13',
  })
  const ops = useQuery({
    ...options, queryKey: diagramKeys.source(id, 'ops', page), queryFn: () => api.listSpecOps(id, historyPageSize, (page - 1) * historyPageSize),
    enabled: ready && view === 'D41',
  })
  const parsedVersion = selection?.match(/^\d{1,15}$/) ? Number(selection) : undefined
  const version = parsedVersion ?? ops.data?.items[1]?.seq ?? 0
  const hasHistory = Boolean(ops.data?.items.length)
  const past = useQuery({
    ...options, queryKey: diagramKeys.source(id, 'at', version), queryFn: () => api.getSpecAt(id, version),
    enabled: ready && view === 'D41' && hasHistory,
  })
  const requirements = useQuery({
    ...options, queryKey: diagramKeys.source(id, 'requirements'), queryFn: () => aiApi.getRequirements(id),
    enabled: ready && view === 'D43',
  })
  const generations = useQuery({
    ...options, queryKey: diagramKeys.source(id, 'generations'), queryFn: () => api.listGenerations(id),
    enabled: ready && (view === 'D03' || view === 'D42'),
  })
  const generationId = generations.data?.items[0]?.id
  const generation = useQuery({
    ...options, queryKey: diagramKeys.source(id, 'generation', generationId), queryFn: ({ signal }) => readGeneration(generationId!, signal),
    enabled: ready && view === 'D03' && Boolean(generationId),
  })

  const source = view === 'D13' ? matrix : view === 'D41' ? ops.isSuccess && hasHistory ? past : ops
    : view === 'D43' ? requirements : view === 'D03' && generations.isSuccess && generationId ? generation
    : view === 'D03' || view === 'D42' ? generations : undefined
  const data: DiagramSources = {
    matrix: matrix.data, ops: ops.data?.items, before: past.data, requirements: requirements.data,
    generations: generations.data?.items, paths: generation.data, version, totalOps: ops.data?.total,
  }
  return { data, source }
}
