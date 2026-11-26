import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { api, ApiError, saveBlob } from '../../../../api/client'
import { authHeader, BASE_URL, notifySessionLost, refreshOutcome } from '../../../../api/session'
import type {
  ApiErrorBody, DeploymentSettings, DeploymentWrite, GenerationSummary, MemberRole, MigrationPlanResponse,
  Page, Preview, UpgradeProposalDetail, UpgradeProposalSummary, UserAccount,
} from '../../../../api/types'

export type {
  AuthConfig, DeployEnvironment, DeploymentPlan, DeploymentSettings, DeploymentWrite, KeycloakConfig,
  MigrationPlanResponse, PaymentsConfig, Scorecard, ScorecardCheck, StorageConfig, UpgradeProposalDetail,
  UpgradeProposalSummary, UpgradeStatus, UserAccount, ValidationIssue,
} from '../../../../api/types'

export type ShipProps = {
  projectId: string
  role?: MemberRole
  rolePending?: boolean
  roleError?: boolean
  retryRole?: () => void
  slug?: string
  revision?: number
  version?: number
}

export const canEdit = (role?: MemberRole) => role === 'editor' || role === 'owner'
export const shipError = (error: unknown) => error instanceof ApiError ? error : undefined
export const pageSize = 20
export const shipKeys = {
  project: (id: string) => ['projects', id, 'ship'] as const,
  section: (id: string, section: string) => [...shipKeys.project(id), section] as const,
  read: (id: string, section: string, ...key: unknown[]) => [...shipKeys.section(id, section), ...key] as const,
}

const project = encodeURIComponent
const options = { retry: false, retryOnMount: false, staleTime: 15_000 }
export const deployOptions = (id: string) => queryOptions({
  ...options, queryKey: shipKeys.section(id, 'deployment'), queryFn: () => api.getDeployment(project(id)),
})
export const issuesOptions = (id: string) => queryOptions({
  ...options, queryKey: shipKeys.read(id, 'deployment', 'issues'), queryFn: () => api.deploymentIssues(project(id)),
})
export const sizingOptions = (id: string, body: DeploymentWrite | null) => queryOptions({
  ...options, queryKey: shipKeys.read(id, 'deployment', 'sizing', body), enabled: body !== null,
  queryFn: () => body === null ? Promise.reject(new Error('missing_plan_body')) : api.deploymentPlan(project(id), body),
})

export function useDeploySave(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: DeploymentWrite) => api.putDeployment(project(id), body),
    onSuccess: async (data: DeploymentSettings) => {
      const key = deployOptions(id).queryKey
      await client.cancelQueries({ queryKey: key, exact: true })
      client.setQueryData(key, data)
      void client.invalidateQueries({ queryKey: ['projects', id] })
    },
  })
}

export type ShipPreview = Preview & { migration?: MigrationPlanResponse | null }
export type GenerationDetail = GenerationSummary & {
  spec_snapshot: Record<string, unknown>
  file_manifest: { path: string; size: number; sha256: string }[]
}
export type DownloadOptions = { destructive?: boolean; acceptBaseline?: boolean }

export const generationsOptions = (id: string, page: number) => queryOptions({
  ...options, queryKey: shipKeys.read(id, 'generate', 'history', page),
  queryFn: () => api.listGenerations(project(id), pageSize, (page - 1) * pageSize),
})
export const generationOptions = (id: string, generation: string) => queryOptions({
  ...options, queryKey: shipKeys.read(id, 'generate', 'detail', generation),
  queryFn: async ({ signal }): Promise<GenerationDetail> => {
    const response = await generationResponse('/generations/' + encodeURIComponent(generation), signal)
    const detail = await response.json() as GenerationDetail
    if (detail.project_id !== id) throw new ApiError(404, { code: 'not_found', message: '', details: [] })
    return detail
  },
})

// The shared client does not expose generation details, download flags, or generation headers.
async function generationResponse(path: string, signal?: AbortSignal) {
  const send = () => fetch(BASE_URL + path, { credentials: 'include', headers: authHeader('app'), signal })
  let response = await send()
  if (response.status === 401) {
    const outcome = await refreshOutcome('app')
    if (outcome === 'ok') response = await send()
    if (outcome === 'lost') notifySessionLost('app')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as Partial<ApiErrorBody> | null
    throw new ApiError(response.status, {
      code: body?.code ?? 'bad_response', message: body?.message ?? '', details: Array.isArray(body?.details) ? body.details : [],
    })
  }
  return response
}

