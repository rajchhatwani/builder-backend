import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import { BASE_URL, CSRF_HEADERS, authHeader, refreshOutcome, notifySessionLost } from '../../../../api/session'
import { aiApi } from '../../../../shell/ai/aiApi'
import { approvalFingerprint } from '../../../../shell/ai/approvalLogic'
import { isLive } from '../../../../shell/ai/buildLogic'
import { workspaceApi } from '../../../../shell/ai/workspaceApi'
import type { Approval, GateRunResult, Preview, Run, RunDetail, RunPage, Step } from '../../../../shell/ai/types'
import { guidedKeys } from './guided'

export type { Approval, Preview, Run, GateRunResult } from '../../../../shell/ai/types'

type RunWithSteps = Omit<RunDetail, 'steps'> & { steps: (Step & { prompt_hash?: string; tool_set_hash?: string })[] }
const projectPath = (project: string) => '/projects/' + encodeURIComponent(project)
const runPath = (project: string) => projectPath(project) + '/agent/runs'
const options = { retry: false, retryOnMount: false }

async function projectRequest<T>(path: string, method: 'GET' | 'POST' | 'DELETE' = 'GET', body?: object): Promise<T> {
  const send = () => fetch(BASE_URL + path, {
    method, credentials: 'include',
    headers: { ...CSRF_HEADERS, ...authHeader('app'), ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  let response = await send()
  if (response.status === 401) {
    const result = await refreshOutcome('app')
    if (result === 'ok') response = await send()
    if (result === 'lost') notifySessionLost('app')
  }
  const value = await response.json().catch(() => null)
  if (!response.ok || value === null) throw new ApiError(response.status, {
    code: typeof value?.code === 'string' ? value.code : 'bad_response',
    message: typeof value?.message === 'string' ? value.message : '',
    details: Array.isArray(value?.details) ? value.details : [],
  })
  return value as T
}

export const deliveryApi = {
  listRuns: (id: string, offset: number) => offset === 0 ? aiApi.listRuns(id) : projectRequest<RunPage>(runPath(id) + '?limit=20&offset=' + offset),
  getRun: (id: string, run: string, offset: number): Promise<RunWithSteps> => offset === 0
    ? aiApi.getRun(id, encodeURIComponent(run))
    : projectRequest(runPath(id) + '/' + encodeURIComponent(run) + '?limit=200&offset=' + offset),
  createRun: (id: string, goal: string, workspace_id: string | null) => projectRequest<Run>(runPath(id), 'POST', { goal, workspace_id }),
  pause: aiApi.pauseRun,
  resume: aiApi.resumeRun,
  cancel: aiApi.cancelRun,
  gates: aiApi.runGates,
  listApprovals: aiApi.listApprovals,
  getApproval: aiApi.getApproval,
  decide: aiApi.decide,
  platformBudget: aiApi.platformBudget,
  listPreviews: aiApi.listPreviews,
  getPreview: aiApi.getPreview,
  createPreview: aiApi.createPreview,
  rotatePreview: aiApi.rotatePreviewToken,
  stopPreview: (id: string, preview: string) => projectRequest<Preview>(projectPath(id) + '/previews/' + encodeURIComponent(preview), 'DELETE'),
  getWorkspace: api.getWorkspace,
  createWorkspace: api.createWorkspace,
  listRoles: api.listRoles,
  checkpoint: api.createCheckpoint,
  rollback: api.rollbackWorkspace,
  discardWorkspace: api.discardWorkspace,
  files: workspaceApi.list,
  downloadKit: api.downloadSelfHostKit,
}

export const deliveryKeys = {
  runs: (id: string) => [...guidedKeys.project(id), 'runs'] as const,
  inbox: (id: string) => [...guidedKeys.approvals(id), 'inbox'] as const,
  review: (id: string, approval: string) => [...guidedKeys.approvals(id), 'review', approval] as const,
  previews: (id: string) => [...guidedKeys.project(id), 'previews'] as const,
  workspace: (id: string, workspace: string) => [...guidedKeys.workspaces(id), workspace] as const,
  roles: (id: string) => [...guidedKeys.project(id), 'roles'] as const,
  files: (id: string, workspace: string) => [...guidedKeys.workspaces(id), workspace, 'files'] as const,
  projectInfo: (id: string) => [...guidedKeys.project(id), 'projectInfo'] as const,
  orgs: [...guidedKeys.account, 'orgs'] as const,
  budget: (slug: string) => [...guidedKeys.account, 'budget', slug] as const,
}

export const runsOptions = (id: string, page = 1) => queryOptions({
  ...options, queryKey: [...deliveryKeys.runs(id), 'list', page],
  queryFn: () => deliveryApi.listRuns(id, (page - 1) * 20),
})
export const runOptions = (id: string, run: string, page = 1) => queryOptions({
  ...options, queryKey: [...deliveryKeys.runs(id), 'detail', run, page], enabled: Boolean(run),
  queryFn: () => deliveryApi.getRun(id, run, (page - 1) * 200),
  refetchInterval: query => query.state.data && isLive(query.state.data) ? 3000 : false,
  refetchIntervalInBackground: false,
})
export const inboxOptions = (id: string, states: string[], run?: string, live = false) => queryOptions({
  ...options, queryKey: [...deliveryKeys.inbox(id), states, run ?? null],
  queryFn: async () => {
    const batches = await Promise.all(states.map(state => deliveryApi.listApprovals(id, { state: state || undefined, run_id: run, limit: 200 })))
    return { rows: [...new Map(batches.flat().map(row => [row.id, row])).values()]
      .sort((a, b) => b.created_at.localeCompare(a.created_at)), capped: batches.some(batch => batch.length === 200) }
  },
  refetchInterval: live ? 3000 : false, refetchIntervalInBackground: false,
})
export const reviewOptions = (id: string, approval: string) => queryOptions({
  ...options, queryKey: deliveryKeys.review(id, approval), queryFn: () => deliveryApi.getApproval(id, approval),
  refetchOnWindowFocus: false, refetchOnReconnect: false,
})
export const previewsOptions = (id: string) => queryOptions({
  ...options, queryKey: deliveryKeys.previews(id), queryFn: () => deliveryApi.listPreviews(id),
})
export const workspaceOptions = (id: string, workspace: string) => queryOptions({
  ...options, queryKey: deliveryKeys.workspace(id, workspace), queryFn: () => deliveryApi.getWorkspace(id, workspace),
})
export const rolesOptions = (id: string) => queryOptions({
  ...options, queryKey: deliveryKeys.roles(id), queryFn: async () => {
    const first = await deliveryApi.listRoles(id, 100)
    const rest = await Promise.all(Array.from({ length: Math.max(0, Math.ceil(first.total / 100) - 1) },
      (_, index) => deliveryApi.listRoles(id, 100, (index + 1) * 100)))
    return [first, ...rest].flatMap(page => page.items)
  },
})
export const filesOptions = (id: string, workspace: string) => queryOptions({
  ...options, queryKey: deliveryKeys.files(id, workspace), queryFn: () => deliveryApi.files(id, workspace),
})

export function usePlatformBudget(id: string) {
  const project = useQuery({ ...options, queryKey: deliveryKeys.projectInfo(id), queryFn: () => api.getProject(id) })
  const orgs = useQuery({ ...options, queryKey: deliveryKeys.orgs, queryFn: api.listOrgs, enabled: Boolean(project.data?.organization_id) })
  const slug = orgs.data?.items.find(org => org.id === project.data?.organization_id)?.slug ?? ''
  const budget = useQuery({ ...options, queryKey: deliveryKeys.budget(slug), queryFn: () => deliveryApi.platformBudget(slug), enabled: Boolean(slug) })
  return { data: budget.data, failed: project.isError || orgs.isError || budget.isError, retry: () => {
    if (project.isError) void project.refetch()
    else if (orgs.isError) void orgs.refetch()
    else void budget.refetch()
  } }
}

export function useRunAction(id: string, run: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (action: 'pause' | 'resume' | 'cancel' | 'gates'): Promise<Run | GateRunResult> => deliveryApi[action](id, encodeURIComponent(run)),
    onSettled: () => Promise.all([
      client.invalidateQueries({ queryKey: deliveryKeys.runs(id) }),
      client.invalidateQueries({ queryKey: guidedKeys.approvals(id) }),
      client.invalidateQueries({ queryKey: guidedKeys.workspaces(id) }),
    ]),
  })
}

export function useApprovalDecision(id: string, approval: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ seen, approve, note }: { seen: Approval; approve: boolean; note: string }) => {
      const latest = await deliveryApi.getApproval(id, approval)
      if (approvalFingerprint(latest) !== approvalFingerprint(seen)
        || seen.expires_at !== latest.expires_at || seen.requires_owner !== latest.requires_owner
        || seen.subject !== latest.subject || seen.run_id !== latest.run_id) return { approval: latest, changed: true }
      return { approval: await deliveryApi.decide(id, approval, approve, note, undefined, seen), changed: false }
    },
    onSuccess: result => {
      client.setQueryData(deliveryKeys.review(id, approval), result.approval)
      void client.invalidateQueries({ queryKey: deliveryKeys.inbox(id) })
      void client.invalidateQueries({ queryKey: deliveryKeys.runs(id) })
    },
  })
}
