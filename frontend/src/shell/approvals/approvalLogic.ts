/** Pure helpers for the AI action approvals page (D37, packs.ai.agents). The server decides everything; this only labels and routes answers. */
export type Risk = 'low' | 'medium' | 'high' | string
export type Proposal = {
  id: string; run_id: string; agent: string; action: string; kind?: string; risk: Risk; args: Record<string, unknown>; allowed_autonomy: string; status: string
  reason?: string | null; result?: Record<string, unknown> | null; error_code?: string | null; executed_by?: string | null; decided_by?: string | null; decided_at?: string | null
  note?: string | null; handoff_role?: string | null; outcome?: string | null; outcome_by?: string | null; outcome_at?: string | null; created_at?: string
}
export type Run = { id: string; agent: string; goal: string; mode?: string; effective_autonomy?: string; status?: string }
export type AgentStat = {
  agent: string; runs: number; proposals: number; executed: number; rejected: number; pending: number
  outcome_success: number; outcome_failure: number; outcome_neutral: number; success_rate_bp: number | null
}
export const STATUSES = ['pending_approval', 'suggested', 'executed', 'failed', 'acknowledged', 'rejected', 'rejected_by_policy', 'handed_off'] as const
export const STATUS_LABEL: Record<string, string> = {
  pending_approval: 'Pending approval', suggested: 'Suggested', executed: 'Executed', failed: 'Failed', acknowledged: 'Acknowledged',
  rejected: 'Rejected', rejected_by_policy: 'Rejected by policy', handed_off: 'Handed off',
}
export const OUTCOMES = ['success', 'failure', 'neutral'] as const
export const OUTCOME_LABEL: Record<string, string> = { success: 'Worked', failure: 'Did not work', neutral: 'Neutral' }

export const canDecide = (status: string) => status === 'pending_approval'
export const canReject = (status: string) => status === 'pending_approval' || status === 'suggested'
export const canHandOff = canReject
export const canAcknowledge = (status: string) => status === 'suggested'
export const canMarkOutcome = (p: Pick<Proposal, 'status' | 'outcome'>) => ['executed', 'failed', 'acknowledged'].includes(p.status) && !p.outcome

/** 8750 -> "87.5%", 10000 -> "100%", null -> "no outcomes yet". Integer basis points only; junk never yields NaN. */
export function successRate(bp: number | null | undefined): string {
  if (bp === null || bp === undefined || !Number.isFinite(bp)) return 'no outcomes yet'
  const n = Math.min(10000, Math.max(0, Math.round(bp)))
  const whole = Math.floor(n / 100), frac = n % 100
  return frac === 0 ? `${whole}%` : `${whole}.${String(frac).padStart(2, '0').replace(/0$/, '')}%`
}
export const riskLabel = (r: string) => (r === 'high' ? 'High risk' : r === 'medium' ? 'Medium risk' : r === 'low' ? 'Low risk' : `Risk ${r}`)
export const riskColors = (r: string): { background: string; color: string } =>
  r === 'high' ? { background: '#fde8e8', color: '#7f1d1d' } : r === 'medium' ? { background: '#fff3cd', color: '#5c3d00' } : { background: '#e6f4ea', color: '#14532d' }

/** Args are untrusted model output: always shown as text, never interpreted. */
export function argsText(args: unknown): string {
  try { return JSON.stringify(args ?? {}, null, 2) ?? '{}' } catch { return '{}' }
}

export function approvalErrorMessage(status: number, body: unknown): string {
  const b = (typeof body === 'object' && body !== null ? body : {}) as { code?: unknown; message?: unknown }
  const code = typeof b.code === 'string' ? b.code : ''
  switch (code) {
    case 'proposal_closed': return 'This proposal was already decided (executed, rejected, handed off or otherwise closed), so it cannot change. The list has been refreshed.'
    case 'autonomy_refuses_execution': return 'This proposal is suggest-level: the autonomy dial refuses to execute it. Acknowledge it or reject it instead.'
    case 'self_approval_forbidden': return 'You started this run, so someone else must approve its actions (self approval is switched off in the spec).'
    case 'outcome_not_allowed': return 'An outcome can only be recorded on executed, failed or acknowledged proposals.'
    case 'outcome_already_set': return 'An outcome was already recorded for this proposal and cannot be changed.'
    case 'unknown_role': return 'That role does not exist in this project.'
    case 'budget_exceeded': return 'The AI budget for this period is used up.'
  }
  if (status === 401) return 'The token was not accepted (missing, wrong or expired).'
  if (status === 403) return code && code !== 'forbidden' && typeof b.message === 'string' && b.message ? b.message : 'Your role may not do this (the spec lists approve and read roles for agents).'
  if (status === 404) return 'That proposal or run no longer exists.'
  if (status === 409) return 'This proposal can no longer change. The list has been refreshed.'
  return (typeof b.message === 'string' && b.message) || `The agents API answered ${status}.`
}
export const isStatus = (s: string) => (STATUSES as readonly string[]).includes(s)
export const pageOffset = (page: number, limit: number) => Math.max(0, page) * limit
export function pageInfo(total: number, limit: number, offset: number) {
  if (total <= 0) return { from: 0, to: 0, hasPrev: false, hasNext: false }
  return { from: offset + 1, to: Math.min(total, offset + limit), hasPrev: offset > 0, hasNext: offset + limit < total }
}
export function moveRow(len: number, cur: number, key: string): number {
  if (len <= 0) return 0
  if (key === 'ArrowDown') return Math.min(len - 1, cur + 1)
  if (key === 'ArrowUp') return Math.max(0, cur - 1)
  if (key === 'Home') return 0
  if (key === 'End') return len - 1
  return cur
}