export async function downloadGeneration(id: string, fallback: string, approval: DownloadOptions = {}) {
  const params = new URLSearchParams()
  if (approval.destructive) params.set('allow_destructive', 'true')
  if (approval.acceptBaseline) params.set('accept_unreadable_baseline', 'true')
  const response = await generationResponse('/projects/' + project(id) + '/generate/download' + (params.size ? '?' + params : ''))
  const filename = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1] ?? fallback
  return { blob: await response.blob(), filename, id: response.headers.get('X-Generation-Id'), hash: response.headers.get('X-Spec-Hash') }
}

export const generationApi = {
  check: (id: string) => api.validateProject(project(id)),
  preview: (id: string): Promise<ShipPreview> => api.previewGeneration(project(id)),
  kit: (id: string, fallback: string) => api.downloadSelfHostKit(project(id), fallback),
  download: downloadGeneration,
  save: saveBlob,
  resend: api.resendVerification,
}

async function optionalConfig<T>(load: () => Promise<T>) {
  try { return await load() } catch (error) { if (shipError(error)?.status === 404) return null; throw error }
}

export const setupOptions = (id: string, generation: string) => queryOptions({
  ...options, queryKey: shipKeys.read(id, 'generate', 'setup', generation),
  queryFn: async () => {
    const auth = await optionalConfig(() => api.getAuthConfig(project(id)))
    const [keycloak, payments, storage] = await Promise.all([
      auth?.enabled && auth.provider === 'keycloak' ? optionalConfig(() => api.getKeycloak(project(id))) : null,
      optionalConfig(() => api.getPayments(project(id))),
      optionalConfig(() => api.getStorage(project(id))),
    ])
    return { auth, keycloak, payments, storage }
  },
})

// Use the session cache owned by the shell. A verification refusal explicitly refreshes it.
export function refreshDownloadAccount(client: QueryClient) {
  return client.fetchQuery<UserAccount | null>({ queryKey: ['entry', 'session'], queryFn: api.me, retry: false, staleTime: 0 })
}

export const scoreOptions = (id: string) => queryOptions({
  ...options, queryKey: shipKeys.read(id, 'upgrades', 'score'), queryFn: () => api.getScorecard(project(id)),
})
export const upgradesOptions = (id: string, page: number) => queryOptions({
  ...options, queryKey: shipKeys.read(id, 'upgrades', 'list', page),
  queryFn: () => api.listUpgrades(project(id), pageSize, (page - 1) * pageSize),
})
export const proposalOptions = (id: string, proposal: string) => queryOptions({
  ...options, queryKey: shipKeys.read(id, 'upgrades', 'detail', proposal),
  queryFn: () => api.getUpgrade(project(id), encodeURIComponent(proposal)),
})
export const patchOptions = (id: string, proposal: string) => queryOptions({
  ...options, queryKey: shipKeys.read(id, 'upgrades', 'patch', proposal),
  queryFn: () => api.getUpgradePatch(project(id), encodeURIComponent(proposal)),
})

export function useUpgradeCreate(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.createUpgrade(project(id)),
    onSuccess: proposal => cacheProposal(client, id, proposal),
  })
}

export function useUpgradeDecision(id: string, proposal: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (decision: 'dismiss' | 'applied') => decision === 'dismiss'
      ? api.dismissUpgrade(project(id), encodeURIComponent(proposal))
      : api.markUpgradeApplied(project(id), encodeURIComponent(proposal)),
    onSuccess: result => cacheProposal(client, id, result),
  })
}

async function cacheProposal(client: QueryClient, id: string, proposal: UpgradeProposalDetail) {
  const key = proposalOptions(id, proposal.id).queryKey
  await client.cancelQueries({ queryKey: key, exact: true })
  client.setQueryData(key, proposal)
  const lists = { queryKey: shipKeys.read(id, 'upgrades', 'list') }
  client.setQueriesData<Page<UpgradeProposalSummary>>(lists, page => page && ({
    ...page, items: page.items.map(item => item.id === proposal.id ? proposal : item),
  }))
  await Promise.all([
    client.invalidateQueries(lists),
    client.invalidateQueries({ queryKey: scoreOptions(id).queryKey }),
  ])
}

export function downloadPatch(proposal: string, text: string) {
  saveBlob(new Blob([text], { type: 'text/x-diff' }), 'upgrade-' + proposal + '.patch')
}

export async function prefetchShip(client: QueryClient, id: string, section: 'deployment' | 'generate' | 'upgrades', page = 1) {
  if (section === 'deployment') {
    await Promise.all([client.prefetchQuery(deployOptions(id)), client.prefetchQuery(issuesOptions(id))])
  } else if (section === 'generate') {
    await client.prefetchQuery(generationsOptions(id, page))
  } else {
    await Promise.all([client.prefetchQuery(scoreOptions(id)), client.prefetchQuery(upgradesOptions(id, page))])
  }
}
