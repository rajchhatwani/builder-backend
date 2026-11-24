import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import { authHeader, BASE_URL, CSRF_HEADERS, notifySessionLost, refreshOutcome } from '../../../../api/session'
import { aiApi } from '../../../../shell/ai/aiApi'
import type { Approval, RequirementItem, RequirementsMap, Run } from '../../../../shell/ai/types'

export type { Approval, RequirementQuestion } from '../../../../shell/ai/types'
export type MapItem = RequirementItem & { subject?: string | null; value?: string | null }
type MapRead = Omit<RequirementsMap, 'id' | 'items'> & { id: string | null; items: MapItem[] }
type StartRun = { accept_assumptions: boolean; phase: number; workspace_id: string | null }
type ItemUpdate = { text?: string; status?: 'open' | 'out_of_scope'; covered_by?: string | null }

class RequirementsError extends ApiError {
  readonly retryAfter: string | null

  constructor(status: number, body: ConstructorParameters<typeof ApiError>[1], retryAfter: string | null) {
    super(status, body)
    this.retryAfter = retryAfter
  }
}

// The existing guided client fixes the start and item request bodies, and drops Retry-After.
// Keep the missing options at the feature boundary, using the shared session transport.
async function requirementsWrite<T>(project: string, suffix: string, method: 'POST' | 'PUT', data: FormData | StartRun | ItemUpdate): Promise<T> {
  const send = () => fetch(`${BASE_URL}/projects/${encodeURIComponent(project)}/requirements/${suffix}`, {
    method, credentials: 'include',
    headers: { ...(data instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...CSRF_HEADERS, ...authHeader('app') },
    body: data instanceof FormData ? data : JSON.stringify(data),
  })
  let response = await send()
  if (response.status === 401) {
    const outcome = await refreshOutcome('app')
    if (outcome === 'ok') response = await send()
    if (outcome === 'lost') notifySessionLost('app')
  }
  const body = await response.json().catch(() => null)
  if (!response.ok || !body) {
    throw new RequirementsError(response.status, {
      code: typeof body?.code === 'string' ? body.code : 'bad_response',
      message: typeof body?.message === 'string' ? body.message : '',
      details: Array.isArray(body?.details) ? body.details : [],
    }, response.headers.get('Retry-After'))
  }
  return body as T
}

export const guidedApi = {
  getRequirements: (id: string): Promise<MapRead> => aiApi.getRequirements(id),
  intake: (id: string, prompt: string, files: File[]) => {
    const body = new FormData()
    body.append('prompt', prompt)
    for (const file of files) body.append('files', file)
    return requirementsWrite<MapRead>(id, 'intake', 'POST', body)
  },
  updateItem: (id: string, item: string, body: ItemUpdate) =>
    requirementsWrite<MapRead>(id, `items/${encodeURIComponent(item)}`, 'PUT', body),
  startRun: (id: string, body: StartRun) => requirementsWrite<Run>(id, 'start-run', 'POST', body),
  answer: aiApi.answer,
  listApprovals: aiApi.listApprovals,
  getApproval: aiApi.getApproval,
  decide: aiApi.decide,
}

export const guidedKeys = {
  account: ['guided', 'account'] as const,
  project: (id: string) => ['guided', id] as const,
  map: (id: string) => [...guidedKeys.project(id), 'requirements'] as const,
  approvals: (id: string) => [...guidedKeys.project(id), 'approvals'] as const,
  members: (id: string) => [...guidedKeys.project(id), 'members'] as const,
  workspaces: (id: string) => [...guidedKeys.project(id), 'workspaces'] as const,
}
const readOptions = { retry: false, retryOnMount: false, staleTime: 15_000 }
export const mapOptions = (id: string) => queryOptions({
  ...readOptions, queryKey: guidedKeys.map(id), queryFn: () => guidedApi.getRequirements(id),
})
export const approvalOptions = (id: string, run?: string) => queryOptions({
  ...readOptions,
  queryKey: [...guidedKeys.approvals(id), run ?? null],
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
  queryFn: () => guidedApi.listApprovals(id, { ...(run ? { run_id: run } : { state: 'pending' }), limit: 200 }),
})

export function useGuidedAccess(id: string) {
  const account = useQuery({ ...readOptions, queryKey: guidedKeys.account, queryFn: api.me })
  const members = useQuery({ ...readOptions, queryKey: guidedKeys.members(id), queryFn: () => api.listMembers(id) })
  const role = members.data?.find(member => member.user_id === account.data?.id)?.role
  return {
    account, members, role,
    pending: account.isPending || members.isPending,
    failed: account.isError || members.isError,
    retry: () => { void account.refetch(); void members.refetch() },
    verified: Boolean(account.data?.email_verified_at) || Boolean(account.data && account.data.platform_role !== 'customer'),
  }
}

export function useGuidedWorkspaces(id: string, enabled: boolean) {
  return useQuery({ ...readOptions, queryKey: guidedKeys.workspaces(id), queryFn: () => api.listWorkspaces(id), enabled })
}

type MapWrite =
  | { kind: 'intake'; prompt: string; files: File[] }
  | { kind: 'item'; item: string; body: ItemUpdate }
  | { kind: 'answer'; question: string; body: { answer?: string; accept_assumption?: boolean } }

export function useMapWrite(id: string) {
  const client = useQueryClient()
  const queryKey = guidedKeys.map(id)
  return useMutation({
    scope: { id: `requirements:${id}` },
    mutationFn: async (action: MapWrite) => {
      await client.cancelQueries({ queryKey })
      switch (action.kind) {
        case 'intake': return guidedApi.intake(id, action.prompt, action.files)
        case 'item': return guidedApi.updateItem(id, action.item, action.body)
        case 'answer': return guidedApi.answer(id, action.question, action.body)
      }
    },
    onSuccess: map => { client.setQueryData(queryKey, map) },
    onSettled: () => client.invalidateQueries({ queryKey }),
  })
}

export function useStartRun(id: string) {
  const client = useQueryClient()
  return useMutation({
    scope: { id: `requirements:${id}` },
    mutationFn: (body: StartRun) => guidedApi.startRun(id, body),
    onSettled: () => client.invalidateQueries({ queryKey: guidedKeys.map(id) }),
  })
}

export function errorCode(error: unknown) {
  return error instanceof ApiError ? error.code : undefined
}

export function errorStatus(error: unknown) {
  return error instanceof ApiError ? error.status : undefined
}

export function errorDetails(error: unknown) {
  return error instanceof ApiError ? error.details : []
}

export function retrySeconds(error: unknown) {
  if (!(error instanceof RequirementsError) || !error.retryAfter) return undefined
  if (/^\d+$/.test(error.retryAfter)) return Number(error.retryAfter)
  const expires = Date.parse(error.retryAfter)
  return Number.isFinite(expires) ? Math.max(0, Math.ceil((expires - Date.now()) / 1000)) : undefined
}

export function serverMessage(error: unknown) {
  return error instanceof ApiError ? error.message : ''
}

export function questionConflictTexts(error: unknown) {
  return errorDetails(error).flatMap(detail =>
    detail && typeof detail === 'object' && 'text' in detail && typeof detail.text === 'string' ? [detail.text] : [],
  )
}

export function fieldMessage(error: unknown, name: string) {
  for (const detail of errorDetails(error)) {
    if (!detail || typeof detail !== 'object' || !('loc' in detail) || !Array.isArray(detail.loc)
      || !detail.loc.includes(name) || !('msg' in detail) || typeof detail.msg !== 'string') continue
    return detail.msg
  }
}

export function usePlanDecision(id: string, run: string | undefined, binding: (approval: Approval) => string) {
  const client = useQueryClient()
  const key = approvalOptions(id, run).queryKey
  function remember(queryKey: typeof key, approval: Approval) {
    client.setQueryData<Approval[]>(queryKey, previous => [
      approval, ...(previous ?? []).filter(item => item.id !== approval.id),
    ])
  }
  return useMutation({
    scope: { id: `plan-decision:${id}` },
    mutationFn: async ({ seen, approve, note, plan }: {
      seen: Approval; approve: boolean; note: string; plan?: Record<string, string[]>
    }) => {
      await client.cancelQueries({ queryKey: key })
      const latest = await guidedApi.getApproval(id, seen.id)
      if (binding(seen) !== binding(latest)) return { approval: latest, changed: true }
      return { approval: await guidedApi.decide(id, seen.id, approve, note, plan, seen), changed: false }
    },
    onSuccess: ({ approval, changed }) => {
      remember(key, approval)
      if (!changed) {
        const resultKey = approvalOptions(id, approval.run_id).queryKey
        if (!run) remember(resultKey, approval)
        void client.invalidateQueries({ queryKey: guidedKeys.approvals(id), refetchType: 'none' })
      }
    },
    onError: (error) => {
      if (errorStatus(error) === 409) void client.invalidateQueries({ queryKey: key, refetchType: 'none' })
    },
  })
}
