import { time } from './connect-a'
import { connectSpec } from './connect-b'

export { time }
export const caller = 'a0741b57-1bc1-4e54-a7d7-f7b0e4566228'
export const sourceId = '3ed6fa0c-d74b-4db6-ba30-312625ad750c'
export const evalId = '31c01b76-90c0-47ca-a5d2-96af92d140ce'
export const runId = 'c8a424b7-cab7-4e23-87b0-b693c0420d3e'
export const identity = { id: caller, roles: ['lead'] }
export const aiSpec = { ...connectSpec, auth: { ...connectSpec.auth,
  roles: [{ name: 'lead', label: 'Lead', inherits_from: 'admin' }, { name: 'admin', label: 'Admin' }, { name: 'staff', label: 'Staff' }] },
packs: { ai: {
  gateway: { roles: { call_roles: ['staff'], manage_roles: ['admin'] } },
  knowledge: { manage_roles: ['admin'], max_text_chars: 500_000 },
  agents: { roles: { run_roles: ['admin'], approve_roles: ['admin'] } },
  evals: { run_roles: ['admin'] },
} } }

export const paths = {
  aiusage: ['/ai/usage', '/ai/calls'],
  knowledge: ['/ai/knowledge/sources'],
  evals: ['/ai/evals/suites', '/ai/evals/runs'],
  agentruns: ['/ai/agents', '/ai/agents/stats', '/ai/agents/runs'],
} as const
export type Screen = keyof typeof paths
export const labels = {
  aiusage: ['AI usage', 'AI usage', 'calls-row', 'No AI calls yet.'],
  knowledge: ['Knowledge', 'Knowledge library', 'source-row', 'No sources yet. Add one below.'],
  evals: ['Evaluations', 'AI evals', 'suite-row', 'No eval runs yet.'],
  agentruns: ['Agent runs', 'Agent runs', 'registry-agent', 'No agent activity yet.'],
} as const
export const source = {
  id: sourceId, title: 'Returns handbook', allowed_roles: ['staff'], owner_only: false, owner_id: caller, chunk_count: 3, created_at: time,
}
const hit = { source_id: sourceId, chunk_id: 'chunk-a', title: source.title, text: 'Refunds take five days.', position: 1, score_bp: 9425 }
export const evalRun = {
  id: evalId, suite: 'returns', agent: 'scribe', score_bp: 5000, passed: false, total: 2, passed_count: 1, created_by: caller, created_at: time,
  results: [{ case: 'refund question', passed: true, proposed: ['note'], error_code: null },
    { case: 'damaged item', passed: false, proposed: [], error_code: 'budget_exceeded' }],
}
const proposal = {
  id: '6ec6c395-55f5-4ad1-bd99-87165842229a', action: 'note', kind: 'note', risk: 'low', args: { text: '<b>Check refunds</b>' },
  allowed_autonomy: 'suggest', status: 'suggested', reason: null, result: null, error_code: null, outcome: null,
}
export const run = {
  id: runId, agent: 'scribe', goal: 'Summarize returns', mode: 'suggest', effective_autonomy: 'suggest', status: 'completed',
  error_code: null, call_id: null, started_by: caller, created_at: time, proposals: [proposal],
}
const registry = {
  agents: [{ name: 'scribe', stage: 'support', autonomy: 'draft', actions: ['note'], max_actions_per_run: 2, require_eval: 'returns', eval_ready: false }],
  actions: [{ name: 'note', kind: 'note', risk: 'low', description: 'Write a note', max_autonomy: 'draft', entity: null, fields: [] }],
}
const stats = {
  agents: [{ agent: 'scribe', runs: 4, proposals: 6, executed: 1, rejected: 2, pending: 3, outcome_success: 1, outcome_failure: 0,
    outcome_neutral: 0, success_rate_bp: 10000 }],
}
const usage = {
  period: 'month', period_start: '2026-01-01', limit_micro_usd: 1000000, spent_micro_usd: 250000, reserved_micro_usd: 50000, remaining_micro_usd: 700000,
  calls_ok: 3, calls_error: 1, input_tokens: 1300, output_tokens: 300, zero_retention: true, region: 'eu',
}
const call = {
  id: 'de1e4a95-38d1-49a9-8cb5-52f362642af6', stage: 'support', status: 'ok', provider: 'local', model: 'demo', input_tokens: 320,
  output_tokens: 41, cost_micro_usd: 1234, caller_id: caller, fallback_used: false, error_code: null, created_at: time,
}
const suite = { name: 'returns', agent: 'scribe', pass_bp: 8000, case_count: 2, latest: null }
export function runtimeFixture(path: string, empty = false, method = 'GET') {
  const page = <T,>(items: T[], limit = 50) => ({ items: empty ? [] : items, total: empty ? 0 : items.length, limit, offset: 0 })
  if (path === '/auth/me') return identity
  if (path === '/ai/usage') return empty ? { ...usage, spent_micro_usd: 0, reserved_micro_usd: 0, remaining_micro_usd: 1000000,
    calls_ok: 0, calls_error: 0, input_tokens: 0, output_tokens: 0 } : usage
  if (path === '/ai/calls') return page([call])
  if (path === '/ai/knowledge/sources') return method === 'POST' ? source : page([source])
  if (path === '/ai/knowledge/search') return { hits: [hit] }
  if (path === '/ai/knowledge/ask') return { grounded: true, answer: '<b>Five days.</b>', citations: [{ ...hit, quote: hit.text }], call_id: null }
  if (path === '/ai/evals/suites') return empty ? [] : [suite]
  if (path === '/ai/evals/runs') return page([evalRun], 20)
  if ([`/ai/evals/runs/${evalId}`, '/ai/evals/suites/returns/run'].includes(path)) return evalRun
  if (path === '/ai/agents') return empty ? { agents: [], actions: [] } : registry
  if (path === '/ai/agents/stats') return empty ? { agents: [] } : stats
  if (path === '/ai/agents/runs') return page([run], 20)
  if ([`/ai/agents/runs/${runId}`, '/ai/agents/scribe/runs'].includes(path)) return run
  if (path === '/ai/agents/proposals') return page([])
}
