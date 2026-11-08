import type { Approval } from './types'

export const KIND_LABEL: Record<string, string> = {
  A: 'Plan',
  B: 'Spec change',
  C: 'Custom code',
  D: 'Risky change',
  E: 'Outside action',
}
export const kindLabel = (k: string) => KIND_LABEL[k] ?? `Gate ${k}`

export const RISK_LABEL: Record<string, string> = {
  auth: 'Changes sign-in',
  tenancy: 'Changes tenancy',
  money: 'Touches money fields',
  public_endpoints: 'Opens public endpoints',
  data_deletion: 'Can delete data',
  new_egress: 'New outside connection',
  new_dependencies: 'Adds packages',
}
export const riskLabel = (f: string) => RISK_LABEL[f] ?? f

export type Tab = 'pending' | 'decided'
/** Pending tab = still open; decided tab = everything the server has closed (approved, denied, expired, superseded). */
export const tabOf = (a: Pick<Approval, 'state'>): Tab => (a.state === 'pending' ? 'pending' : 'decided')

/** The server applies expiry on read; the clock check only covers a page left open past the deadline. */
export function effectiveState(a: Pick<Approval, 'state' | 'expires_at'>, now = Date.now()): string {
  if (a.state === 'pending' && Date.parse(a.expires_at) <= now) return 'expired'
  return a.state
}

export function expiryText(a: Pick<Approval, 'state' | 'expires_at'>, now = Date.now()): string {
  const left = Date.parse(a.expires_at) - now
  if (Number.isNaN(left)) return ''
  if (a.state !== 'pending') return ''
  if (left <= 0) return 'Expired'
  const h = Math.floor(left / 3_600_000)
  if (h >= 48) return `Expires in ${Math.floor(h / 24)} days`
  if (h >= 1) return `Expires in ${h} h`
  return `Expires in ${Math.max(1, Math.round(left / 60_000))} min`
}

export const STATE_LABEL: Record<string, string> = {
  pending: 'Waiting for you', approved: 'Approved', denied: 'Denied', expired: 'Expired', superseded: 'Replaced by a newer request',
}
export const stateLabel = (s: string) => STATE_LABEL[s] ?? s

export interface DecisionGate { canDecide: boolean; reason: string }
/** myRole is null when it could not be read: the server still enforces the rule (403), so the buttons stay usable. */
export function decisionGate(a: Pick<Approval, 'state' | 'expires_at' | 'requires_owner'>, myRole: string | null, now = Date.now()): DecisionGate {
  const st = effectiveState(a, now)
  if (st === 'expired') return { canDecide: false, reason: 'This request has expired. The agent has to ask again.' }
  if (st === 'superseded') return { canDecide: false, reason: 'A newer request replaced this one.' }
  if (st !== 'pending') return { canDecide: false, reason: `Already ${st}.` }
  if (myRole === 'viewer') return { canDecide: false, reason: 'Viewers can read approvals but not decide them.' }
  if (a.requires_owner && myRole !== null && myRole !== 'owner') {
    return { canDecide: false, reason: 'Only a project owner can decide this one: it concerns security, data removal, outside actions or AI-written code.' }
  }
  return { canDecide: true, reason: '' }
}

/** Deny needs a reason; approve does not. */
export const noteValid = (approve: boolean, note: string) => approve || note.trim().length > 0

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const str = (v: unknown, max = 300) => (typeof v === 'string' ? v.slice(0, max) : '')

export interface DiffRow { section: string; added: string[]; removed: string[]; changed: string[]; changedOnly: boolean }

const names = (v: unknown): string[] => (Array.isArray(v) ? v.map((x) => (typeof x === 'string' ? x : isObj(x) ? str(x.name ?? x.id ?? JSON.stringify(x), 120) : String(x))).slice(0, 100) : [])
/** Structured spec diff from the final approval: [{section, added[], removed[], changed[]} | {section, changed:true}]. */
export function diffRowsOf(raw: unknown): DiffRow[] {
  if (!Array.isArray(raw)) return []
  const out: DiffRow[] = []
  for (const d of raw.slice(0, 100)) {
    if (!isObj(d) || typeof d.section !== 'string') continue
    const changedOnly = d.changed === true
    out.push({ section: d.section.slice(0, 80), added: names(d.added), removed: names(d.removed), changed: changedOnly ? [] : names(d.changed), changedOnly })
  }
  return out
}

