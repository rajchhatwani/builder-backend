import axe from 'axe-core'
import { act, createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { click, flush, mount, q, qa, setInput } from '../ai/testUtils'
import { AgentApprovalsPage } from './AgentApprovalsPage'

const P = (o: Record<string, unknown> = {}) => ({
  id: 'p1', run_id: 'r1', agent: 'triage', action: 'create_ticket', kind: 'entity_create', risk: 'high', args: { title: '<b>Pay</b>', n: 2 }, allowed_autonomy: 'auto',
  status: 'pending_approval', reason: null, result: null, error_code: null, ...o,
})
const P2 = P({ id: 'p2', action: 'note', risk: 'low', status: 'suggested', allowed_autonomy: 'suggest' })
const STATS = [{ agent: 'triage', runs: 5, proposals: 7, executed: 3, rejected: 1, pending: 2, outcome_success: 2, outcome_failure: 1, outcome_neutral: 0, success_rate_bp: 6667 }, { agent: 'idle', runs: 0, proposals: 0, executed: 0, rejected: 0, pending: 0, outcome_success: 0, outcome_failure: 0, outcome_neutral: 0, success_rate_bp: null }]
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const err = (status: number, code: string) => json({ code, message: 'raw', details: [] }, status)

function api(over: (m: string, url: string, body: unknown) => Response | undefined = () => undefined, items: unknown[] = [P(), P2], total = items.length) {
  const calls: { m: string; url: string; body: Record<string, unknown> | null; auth?: string }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    const body = init.body ? JSON.parse(init.body as string) : null
    calls.push({ m, url, body, auth: (init.headers as Record<string, string>).Authorization })
    const o = over(m, url, body)
    if (o) return o
    if (url.includes('/ai/agents/stats')) return json({ agents: STATS })
    if (m === 'GET' && url.includes('/ai/agents/proposals?')) return json({ items, total, limit: 20, offset: Number(/offset=(\d+)/.exec(url)?.[1] ?? 0) })
    if (m === 'GET' && url.includes('/ai/agents/runs/')) return json({ id: 'r1', agent: 'triage', goal: 'Triage the inbox', status: 'completed', proposals: [] })
    if (m === 'POST') return json(P({ status: 'executed' }))
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const el = (f: typeof fetch, props: Record<string, unknown> = {}) => createElement(AgentApprovalsPage, { projectId: 'p', origin: 'http://gen.test', doFetch: f, ...props })
async function load(f: typeof fetch, props: Record<string, unknown> = {}) {
  const host = await mount(el(f, props))
  await setInput(q('agentapprovals-token') as HTMLInputElement, 'TOK')
  await click(q('agentapprovals-load'))
  await flush()
  return host
}
const key = async (e: Element, k: string) => { await act(async () => { e.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true })) }); await flush() }
const posts = (calls: ReturnType<typeof api>['calls']) => calls.filter((c) => c.m === 'POST')

