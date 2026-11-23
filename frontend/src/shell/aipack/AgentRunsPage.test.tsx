import axe from 'axe-core'
import { act, createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { click, flush, mount, q, qa, setInput, typeInto } from '../ai/testUtils'
import { AgentRunsPage } from './AgentRunsPage'

const EVIL = '<img src=x onerror=alert(1)>'
const REG = {
  agents: [
    { name: 'scribe', stage: 'answer', autonomy: 'suggest', actions: ['note'], max_actions_per_run: 5, require_eval: null, eval_ready: null },
    { name: 'clerk', stage: 'answer', autonomy: 'auto', actions: ['note', 'create_row'], max_actions_per_run: 3, require_eval: 'clerk-suite', eval_ready: false },
  ],
  actions: [{ name: 'note', kind: 'note', description: 'Write a note', risk: 'low', max_autonomy: 'auto', entity: null, fields: [] }],
}
const STAT = { agent: 'scribe', runs: 4, proposals: 6, executed: 1, rejected: 2, pending: 3, outcome_success: 1, outcome_failure: 0, outcome_neutral: 0, success_rate_bp: 10000 }
const PROP = { id: 'p1', action: 'note', kind: 'note', risk: 'low', args: { text: EVIL }, allowed_autonomy: 'suggest', status: 'suggested', reason: null, result: null, error_code: null }
const RUN = { id: 'r1', agent: 'scribe', goal: `do ${EVIL}`, mode: 'suggest', effective_autonomy: 'suggest', status: 'completed', error_code: null, started_by: 'abcdef12', created_at: '2026-01-01', proposals: [PROP] }
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })

function api(over: (m: string, url: string) => Response | undefined = () => undefined) {
  const calls: { m: string; url: string; body?: string }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    calls.push({ m, url, body: init.body as string | undefined })
    const o = over(m, url)
    if (o) return o
    if (m === 'POST') return json(RUN, 201)
    if (url.endsWith('/ai/agents')) return json(REG)
    if (url.includes('/stats')) return json({ agents: [STAT] })
    if (/\/runs\/r1/.test(url)) return json(RUN)
    if (url.includes('/runs')) return json({ items: [RUN], total: 1 })
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const load = (f: typeof fetch) => mount(createElement(AgentRunsPage, { projectId: 'p', session: readySession(f) }))
const post = (calls: { m: string; body?: string }[]) => calls.filter((c) => c.m === 'POST')

describe('AgentRunsPage', () => {
  it('gates without a session and has a single h1', async () => {
    const host = await mount(createElement(AgentRunsPage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('agent-runs-no-origin')).not.toBeNull()
    expect(host.querySelectorAll('h1')).toHaveLength(1)
  })
  it('shows registry, stats, runs and links to the approvals page', async () => {
    const { f } = api()
    await load(f)
    expect(qa('registry-agent')).toHaveLength(2)
    expect(qa('registry-agent')[1].textContent).toContain('clerk-suite: not passed yet')
    expect(q('stats-row')?.textContent).toContain('100%')
    expect(qa('run-row')).toHaveLength(1)
    expect(q('agents-approvals-link')?.getAttribute('href')).toBe('#/p/p/agentactions')
  })
  it('starts a suggest (dry) run immediately, without a confirmation', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('start-agent') as HTMLSelectElement, 'scribe')
    expect(q('start-mode-note')?.textContent).toMatch(/suggest mode/)
    await typeInto(q('start-goal') as HTMLTextAreaElement, 'summarise')
    await click(q('start-run'))
    expect(q('start-confirm')).toBeNull()
    const b = JSON.parse(post(calls)[0].body!)
    expect(b.goal).toBe('summarise')
    expect(b.mode).toBe('suggest')
    expect(b.idempotency_key.length).toBeGreaterThan(0)
    expect(calls.find((c) => c.m === 'POST')!.url).toContain('/ai/agents/scribe/runs')
    expect(q('start-ok')).not.toBeNull()
  })
  it('requires confirmation before a non-dry run and starts it once', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('start-agent') as HTMLSelectElement, 'clerk')
    await typeInto(q('start-goal') as HTMLTextAreaElement, 'file it')
    expect(q('start-mode-note')?.textContent).toMatch(/auto mode.*not a dry run.*has not passed/)
    await click(q('start-run'))
    expect(q('start-confirm')?.textContent).toMatch(/not a dry run/)
    expect(post(calls)).toHaveLength(0)
    const yes = q('start-yes')!
    await act(async () => { yes.click(); yes.click() })
    await flush()
    expect(post(calls)).toHaveLength(1)
  })
  it('picking suggest on an auto agent is dry; picking draft asks first', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('start-agent') as HTMLSelectElement, 'clerk')
    await typeInto(q('start-goal') as HTMLTextAreaElement, 'x')
    await setInput(q('start-mode') as HTMLSelectElement, 'suggest')
    await click(q('start-run'))
    expect(q('start-confirm')).toBeNull()
    expect(JSON.parse(post(calls)[0].body!).mode).toBe('suggest')
    await setInput(q('start-agent') as HTMLSelectElement, 'clerk')
    await typeInto(q('start-goal') as HTMLTextAreaElement, 'y')
    await setInput(q('start-mode') as HTMLSelectElement, 'draft')
    await click(q('start-run'))
    expect(q('start-confirm')).not.toBeNull()
  })
  it('only offers modes up to the chosen agent ceiling and resets the mode when the agent changes', async () => {
    const { f } = api()
    await load(f)
    const opts = () => Array.from((q('start-mode') as HTMLSelectElement).options).map((o) => o.value)
    await setInput(q('start-agent') as HTMLSelectElement, 'clerk')
    expect(opts()).toEqual(['', 'suggest', 'draft', 'auto'])
    await setInput(q('start-mode') as HTMLSelectElement, 'auto')
    await setInput(q('start-agent') as HTMLSelectElement, 'scribe')
    expect(opts()).toEqual(['', 'suggest'])
    expect((q('start-mode') as HTMLSelectElement).value).toBe('')
    expect(q('start-mode-note')?.textContent).toMatch(/suggest mode/)
  })
  it('shows loading while the registry is pending', async () => {
    const { f } = api()
    const inner = f as unknown as (u: string, i: RequestInit) => Promise<Response>
    const slow = vi.fn((u: string, i: RequestInit) => (u.endsWith('/ai/agents') ? new Promise<Response>(() => {}) : inner(u, i))) as unknown as typeof fetch
    await load(slow)
    expect(q('registry-loading')).not.toBeNull()
  })
  it('validates locally and shows server refusals (autonomy, role)', async () => {
    const { f, calls } = api((m) => (m === 'POST' ? json({ code: 'autonomy_exceeded', message: 'x' }, 403) : undefined))
    await load(f)
    await click(q('start-run'))
    expect(q('start-error')?.textContent).toBe('Choose an agent.')
    await setInput(q('start-agent') as HTMLSelectElement, 'scribe')
    await click(q('start-run'))
    expect(q('start-error')?.textContent).toBe('Describe the goal.')
    expect(post(calls)).toHaveLength(0)
    await typeInto(q('start-goal') as HTMLTextAreaElement, 'g')
    await click(q('start-run'))
    expect(q('start-error')?.textContent).toMatch(/above the autonomy/)
  })
  it('shows a role refusal on start', async () => {
    const { f } = api((m) => (m === 'POST' ? json({ code: 'forbidden', message: 'x' }, 403) : undefined))
    await load(f)
    await setInput(q('start-agent') as HTMLSelectElement, 'scribe')
    await typeInto(q('start-goal') as HTMLTextAreaElement, 'g')
    await click(q('start-run'))
    expect(q('start-error')?.textContent).toMatch(/role may not/)
  })
  it('shows run detail with untrusted text rendered as text only', async () => {
    const { f, calls } = api()
    const host = await load(f)
    await click(q('run-open'))
    expect(calls.some((c) => c.url.endsWith('/ai/agents/runs/r1'))).toBe(true)
    expect(q('run-goal')?.textContent).toContain(EVIL)
    expect(q('run-proposal')?.textContent).toContain(EVIL)
    expect(host.querySelector('img')).toBeNull()
    expect(q('run-approvals-link')).not.toBeNull()
  })
  it('passes the run filters', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('runs-agent') as HTMLSelectElement, 'clerk')
    await setInput(q('runs-status') as HTMLSelectElement, 'failed')
    expect(calls.some((c) => /\/runs\?.*agent=clerk/.test(c.url) && /status=failed/.test(c.url))).toBe(true)
  })
  it('shows role refusal, empty and missing-block states', async () => {
    const a = api((_m, u) => (u.endsWith('/ai/agents') ? json({ code: 'forbidden' }, 403) : u.includes('/stats') ? json({ agents: [] }) : u.includes('/runs') ? json({ items: [], total: 0 }) : undefined))
    await load(a.f)
    expect(q('registry-error')?.textContent).toMatch(/role may not/)
    expect(q('stats-empty')).not.toBeNull()
    expect(q('runs-empty')).not.toBeNull()
    expect(q('start-unavailable')).not.toBeNull()
  })
  it('has no axe violations', async () => {
    const { f } = api()
    const host = await load(f)
    await setInput(q('start-agent') as HTMLSelectElement, 'clerk')
    await typeInto(q('start-goal') as HTMLTextAreaElement, 'x')
    await click(q('start-run'))
    await click(q('run-open'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