export interface HookRow { name: string; author: string; ai: boolean }
export interface Detail {
  summary: string
  hooks: HookRow[]
  files: string[]
  gateHash: string
  specDiff: string[]
  diffRows: DiffRow[]
  gatesGreen: boolean
  facts: Array<{ key: string; value: string }>
  hasAiCode: boolean
}

const KNOWN = new Set(['summary', 'hooks', 'hook', 'files', 'file', 'gate_report_hash', 'final', 'run_id', 'author', 'sha256', 'spec_diff', 'diff', 'gates_green', 'changes_summary', 'effects', 'hook_effects'])

const scalar = (v: unknown): string => {
  if (typeof v === 'string') return v.slice(0, 300)
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  if (Array.isArray(v)) return v.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join(', ').slice(0, 300)
  if (isObj(v)) return JSON.stringify(v).slice(0, 300)
  return ''
}

/** Everything the reviewer must see, from an approval payload of any kind. Unknown keys are listed as plain facts, never hidden. */
export function describePayload(payload: Record<string, unknown>): Detail {
  const hooks: HookRow[] = []
  if (Array.isArray(payload.hooks)) {
    for (const h of payload.hooks) {
      if (typeof h === 'string') hooks.push({ name: h, author: 'unknown', ai: false })
      else if (isObj(h) && typeof h.name === 'string') hooks.push({ name: h.name, author: str(h.author, 20) || 'human', ai: h.author === 'ai' })
    }
  }
  if (typeof payload.hook === 'string') hooks.push({ name: payload.hook, author: str(payload.author, 20) || 'unknown', ai: payload.author === 'ai' })
  const files = [...(Array.isArray(payload.files) ? payload.files : []), ...(typeof payload.file === 'string' ? [payload.file] : [])]
    .filter((f): f is string => typeof f === 'string').slice(0, 200)
  const diffRaw = payload.spec_diff ?? payload.diff
  const diffRows = diffRowsOf(diffRaw)
  const specDiff = Array.isArray(diffRaw) ? diffRaw.filter((d) => !(isObj(d) && typeof d.section === 'string')).map((d) => (typeof d === 'string' ? d : JSON.stringify(d))).slice(0, 200) : typeof diffRaw === 'string' ? diffRaw.split('\n').slice(0, 200) : []
  const facts: Detail['facts'] = []
  for (const [key, v] of Object.entries(payload)) {
    if (KNOWN.has(key)) continue
    const value = scalar(v)
    if (value) facts.push({ key, value })
  }
  if (payload.effects !== undefined || payload.hook_effects !== undefined) facts.push({ key: 'effects', value: scalar(payload.effects ?? payload.hook_effects) })
  return {
    summary: str(payload.summary, 1000) || str(payload.changes_summary, 1000),
    hooks, files, gateHash: str(payload.gate_report_hash, 80), specDiff, diffRows, gatesGreen: payload.gates_green === true, facts,
    hasAiCode: hooks.some((h) => h.ai) || payload.author === 'ai' || payload.effects !== undefined || payload.hook_effects !== undefined,
  }
}

export const approvalsLink = (projectId: string, approvalId?: string) => `#/p/${projectId}/approvals${approvalId ? `?approval=${approvalId}` : ''}`
export const approvalIdFromHash = (hash: string): string | null => hash.match(/[?&]approval=([0-9a-fA-F-]{8,40})/)?.[1] ?? null

/** Gate A has its own page. */
export const reviewHref = (projectId: string, a: Pick<Approval, 'id' | 'kind' | 'run_id'>) =>
  a.kind === 'A' ? `#/p/${projectId}/plan?run=${a.run_id}` : approvalsLink(projectId, a.id)

