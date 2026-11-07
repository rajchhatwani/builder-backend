import type { Approval, PlatformBudget, Run, Step } from './types'

export const TERMINAL = ['applied', 'stopped', 'failed', 'cancelled']
export const POLL_MS = 3000

export const isLive = (run: Pick<Run, 'state'>) => !TERMINAL.includes(run.state)

/** Poll interval for the build view, or null when nothing can change by itself (finished runs, hidden tab). */
export function pollInterval(run: Pick<Run, 'state'> | null, hidden = false): number | null {
  if (!run || hidden) return null
  return isLive(run) ? POLL_MS : null
}

export interface RunActions { cancel: boolean; resume: boolean; resumeLabel: string }
/** The API has cancel and resume (no pause). Resume continues a stopped run or starts a created one; it is held back while an approval is pending. */
export function runActions(run: Pick<Run, 'state'>, pendingApprovals: number): RunActions {
  const resumable = run.state === 'stopped' || run.state === 'created' || ((run.state === 'planning' || run.state === 'running' || run.state === 'awaiting_approval') && pendingApprovals === 0)
  return { cancel: isLive(run), resume: resumable, resumeLabel: run.state === 'created' ? 'Start' : 'Resume' }
}

export interface BudgetRow { key: 'steps' | 'repairs' | 'cost'; label: string; used: number; limit: number | null; pct: number | null; level: 'ok' | 'warn' | 'full'; text: string }

export const pct = (used: number, limit: number | null | undefined): number | null =>
  limit && limit > 0 ? Math.min(100, Math.max(0, Math.round((used / limit) * 100))) : null

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null)
export const usd = (micro: number) => `$${(micro / 1_000_000).toFixed(micro >= 1_000_000 ? 2 : 4)}`

export function budgetRows(run: Pick<Run, 'budgets' | 'steps_used' | 'repairs_used' | 'cost_micro_usd'>): BudgetRow[] {
  const mk = (key: BudgetRow['key'], label: string, used: number, limit: number | null, fmt: (n: number) => string): BudgetRow => {
    const p = pct(used, limit)
    const level = p === null ? 'ok' : p >= 100 ? 'full' : p >= 80 ? 'warn' : 'ok'
    return { key, label, used, limit, pct: p, level, text: limit ? `${fmt(used)} of ${fmt(limit)}` : fmt(used) }
  }
  const id = (n: number) => String(n)
  return [
    mk('steps', 'Steps', run.steps_used, num(run.budgets.max_steps), id),
    mk('repairs', 'Repairs', run.repairs_used, num(run.budgets.max_repairs), id),
    mk('cost', 'Cost', run.cost_micro_usd, num(run.budgets.max_cost_micro_usd), usd),
  ]
}

export function stepLine(s: Step): { what: string; ok: boolean; cost: string } {
  const what = s.kind === 'tool' ? (s.tool_name ?? 'tool') : s.kind
  const out = s.output as { cost_micro_usd?: unknown } | null
  const c = typeof out?.cost_micro_usd === 'number' ? usd(out.cost_micro_usd) : '-'
  return { what, ok: s.ok, cost: c }
}

export const pendingFor = (approvals: Approval[], runId?: string) =>
  approvals.filter((a) => a.state === 'pending' && (!runId || a.run_id === runId))

export const RUN_STATE_LABEL: Record<string, string> = {
  created: 'Ready to start', planning: 'Planning', awaiting_approval: 'Waiting for you', running: 'Building', gating: 'Checking',
  applying: 'Applying', applied: 'Done', stopped: 'Stopped', failed: 'Failed', cancelled: 'Cancelled',
}
export const runStateLabel = (s: string) => RUN_STATE_LABEL[s] ?? s

export const STAGE_TABS = ['gates', 'details', 'plan', 'diagrams', 'api', 'stage'] as const
export type StageTab = (typeof STAGE_TABS)[number]
export const TAB_READY: StageTab[] = ['gates', 'details', 'plan', 'stage']

export interface StopInfo { title: string; text: string; next: string }
/** Plain words for the codes a stopped run carries. Unknown codes fall back to the server's detail. */
export function stopInfo(code: string | null, detail?: string | null): StopInfo | null {
  if (!code) return null
  if (code === 'apply_conflict') return {
    title: 'Not applied: the project changed meanwhile',
    text: 'A person changed the live spec after you approved this. Nothing was applied and your live project is untouched. The agent\'s draft is kept.',
    next: 'The project owner can run the build again (Resume) so the agent starts from the current spec.',
  }
  if (code === 'apply_failed') return {
    title: 'Not applied: applying the change failed',
    text: 'The approved change could not be written to the project, so nothing was applied and the live spec is unchanged.',
    next: detail ? `Reason: ${detail.slice(0, 300)}. Fix the cause, then resume the run.` : 'Resume the run to try again, or take over and change it yourself.',
  }
  return { title: code, text: detail ?? '', next: '' }
}

export interface Friendly { text: string; tone: 'ok' | 'bad' | 'info'; next?: string }
/** Timeline text for the system steps the apply phase writes; null means "show the normal line". */
export function friendlyStep(s: Pick<Step, 'kind' | 'output'>): Friendly | null {
  if (s.kind !== 'system' || !s.output) return null
  const o = s.output as Record<string, unknown>
  if (o.apply_conflict === true) return { tone: 'bad', text: 'Not applied: a person changed the project after you approved. Your live project is unchanged and the draft is kept.', next: 'The owner can resume the run to build again from the current project.' }
  if (o.apply_failed === true) return { tone: 'bad', text: 'Not applied: the approved change could not be written. Your live project is unchanged.', next: 'Fix the cause and resume the run.' }
  if (o.draft === 'applied') return { tone: 'ok', text: 'The approved change was applied to your project.' }
  if (o.draft === 'discarded') return { tone: 'info', text: 'The draft was thrown away. Your live project was not changed.' }
  return null
}

/** The run is over and its change reached the project: the point where "See it work" makes sense. */
export const canSeeItWork = (run: Pick<Run, 'state'>) => run.state === 'applied'

export interface PlatformRow { pct: number | null; level: 'ok' | 'warn' | 'full'; text: string; remaining: string; limitReached: boolean }
export function platformRow(b: PlatformBudget): PlatformRow {
  const used = b.spent_micro_usd + b.reserved_micro_usd
  if (b.cap_micro_usd === null) return { pct: null, level: 'ok', text: `${usd(b.spent_micro_usd)} spent, no cap set`, remaining: '', limitReached: false }
  const p = pct(used, b.cap_micro_usd)
  const reached = b.remaining_micro_usd === 0
  const level = reached || (p !== null && p >= 100) ? 'full' : p !== null && p >= 80 ? 'warn' : 'ok'
  return {
    pct: reached ? 100 : p, level, limitReached: reached,
    text: `${usd(b.spent_micro_usd)} of ${usd(b.cap_micro_usd)}`,
    remaining: reached ? 'Limit reached' : b.remaining_micro_usd === null ? '' : `${usd(b.remaining_micro_usd)} left`,
  }
}
