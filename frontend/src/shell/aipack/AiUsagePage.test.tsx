import axe from 'axe-core'
import { act, createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { click, flush, mount, q, qa, setInput } from '../ai/testUtils'
import { AiUsagePage } from './AiUsagePage'

const USAGE = { period: 'day', period_start: '2026-01-01', limit_micro_usd: 1_000_000, spent_micro_usd: 250_000, reserved_micro_usd: 50_000, remaining_micro_usd: 700_000, calls_ok: 3, calls_error: 1, input_tokens: 100, output_tokens: 40, zero_retention: true, region: 'eu' }
const CALL = { id: 'abcdef12-0000', caller_id: '11111111-2', stage: 'answer', provider: 'fake', model: 'm1', status: 'ok', input_tokens: 10, output_tokens: 5, cost_micro_usd: 1234, reserved_micro_usd: 2000, error_code: null, fallback_used: false, created_at: '2026-01-01T00:00:00Z', finished_at: null }
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })

function api(over: (url: string) => Response | undefined = () => undefined) {
  const urls: string[] = []
  const f = vi.fn(async (url: string) => {
    urls.push(url)
    const o = over(url)
    if (o) return o
    if (url.includes('/ai/usage')) return json(USAGE)
    if (url.includes('/ai/calls')) return json({ items: [CALL, { ...CALL, id: 'zzzz', stage: '<img src=x onerror=alert(1)>', error_code: 'budget_exceeded', status: 'error' }], total: 2, limit: 50, offset: 0 })
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, urls }
}
const load = (f: typeof fetch) => mount(createElement(AiUsagePage, { projectId: 'p', session: readySession(f) }))

describe('AiUsagePage', () => {
  it('gates without a session and has a single h1', async () => {
    const { f } = api()
    const host = await mount(createElement(AiUsagePage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('ai-usage-no-origin')).not.toBeNull()
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(f).not.toHaveBeenCalled()
  })
  it('shows totals as estimates with exact integer formatting and renders strings as text', async () => {
    const { f } = api()
    const host = await load(f)
    expect(q('usage-estimate-note')?.textContent).toMatch(/estimates/)
    expect(q('usage-spent')?.textContent).toBe('USD 0.250000')
    expect(q('usage-remaining')?.textContent).toBe('USD 0.700000')
    expect(q('usage-calls')?.textContent).toBe('3 / 1')
    expect(qa('calls-row')).toHaveLength(2)
    expect(qa('calls-row')[0].textContent).toContain('0.001234')
    expect(host.querySelector('img')).toBeNull()
    expect(qa('calls-row')[1].textContent).toContain('<img src=x onerror=alert(1)>')
  })
  it('passes the stage and status filters to the route and resets paging', async () => {
    const { f, urls } = api()
    await load(f)
    await setInput(q('calls-stage') as HTMLInputElement, 'answer')
    await setInput(q('calls-status') as HTMLSelectElement, 'error')
    expect(urls.some((u) => /\/ai\/calls\?.*stage=answer/.test(u) && /status=error/.test(u))).toBe(true)
  })
  it('pages with total', async () => {
    const { f, urls } = api((u) => (u.includes('/ai/calls') ? json({ items: [CALL], total: 120 }) : undefined))
    await load(f)
    await click(q('calls-next'))
    expect(urls.some((u) => u.includes('offset=50'))).toBe(true)
  })
  it('shows the role refusal and the missing-block message', async () => {
    const { f } = api((u) => (u.includes('/ai/usage') ? json({ code: 'forbidden', message: 'x' }, 403) : u.includes('/ai/calls') ? json({ detail: 'Not Found' }, 404) : undefined))
    await load(f)
    expect(q('usage-error')?.textContent).toMatch(/role may not/)
    expect(q('calls-error')?.textContent).toMatch(/no AI gateway/)
  })
  it('drops a response that arrives after a newer request (stale fetch)', async () => {
    const first: { release: (r: Response) => void } = { release: () => {} }
    const { f } = api()
    const inner = f as unknown as (u: string, i: RequestInit) => Promise<Response>
    let n = 0
    const slow = vi.fn((u: string, i: RequestInit) => {
      if (!u.includes('/ai/calls')) return inner(u, i)
      n += 1
      if (n === 1) return Promise.resolve(json({ items: [{ ...CALL, id: 'one', stage: 'first' }], total: 1 }))
      if (n === 2) return new Promise<Response>((res) => { first.release = res })
      return Promise.resolve(json({ items: [{ ...CALL, id: 'three', stage: 'newest' }], total: 1 }))
    }) as unknown as typeof fetch
    await load(slow)
    await setInput(q('calls-status') as HTMLSelectElement, 'ok')      // request 2: held
    await setInput(q('calls-status') as HTMLSelectElement, 'error')   // request 3: answers at once
    expect(qa('calls-row')[0].textContent).toContain('newest')
    await act(async () => { first.release(json({ items: [{ ...CALL, id: 'two', stage: 'stale' }], total: 1 })) })
    await flush()
    expect(qa('calls-row')).toHaveLength(1)
    expect(qa('calls-row')[0].textContent).toContain('newest')
    expect(qa('calls-row')[0].textContent).not.toContain('stale')
  })
  it('shows loading while the usage request is pending', async () => {
    const { f } = api()
    const inner = f as unknown as (u: string, i: RequestInit) => Promise<Response>
    const slow = vi.fn((u: string, i: RequestInit) => (u.includes('/ai/usage') ? new Promise<Response>(() => {}) : inner(u, i))) as unknown as typeof fetch
    await load(slow)
    expect(q('usage-loading')).not.toBeNull()
  })
  it('shows empty and unexpected-shape states', async () => {
    const { f } = api((u) => (u.includes('/ai/calls') ? json({ items: [], total: 0 }) : u.includes('/ai/usage') ? json([1]) : undefined))
    await load(f)
    expect(q('calls-empty')).not.toBeNull()
    expect(q('usage-error')).not.toBeNull()
  })
  it('refresh reloads both', async () => {
    const { f, urls } = api()
    await load(f)
    const n = urls.length
    await click(q('usage-refresh'))
    expect(urls.length).toBe(n + 2)
  })
  it('has no axe violations', async () => {
    const { f } = api()
    const host = await load(f)
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