export const pendingCount = (list: Approval[], now = Date.now()) => list.filter((a) => effectiveState(a, now) === 'pending').length

/** S3-006: the list endpoint is a bare array today; tolerate a paginated `{items}` envelope, junk rows, and rows with a missing payload or flags. */
export function approvalList(raw: unknown): Approval[] {
  const rows = Array.isArray(raw) ? raw : isObj(raw) && Array.isArray(raw.items) ? raw.items : []
  const out: Approval[] = []
  for (const r of rows) {
    if (!isObj(r) || typeof r.id !== 'string' || typeof r.kind !== 'string') continue
    out.push({
      ...(r as unknown as Approval),
      payload: isObj(r.payload) ? r.payload : {},
      risk_flags: Array.isArray(r.risk_flags) ? r.risk_flags.filter((f): f is string => typeof f === 'string') : [],
      subject: typeof r.subject === 'string' ? r.subject : '',
      run_id: typeof r.run_id === 'string' ? r.run_id : '',
    })
  }
  return out
}

const stable = (v: unknown): string =>
  Array.isArray(v) ? `[${v.map(stable).join(',')}]` : isObj(v) ? `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${stable(v[k])}`).join(',')}}` : JSON.stringify(v ?? null)

/** S3-004/5: what the reviewer saw. If this differs when they click, the request changed under them and nothing is sent. */
export const approvalFingerprint = (a: Approval): string =>
  stable([a.id, a.kind, a.state, a.bound_spec_hash, a.bound_commit ?? null, a.payload_hash ?? null, a.payload, a.risk_flags])

export interface DecideFailure { text: string; reload: boolean }
/** Server refusals of a decision that mean "your view is out of date" (reload and review again) or "cannot be decided now". */
export function decideFailure(code: string | undefined, fallback: string): DecideFailure {
  switch (code) {
    case 'approval_already_decided': return { text: 'This request changed: it was already decided by someone else. Review it again.', reload: true }
    case 'approval_expired': return { text: 'This request changed: it has expired, so it can no longer be approved. The agent has to ask again.', reload: true }
    case 'approval_changed': return { text: 'This request changed since you opened it. Review it again before you decide.', reload: true }
    case 'run_finished': return { text: 'The run has already finished, so this request can no longer be decided. Nothing was changed by your click.', reload: true }
    case 'separation_of_duties': return { text: 'This organisation requires someone other than the person who started the run to decide it. Ask another person.', reload: false }
    case 'approval_forbidden': return { text: 'Your role may not decide this request. Ask a project owner.', reload: false }
    default: return { text: fallback, reload: false }
  }
}

const OP_LABEL: Record<string, string> = {
  remove_entity: 'Remove the entity', remove_field: 'Remove the field', update_field: 'Change the field', add_relation: 'Add a relation',
  change_tenancy_mode: 'Change the tenancy mode', weaken_access_rule: 'Weaken the access rule',
}
export interface GateD { headline: string; phrase: string; rows: Array<{ key: string; value: string }> }
/** C-005: Gate D shows what exactly changes and asks for the affected name to be typed. */
export function gateDInfo(payload: Record<string, unknown>): GateD {
  const s = (k: string) => (typeof payload[k] === 'string' ? (payload[k] as string).slice(0, 120) : '')
  const op = s('op_type')
  const target = s('package')
    ? `${s('package')}${s('version') ? `==${s('version')}` : ''}`
    : [s('entity'), s('name')].filter(Boolean).join('.') || [s('from_entity'), s('to_entity')].filter(Boolean).join(' -> ') || s('name')
  const rows = Object.entries(payload).filter(([k]) => !['run_id', 'op_type'].includes(k)).map(([key, v]) => ({ key, value: (typeof v === 'string' ? v : JSON.stringify(v) ?? '').slice(0, 300) }))
  return { headline: `${OP_LABEL[op] ?? (op || 'Apply a risky change to')}${target ? ` ${target}` : ''}`, phrase: target || 'APPROVE', rows }
}
export const confirmMatches = (typed: string, phrase: string) => typed.trim() === phrase
