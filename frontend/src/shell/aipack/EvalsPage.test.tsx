import axe from 'axe-core'
import { act, createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { click, flush, mount, q, qa, setInput } from '../ai/testUtils'
import { EvalsPage } from './EvalsPage'

const RUN = { id: 'r1', suite: 'triage', agent: 'helper', score_bp: 5000, passed: false, total: 2, passed_count: 1, created_by: 'abcdef12', created_at: '2026-01-02',
  results: [{ case: 'good <b>case</b>', passed: true, proposed: ['note'], error_code: null }, { case: 'bad', passed: false, proposed: [], error_code: 'budget_exceeded' }] }
const SUITE = { name: 'triage', agent: 'helper', pass_bp: 8000, case_count: 2, latest: { id: 'r0', passed: true, score_bp: 9000, created_at: '2026-01-01' } }
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })

function api(over: (m: string, url: string) => Response | undefined = () => undefined) {
  const calls: { m: string; url: string }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    calls.push({ m, url })
    const o = over(m, url)
    if (o) return o
    if (url.includes('/suites/') && m === 'POST') return json(RUN, 201)
    if (url.includes('/suites')) return json([SUITE])
    if (/\/runs\/r1/.test(url)) return json(RUN)
    if (url.includes('/runs')) return json({ items: [RUN], total: 1 })
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const load = (f: typeof fetch) => mount(createElement(EvalsPage, { projectId: 'p', session: readySession(f) }))

describe('EvalsPage', () => {
  it('gates without a session and has a single h1', async () => {
    const host = await mount(createElement(EvalsPage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('evals-no-origin')).not.toBeNull()
    expect(host.querySelectorAll('h1')).toHaveLength(1)
  })
  it('states that runs are dry and lists suites and runs', async () => {
    const { f } = api()
    await load(f)
    expect(q('evals-dry-note')?.textContent).toMatch(/dry/)
    expect(qa('suite-row')[0].textContent).toContain('Passed at 90%')
    expect(qa('run-row')).toHaveLength(1)
  })
  it('runs a suite once (double click) and shows pass/fail with reasons as text', async () => {
    const { f, calls } = api()
    const host = await load(f)
    const b = q('suite-run')!
    await act(async () => { b.click(); b.click() })
    await flush()
    expect(calls.filter((c) => c.m === 'POST')).toHaveLength(1)
    expect(calls.find((c) => c.m === 'POST')!.url).toContain('/ai/evals/suites/triage/run')
    expect(q('eval-verdict')?.textContent).toBe('Suite failed')
    const rows = qa('eval-case')
    expect(rows[0].textContent).toContain('Pass')
    expect(rows[0].textContent).toContain('good <b>case</b>')
    expect(rows[1].textContent).toContain('Fail')
    expect(rows[1].textContent).toContain('Error: budget_exceeded')
    expect(host.querySelector('b')).toBeNull()
  })
  it('opens the detail of a past run', async () => {
    const { f, calls } = api()
    await load(f)
    await click(q('run-open'))
    expect(calls.some((c) => c.url.endsWith('/ai/evals/runs/r1'))).toBe(true)
    expect(qa('eval-case')).toHaveLength(2)
  })
  it('filters runs by suite', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('runs-suite') as HTMLInputElement, 'triage')
    expect(calls.some((c) => /\/runs\?.*suite=triage/.test(c.url))).toBe(true)
  })
  it('shows a refusal when running is not allowed', async () => {
    const { f } = api((m) => (m === 'POST' ? json({ code: 'forbidden', message: 'x' }, 403) : undefined))
    await load(f)
    await click(q('suite-run'))
    expect(q('eval-run-error')?.textContent).toMatch(/role may not/)
  })
  it('shows role refusal on reads, empty states', async () => {
    const a = api((_m, u) => (u.includes('/suites') ? json({ code: 'forbidden' }, 403) : u.includes('/runs') ? json({ items: [], total: 0 }) : undefined))
    await load(a.f)
    expect(q('suites-error')?.textContent).toMatch(/role may not/)
    expect(q('runs-empty')).not.toBeNull()
  })
  it('shows the missing-block message (404) and a loading state', async () => {
    const { f } = api((_m, u) => (u.includes('/suites') ? json({ detail: 'Not Found' }, 404) : undefined))
    await load(f)
    expect(q('suites-error')?.textContent).toMatch(/no eval harness/)
    const b = api()
    const inner = b.f as unknown as (u: string, i: RequestInit) => Promise<Response>
    const slow = vi.fn((u: string, i: RequestInit) => (u.includes('/suites') ? new Promise<Response>(() => {}) : inner(u, i))) as unknown as typeof fetch
    await load(slow)
    expect(q('suites-loading')).not.toBeNull()
  })
  it('shows the no-suites state', async () => {
    const { f } = api((_m, u) => (u.includes('/suites') ? json([]) : undefined))
    await load(f)
    expect(q('suites-empty')).not.toBeNull()
  })
  it('has no axe violations', async () => {
    const { f } = api()
    const host = await load(f)
    await click(q('run-open'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
