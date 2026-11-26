import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../../api/client'
import { liveKey, liveRead, runtimeRequest, segment, useRuntimeWrite } from './live'
import type { Page, Session } from './live'
import { operateKeys } from './operate'
import { agentRunPath, runPath } from './tools'
import type { AgentRegistry, AgentRun, AgentStats } from './tools'

type MicroUsd = string | number
export type Usage = {
  period: string; period_start: string; region: string; zero_retention: boolean
  limit_micro_usd: MicroUsd; spent_micro_usd: MicroUsd; reserved_micro_usd: MicroUsd; remaining_micro_usd: MicroUsd
  calls_ok: number; calls_error: number; input_tokens: number; output_tokens: number
}
export const callStatuses = ['reserved', 'ok', 'error'] as const
type CallStatus = typeof callStatuses[number]
type Call = {
  id: string; caller_id: string | null; stage: string; provider: string; model: string; status: CallStatus
  input_tokens: number; output_tokens: number; cost_micro_usd: MicroUsd
  reserved_micro_usd: MicroUsd; error_code: string | null; fallback_used: boolean
  created_at: string; finished_at: string | null
}

export type Source = {
  id: string; title: string; allowed_roles: string[]; owner_only: boolean; owner_id: string; chunk_count: number; created_at: string
}
type SourceInput = { title: string; text: string; allowed_roles?: string[]; owner_only?: boolean }
type Passage = { source_id: string; chunk_id: string; title: string; score_bp: number }
type Hit = Passage & { text: string; position: number }
type Citation = Passage & { quote: string }
type SearchResult = { hits: Hit[] }
type Answer = { answer: string; grounded: boolean; citations: Citation[]; call_id: string | null }

type EvalLatest = { id: string; passed: boolean; score_bp: number; created_at: string }
type EvalSuite = { name: string; agent: string; pass_bp: number; case_count: number; latest: EvalLatest | null }
export type EvalRun = EvalLatest & {
  suite: string; agent: string; total: number; passed_count: number; created_by: string | null
  results: { case: string; passed: boolean; proposed: string[]; error_code: string | null }[]
}
export const runModes = ['suggest', 'draft', 'auto'] as const
export type RunMode = typeof runModes[number]
export const runStatuses = ['completed', 'failed', 'refused'] as const
type RunStatus = typeof runStatuses[number]
type RunInput = { goal: string; mode: RunMode; idempotency_key: string }
type Identity = { id: string; roles: string[] }
type RoleGroups = { run_roles: string[]; approve_roles: string[] }
type Settings = {
  packs?: { ai?: {
    gateway?: { roles: { call_roles: string[]; manage_roles: string[] } } | null
    knowledge?: { manage_roles: string[]; max_text_chars: number } | null
    agents?: { roles: RoleGroups } | null
    evals?: { run_roles: string[] } | null
  } | null } | null
  auth?: { roles?: { name: string; inherits_from?: string | null }[] } | null
}

const sourcePath = '/ai/knowledge/sources'
type List = { limit: number; offset: number }
export const usageOptions = (session: Session) => liveRead<Usage>(session, '/ai/usage')
export const callsOptions = (session: Session, params: List & { stage?: string; status?: CallStatus; caller_id?: string }, enabled: boolean) =>
  liveRead<Page<Call>>(session, '/ai/calls', params, enabled)
export const sourcesOptions = (session: Session, params: List) => liveRead<Page<Source>>(session, sourcePath, params)
export const useAddSource = (session: Session) => useRuntimeWrite<SourceInput, Source>(session, sourcePath)
export const useDeleteSource = (session: Session, id: string) => useRuntimeWrite<undefined, null>(session, `${sourcePath}/${segment(id)}`, 'DELETE')
export const useSearchKnowledge = (session: Session) => useRuntimeWrite<{ query: string; limit: number }, SearchResult>(session, '/ai/knowledge/search', 'POST', false)
export const useAskKnowledge = (session: Session) => useRuntimeWrite<{ question: string; limit: number }, Answer>(session, '/ai/knowledge/ask', 'POST', false)

export const suitesOptions = (session: Session) => liveRead<EvalSuite[]>(session, '/ai/evals/suites')
export const evalHistoryOptions = (session: Session, params: List & { suite?: string }) => liveRead<Page<EvalRun>>(session, '/ai/evals/runs', params)
export const evalRunOptions = (session: Session, id?: string) => liveRead<EvalRun>(session, `/ai/evals/runs/${segment(id ?? '')}`, {}, Boolean(id))
export function useRunEval(session: Session) {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: (suite: string) => runtimeRequest<EvalRun>(session, `/ai/evals/suites/${segment(suite)}/run`, 'POST'),
    onSuccess: () => cache.invalidateQueries({ queryKey: liveKey(session) }),
  })
}

export const registryOptions = (session: Session) => liveRead<AgentRegistry>(session, '/ai/agents')
export const statsOptions = (session: Session, agent?: string) => liveRead<AgentStats>(session, '/ai/agents/stats', { agent })
export const agentHistoryOptions = (session: Session, params: List & { agent?: string; status?: RunStatus }) =>
  liveRead<Page<AgentRun>>(session, '/ai/agents/runs', params)
export const agentRunOptions = (session: Session, id?: string) => liveRead<AgentRun>(session, runPath(id ?? ''), {}, Boolean(id))
export const useStartAgent = (session: Session, agent: string) => useRuntimeWrite<RunInput, AgentRun>(session, agentRunPath(agent))

const aiSettingsOptions = (id: string, enabled: boolean) => queryOptions({
  queryKey: operateKeys.item(id, 'ai-settings'),
  queryFn: async () => await api.getSpecJson(id) as Settings,
  enabled, retry: false, retryOnMount: false,
})
const identityOptions = (session: Session) => liveRead<Identity>(session, '/auth/me')
export function useAiAccess(session: Session, writable: boolean) {
  const account = useQuery(identityOptions(session))
  const settings = useQuery(aiSettingsOptions(session.projectId, writable))
  const groups = settings.data?.packs?.ai
  const roles = new Set(account.data?.roles)
  const definitions = settings.data?.auth?.roles ?? []
  const parents = new Map(definitions.map(role => [role.name, role.inherits_from]))
  for (const role of roles) {
    const parent = parents.get(role)
    if (parent) roles.add(parent)
  }
  const allows = (group?: string[]) => group?.some(role => roles.has(role)) || group?.length === 0
  const can = (...groups: (string[] | undefined)[]) => Boolean(writable && account.data && groups.some(allows))
  return {
    owner: account.data?.id, roles: definitions.map(role => role.name),
    textLimit: groups?.knowledge?.max_text_chars ?? 5_000_000,
    manage: can(groups?.knowledge?.manage_roles),
    ask: can(groups?.gateway?.roles.call_roles, groups?.gateway?.roles.manage_roles),
    eval: can(groups?.evals?.run_roles, groups?.agents?.roles.approve_roles),
    run: can(groups?.agents?.roles.run_roles),
    pending: writable && (account.isPending || settings.isPending),
    error: writable ? account.error || settings.error : null,
    retry: () => Promise.all([account.refetch(), ...(writable ? [settings.refetch()] : [])]),
  }
}
