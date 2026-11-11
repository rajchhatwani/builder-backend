import { ApiError } from '../../api/client'
import { BASE_URL, CSRF_HEADERS, authHeader, refreshSession } from '../../api/session'
import type { Approval, GateRunResult, PlatformBudget, Preview, PreviewCreated, RequirementItem, RequirementsMap, Run, RunDetail, RunPage } from './types'

/** Thin client for the agent + requirements endpoints. Same auth as api/client.ts; multipart is sent without a JSON content type. */
async function call<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  const isForm = init.body instanceof FormData
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: { ...(isForm ? {} : { 'Content-Type': 'application/json' }), ...CSRF_HEADERS, ...authHeader('app'), ...init.headers },
  })
  if (res.status === 401 && !retried && (await refreshSession('app'))) return call<T>(path, init, true)
  if (res.status === 204) return undefined as T
  let body: unknown
  try { body = await res.json() } catch {
    if (res.ok) throw new ApiError(res.status, { code: 'bad_response', message: 'The server sent a response that could not be read', details: [] })
    body = {}
  }
  if (!res.ok) {
    const raw = (body ?? {}) as { code?: string; message?: string; details?: unknown[] }
    throw new ApiError(res.status, {
      code: typeof raw.code === 'string' ? raw.code : 'bad_response',
      message: typeof raw.message === 'string' ? raw.message : `The server answered ${res.status}`,
      details: Array.isArray(raw.details) ? raw.details : [],
    })
  }
  return body as T
}

const json = (method: string, data?: unknown): RequestInit => ({ method, body: data === undefined ? undefined : JSON.stringify(data) })
const P = (id: string) => `/projects/${id}`

/** S3-004/5: the decision names the request that was reviewed; the server answers 409 approval_changed when it moved. */
export const decisionBinding = (seen?: { payload_hash?: string | null; bound_spec_hash?: string }) => ({
  ...(seen?.payload_hash ? { expected_payload_hash: seen.payload_hash } : {}),
  ...(seen?.bound_spec_hash ? { expected_spec_hash: seen.bound_spec_hash } : {}),
})

export const aiApi = {
  getRequirements: (pid: string) => call<RequirementsMap>(`${P(pid)}/requirements`),
  intake: (pid: string, prompt: string, files: File[]) => {
    const fd = new FormData()
    fd.append('prompt', prompt)
    for (const f of files) fd.append('files', f)
    return call<RequirementsMap>(`${P(pid)}/requirements/intake`, { method: 'POST', body: fd })
  },
  answer: (pid: string, qid: string, body: { answer?: string; accept_assumption?: boolean }) =>
    call<RequirementsMap>(`${P(pid)}/requirements/questions/${encodeURIComponent(qid)}/answer`, json('POST', body)),
  putItem: (pid: string, item: Pick<RequirementItem, 'id' | 'text' | 'status'>) =>
    call<RequirementsMap>(`${P(pid)}/requirements/items/${encodeURIComponent(item.id)}`, json('PUT', { text: item.text, status: item.status })),
  startRun: (pid: string, acceptAssumptions: boolean) =>
    call<Run>(`${P(pid)}/requirements/start-run`, json('POST', { accept_assumptions: acceptAssumptions })),

  listRuns: (pid: string, limit = 20) => call<RunPage>(`${P(pid)}/agent/runs?limit=${limit}`),
  getRun: (pid: string, rid: string) => call<RunDetail>(`${P(pid)}/agent/runs/${rid}?limit=200`),
  cancelRun: (pid: string, rid: string) => call<Run>(`${P(pid)}/agent/runs/${rid}/cancel`, json('POST')),
  pauseRun: (pid: string, rid: string) => call<Run>(`${P(pid)}/agent/runs/${rid}/pause`, json('POST')),
  runGates: (pid: string, rid: string) => call<GateRunResult>(`${P(pid)}/agent/runs/${rid}/gates`, json('POST')),
  resumeRun: (pid: string, rid: string) => call<Run>(`${P(pid)}/agent/runs/${rid}/resume`, json('POST')),
  listApprovals: (pid: string, q: { state?: string; run_id?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][]).toString()
    return call<Approval[]>(`${P(pid)}/agent/approvals${qs ? `?${qs}` : ''}`)
  },
  getApproval: (pid: string, aid: string) => call<Approval>(`${P(pid)}/agent/approvals/${encodeURIComponent(aid)}`),
  /** `plan` (Gate A only): the reviewer's edited plan; the server cleans it and answers 422 plan_empty when nothing is left. */
  decide: (pid: string, aid: string, approve: boolean, note?: string, plan?: Record<string, string[]>, seen?: Pick<Approval, 'payload_hash' | 'bound_spec_hash'>) =>
    call<Approval>(`${P(pid)}/agent/approvals/${aid}/decision`, json('POST', { approve, note: note || undefined, ...(plan ? { plan } : {}), ...decisionBinding(seen) })),
  platformBudget: (orgSlug: string) => call<PlatformBudget>(`/orgs/${encodeURIComponent(orgSlug)}/ai/platform-budget`),

  listPreviews: (pid: string) => call<Preview[]>(`${P(pid)}/previews`),
  createPreview: (pid: string, workspaceId?: string | null) =>
    call<PreviewCreated>(`${P(pid)}/previews`, json('POST', workspaceId ? { workspace_id: workspaceId } : {})),
  rotatePreviewToken: (pid: string, previewId: string) => call<PreviewCreated>(`${P(pid)}/previews/${encodeURIComponent(previewId)}/rotate-token`, json('POST')),
  getPreview: (pid: string, previewId: string) => call<Preview>(`${P(pid)}/previews/${encodeURIComponent(previewId)}`),
}