describe('AgentApprovalsPage', () => {
  it('asks for a token first and sends it only as bearer', async () => {
    const { f, calls } = api()
    await mount(el(f))
    expect(q('agentapprovals-notoken')).not.toBeNull(); expect(calls).toHaveLength(0)
    await setInput(q('agentapprovals-token') as HTMLInputElement, 'TOK'); await click(q('agentapprovals-load'))
    expect(calls[0].url).toMatch(/^http:\/\/gen\.test\/ai\/agents\/(proposals\?status=pending_approval&limit=20&offset=0|stats)$/)
    expect(calls.every((c) => c.auth === 'Bearer TOK')).toBe(true)
    expect(calls.some((c) => c.url.endsWith('/ai/agents/stats'))).toBe(true)
  })
  it('shows the no-origin note', async () => {
    const host = await mount(el(api().f, { origin: null }))
    expect(host.querySelector('[data-testid="agentapprovals-no-origin"]')).not.toBeNull()
  })
  it('lists proposals with agent, action, risk, autonomy and read-only args', async () => {
    await load(api().f)
    expect(q('agentapprovals-live')!.textContent).toBe('2 Pending approval proposals, showing 1 to 2.')
    expect(q('proposal-head-p1')!.textContent).toBe('triage proposes create_ticket')
    expect(q('proposal-risk-p1')!.textContent).toBe('High risk'); expect(q('proposal-risk-p2')!.textContent).toBe('Low risk')
    expect(q('proposal-meta-p1')!.textContent).toContain('Allowed autonomy: auto'); expect(q('proposal-meta-p2')!.textContent).toContain('Allowed autonomy: suggest')
    expect(q('proposal-args-p1')!.textContent).toContain('"title": "<b>Pay</b>"'); expect(q('proposal-args-p1')!.querySelector('b')).toBeNull()
    expect(q('proposal-args-p1')!.querySelector('input,textarea')).toBeNull()
  })
  it('shows the stats strip with a rate and a no-outcome agent', async () => {
    await load(api().f)
    expect(q('agent-stat-triage')!.textContent).toContain('5 runs, 7 proposals, 3 executed, 1 rejected, 2 pending')
    expect(q('agent-rate-triage')!.textContent).toBe('66.67%'); expect(q('agent-rate-idle')!.textContent).toBe('no outcomes yet')
  })
  it('stats failure does not hide the inbox', async () => {
    await load(api((m, url) => (url.includes('/stats') ? err(500, 'boom') : undefined)).f)
    expect(q('agent-stats-error')!.textContent).toMatch(/Statistics unavailable/); expect(q('proposal-p1')).not.toBeNull()
  })
  it('filters by status and offers all statuses', async () => {
    const { f, calls } = api()
    await load(f)
    const opts = Array.from((q('agentapprovals-status') as HTMLSelectElement).options).map((o) => o.value)
    expect(opts).toEqual(['pending_approval', 'suggested', 'executed', 'failed', 'acknowledged', 'rejected', 'rejected_by_policy', 'handed_off'])
    await setInput(q('agentapprovals-status') as HTMLSelectElement, 'executed')
    expect(calls.at(-1)!.url).toContain('status=executed')
  })
  it('shows loading-free empty, error and 403 states', async () => {
    await load(api(undefined, []).f)
    expect(q('agentapprovals-empty')!.textContent).toMatch(/No proposals/)
    await act(async () => { document.body.innerHTML = '' })
    await load(api((m, url) => (url.includes('/proposals?') ? err(403, 'forbidden') : undefined)).f)
    expect(q('agentapprovals-error')!.textContent).toMatch(/may not do this/)
  })
  it('shows a network failure', async () => {
    await load(api((m, url) => { if (url.includes('/proposals?')) throw new Error('offline'); return undefined }).f)
    expect(q('agentapprovals-error')!.textContent).toBe('offline')
  })
  it('pages with offset', async () => {
    const { f, calls } = api(undefined, [P(), P2], 45)
    await load(f)
    expect((q('agentapprovals-prev') as HTMLButtonElement).disabled).toBe(true)
    await click(q('agentapprovals-next'))
    expect(calls.at(-1)!.url).toContain('offset=20'); expect(q('agentapprovals-range')!.textContent).toBe('21 to 40 of 45')
  })
  it('roving focus: one tab stop, arrows move it', async () => {
    await load(api().f)
    const r1 = q('proposal-head-p1')!, r2 = q('proposal-head-p2')!
    expect(r1.tabIndex).toBe(0); expect(r2.tabIndex).toBe(-1)
    await key(r1, 'ArrowDown')
    expect(r2.tabIndex).toBe(0); expect(document.activeElement).toBe(r2)
  })
  it('shows only the actions that fit each status', async () => {
    await load(api().f)
    expect(q('approve-p1')).not.toBeNull(); expect(q('acknowledge-p1')).toBeNull(); expect(q('reject-p1')).not.toBeNull(); expect(q('handoff-p1')).not.toBeNull()
    expect(q('approve-p2')).toBeNull(); expect(q('acknowledge-p2')).not.toBeNull(); expect(q('reject-p2')).not.toBeNull(); expect(q('outcome-success-p1')).toBeNull()
  })
  it('steps back a page when deciding the last item of a later page empties it', async () => {
    let shrunk = false
    const { f, calls } = api((m, url) => {
      if (!shrunk || m !== 'GET' || !url.includes('/proposals?')) return undefined
      const off = Number(/offset=(\d+)/.exec(url)?.[1] ?? 0)
      return off >= 20 ? json({ items: [], total: 20, limit: 20, offset: off }) : json({ items: [P()], total: 20, limit: 20, offset: off })
    }, [P(), P2], 21)
    await load(f)
    await click(q('agentapprovals-next'))
    shrunk = true
    await click(q('approve-p1'))
    await flush()
    expect(calls.at(-1)!.url).toContain('offset=0')
    expect(q('agentapprovals-prev')).not.toBeNull()
  })
  it('approves and refreshes', async () => {
    const { f, calls } = api()
    await load(f); await click(q('approve-p1'))
    expect(posts(calls)[0].url).toBe('http://gen.test/ai/agents/proposals/p1/approve')
    expect(q('agentapprovals-notice')!.textContent).toBe('create_ticket: approved.')
    expect(calls.filter((c) => c.url.includes('/proposals?')).length).toBeGreaterThan(1)
  })
  it('rejects with a reason after confirming, and can cancel', async () => {
    const { f, calls } = api()
    await load(f); await click(q('reject-p1'))
    await click(q('cancel-form')); expect(q('agentapprovals-text')).toBeNull()
    await click(q('reject-p1')); await setInput(q('agentapprovals-text') as HTMLInputElement, ' too risky ')
    await click(q('confirm-reject'))
    expect(posts(calls)[0].body).toEqual({ reason: 'too risky' }); expect(q('agentapprovals-notice')!.textContent).toBe('create_ticket: rejected.')
  })
  it('hands off to a role and requires one', async () => {
    const { f, calls } = api()
    await load(f); await click(q('handoff-p1'))
    expect((q('confirm-handoff') as HTMLButtonElement).disabled).toBe(true)
    await setInput(q('agentapprovals-text') as HTMLInputElement, 'finance')
    await click(q('confirm-handoff'))
    expect(posts(calls)[0].url).toMatch(/\/p1\/handoff$/); expect(posts(calls)[0].body).toEqual({ to_role: 'finance' })
    expect(q('agentapprovals-notice')!.textContent).toBe('create_ticket: handed off to finance.')
  })
  it('shows unknown_role on hand off', async () => {
    await load(api((m, url) => (url.endsWith('/handoff') ? err(422, 'unknown_role') : undefined)).f)
    await click(q('handoff-p1')); await setInput(q('agentapprovals-text') as HTMLInputElement, 'nobody'); await click(q('confirm-handoff'))
    expect(q('proposal-error-p1')!.textContent).toMatch(/role does not exist/)
  })
  it('acknowledges a suggested proposal', async () => {
    const { f, calls } = api()
    await load(f); await click(q('acknowledge-p2'))
    expect(posts(calls)[0].url).toMatch(/\/p2\/acknowledge$/); expect(q('agentapprovals-notice')!.textContent).toBe('note: acknowledged.')
  })
  it('surfaces 409 proposal_closed clearly and refreshes the list', async () => {
    const { f, calls } = api((m, url) => (url.endsWith('/approve') ? err(409, 'proposal_closed') : undefined))
    await load(f)
    const before = calls.filter((c) => c.url.includes('/proposals?')).length
    await click(q('approve-p1'))
    expect(q('proposal-error-p1')!.textContent).toMatch(/already decided/); expect(q('proposal-error-p1')!.getAttribute('role')).toBe('alert')
    expect(calls.filter((c) => c.url.includes('/proposals?')).length).toBeGreaterThan(before)
  })
  it('surfaces autonomy_refuses_execution and self_approval_forbidden', async () => {
    for (const [st, code, re] of [[409, 'autonomy_refuses_execution', /suggest-level/], [403, 'self_approval_forbidden', /someone else must approve/], [403, 'forbidden', /may not do this/]] as const) {
      await load(api((m, url) => (url.endsWith('/approve') ? err(st, code) : undefined)).f); await click(q('approve-p1'))
      expect(q('proposal-error-p1')!.textContent).toMatch(re)
      await act(async () => { document.body.innerHTML = '' })
    }
  })
  it('offers outcome buttons for executed, failed and acknowledged proposals, once', async () => {
    const items = [P({ id: 'e1', status: 'executed' }), P({ id: 'f1', status: 'failed', error_code: 'entity_invalid' }), P({ id: 'a1', status: 'acknowledged' }), P({ id: 'e2', status: 'executed', outcome: 'success' }), P({ id: 'r9', status: 'rejected' })]
    const { f, calls } = api(undefined, items)
    await load(f)
    for (const id of ['e1', 'f1', 'a1']) expect(qa(`outcome-failure-${id}`)).toHaveLength(1)
    expect(q('outcome-success-e2')).toBeNull(); expect(q('proposal-outcome-e2')!.textContent).toBe('Outcome: Worked'); expect(q('outcome-success-r9')).toBeNull()
    expect(q('approve-e1')).toBeNull(); expect(q('proposal-meta-f1')!.textContent).toContain('failed: entity_invalid')
    await click(q('outcome-success-e1'))
    expect(posts(calls)[0].url).toMatch(/\/e1\/outcome$/); expect(posts(calls)[0].body).toEqual({ outcome: 'success' })
    expect(q('agentapprovals-notice')!.textContent).toBe('create_ticket: outcome recorded as worked.')
  })
  it('shows outcome_already_set', async () => {
    await load(api((m, url) => (url.endsWith('/outcome') ? err(409, 'outcome_already_set') : undefined), [P({ id: 'e1', status: 'executed' })]).f)
    await click(q('outcome-neutral-e1'))
    expect(q('proposal-error-e1')!.textContent).toMatch(/already recorded/)
  })
  it('shows the run goal on demand and toggles it off', async () => {
    const { f, calls } = api()
    await load(f); await click(q('run-link-p1'))
    expect(calls.at(-1)!.url).toBe('http://gen.test/ai/agents/runs/r1'); expect(q('run-goal-p1')!.textContent).toBe('Goal: Triage the inbox')
    await click(q('run-link-p1')); expect(q('run-goal-p1')).toBeNull()
  })
  it('shows a run lookup failure', async () => {
    await load(api((m, url) => (url.includes('/runs/') ? err(404, 'not_found') : undefined)).f); await click(q('run-link-p1'))
    expect(q('run-goal-p1')!.textContent).toMatch(/no longer exists/)
  })
  it('has no axe violations (inbox, reject form, run goal, errors)', async () => {
    const host = await load(api((m, url) => (url.endsWith('/approve') ? err(409, 'proposal_closed') : undefined), [P(), P2, P({ id: 'e1', status: 'executed' })]).f)
    await click(q('run-link-p1')); await click(q('approve-p1')); await click(q('reject-p2'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
