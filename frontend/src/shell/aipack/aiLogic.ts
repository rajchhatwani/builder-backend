/** Pure helpers for the AI dashboards (packs.ai.*). Everything the model or a document produced is UNTRUSTED text: it is
 *  only ever rendered as a React text node, never as HTML. Costs are integer micro-USD (1 USD = 1_000_000), estimates only. */
import { formatMinor } from '../money/moneyLogic'

export const MICRO_EXPONENT = 6

/** 1_500_000 -> "1.500000"; junk -> "0.000000". Integer arithmetic only. */
export const usd = (micro: unknown): string => formatMinor(typeof micro === 'number' || typeof micro === 'string' || typeof micro === 'bigint' ? micro : 0, MICRO_EXPONENT)

/** Integer basis points: 8750 -> "87.5%", 10000 -> "100%". Junk never yields NaN. */
export function bpText(bp: unknown): string {
  if (typeof bp !== 'number' || !Number.isFinite(bp)) return 'n/a'
  const n = Math.min(10000, Math.max(0, Math.round(bp)))
  const whole = Math.floor(n / 100), frac = n % 100
  return frac === 0 ? `${whole}%` : `${whole}.${String(frac).padStart(2, '0').replace(/0$/, '')}%`
}

/** Plain-text clip for untrusted text (display only; the full value stays in the API). */
export const clip = (t: unknown, max = 600): string => {
  const s = typeof t === 'string' ? t : t === null || t === undefined ? '' : String(t)
  return s.length > max ? `${s.slice(0, max)}…` : s
}

/** Untrusted structured data (agent args / results) as pretty JSON text. */
export function jsonText(v: unknown): string {
  try { return JSON.stringify(v ?? null, null, 2) ?? 'null' } catch { return 'null' }
}

export const shortId = (id: unknown): string => (typeof id === 'string' ? id.slice(0, 8) : '')

export function pageInfo(total: number, limit: number, offset: number) {
  if (!(total > 0)) return { from: 0, to: 0, hasPrev: false, hasNext: false }
  return { from: offset + 1, to: Math.min(total, offset + limit), hasPrev: offset > 0, hasNext: offset + limit < total }
}

/** Human message for an AI API error body {code,message}. `what` names the area ("AI gateway", "knowledge library"...). */
export function aiErrorMessage(status: number, body: unknown, what: string): string {
  const b = (typeof body === 'object' && body !== null ? body : {}) as { code?: unknown; message?: unknown }
  const code = typeof b.code === 'string' ? b.code : ''
  const message = typeof b.message === 'string' ? b.message : ''
  switch (code) {
    case 'budget_exceeded': return 'The AI budget for this period is used up.'
    case 'autonomy_exceeded': return 'That mode is above the autonomy this agent is allowed. Choose a lower mode.'
    case 'eval_required': return 'This agent may run in auto mode only after its latest eval run passed. Run its eval suite first.'
    case 'unknown_agent': return 'There is no such agent in this project.'
    case 'unknown_suite': case 'unknown_eval_suite': return 'There is no such eval suite in this project.'
    case 'idempotency_conflict': return 'That idempotency key was already used with different contents. Start again with a new key.'
    case 'invalid_output': return 'The model answered something the run could not use. Nothing was changed.'
    case 'rate_limited': return 'Too many requests. Wait a moment and try again.'
  }
  if (status === 401) return 'Your session was not accepted. Sign in again.'
  if (status === 403) return `Your role may not do this (the spec lists the roles that may use the ${what}).`
  if (status === 404 && !code) return `This project has no ${what} (404). Enable it in the spec to use this page.`
  if (status === 429) return 'Too many requests. Wait a moment and try again.'
  return message || `The ${what} answered ${status}.`
}

/** Starting a run is "dry" only in suggest mode. An unset mode runs at the agent's own autonomy (the API's default). */
export const effectiveStartMode = (picked: string, agentAutonomy: string): string => picked || agentAutonomy
export const isDryMode = (mode: string): boolean => mode === 'suggest'

export const AUTONOMY_LABEL: Record<string, string> = {
  suggest: 'Suggest (dry: proposals only, nothing runs)',
  draft: 'Draft (proposals wait for a human to approve)',
  auto: 'Auto (low-risk actions may execute without a human)',
}
