import axe from 'axe-core'
import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { act } from 'react'
import { click, flush, mount, q, qa, setInput, typeInto } from '../ai/testUtils'
import { KnowledgePage } from './KnowledgePage'

const EVIL = '<script>alert(1)</script><img src=x onerror=alert(2)>'
const SRC = { id: 's1', title: 'Handbook', allowed_roles: ['admin'], owner_only: false, owner_id: 'abcdef123', chunk_count: 3, created_at: '2026-01-01' }
const HIT = { source_id: 's1', chunk_id: 'c1', title: 'Handbook', text: EVIL, position: 0, score_bp: 8750 }
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })

function api(over: (m: string, url: string) => Response | undefined = () => undefined) {
  const calls: { m: string; url: string; body?: string }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    calls.push({ m, url, body: init.body as string | undefined })
    const o = over(m, url)
    if (o) return o
    if (url.includes('/search')) return json({ hits: [HIT] })
    if (url.includes('/ask')) return json({ answer: EVIL, grounded: true, citations: [{ source_id: 's1', chunk_id: 'c1', title: 'Handbook', quote: EVIL, score_bp: 9000 }], call_id: null })
    if (m === 'DELETE') return new Response(null, { status: 204 })
    if (m === 'POST') return json(SRC, 201)
    if (url.includes('/sources')) return json({ items: [SRC], total: 1 })
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const load = (f: typeof fetch) => mount(createElement(KnowledgePage, { projectId: 'p', session: readySession(f) }))

describe('KnowledgePage', () => {
  it('gates without a session and has a single h1', async () => {
    const host = await mount(createElement(KnowledgePage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('knowledge-no-origin')).not.toBeNull()
    expect(host.querySelectorAll('h1')).toHaveLength(1)
  })
  it('lists sources, empty and error states', async () => {
    const { f } = api()
    await load(f)
    expect(qa('source-row')).toHaveLength(1)
  })
  it('shows the empty state', async () => {
    const { f } = api((m, u) => (m === 'GET' && u.includes('/sources') ? json({ items: [], total: 0 }) : undefined))
    await load(f)
    expect(q('sources-empty')).not.toBeNull()
  })
  it('shows the missing-block message (404) and a loading state', async () => {
    const { f } = api((_m, u) => (u.includes('/sources') ? json({ detail: 'Not Found' }, 404) : undefined))
    await load(f)
    expect(q('sources-error')?.textContent).toMatch(/no knowledge library/)
    const b = api()
    const inner = b.f as unknown as (u: string, i: RequestInit) => Promise<Response>
    const slow = vi.fn((u: string, i: RequestInit) => (u.includes('/sources') ? new Promise<Response>(() => {}) : inner(u, i))) as unknown as typeof fetch
    await load(slow)
    expect(q('sources-loading')).not.toBeNull()
  })
  it('shows the role refusal', async () => {
    const { f } = api((_m, u) => (u.includes('/sources') ? json({ code: 'forbidden', message: 'x' }, 403) : undefined))
    await load(f)
    expect(q('sources-error')?.textContent).toMatch(/role may not/)
  })
  it('creates a source once even on a double click, with allowed roles', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('source-title') as HTMLInputElement, 'Policy')
    await typeInto(q('source-text') as HTMLTextAreaElement, 'hello')
    await setInput(q('source-roles') as HTMLInputElement, 'admin, staff')
    const b = q('source-create')!
    await act(async () => { b.click(); b.click() })
    await flush()
    const posts = calls.filter((c) => c.m === 'POST')
    expect(posts).toHaveLength(1)
    expect(JSON.parse(posts[0].body!)).toEqual({ title: 'Policy', text: 'hello', allowed_roles: ['admin', 'staff'] })
    expect(q('source-notice')?.textContent).toBe('Source added.')
  })
  it('validates locally and shows API errors', async () => {
    const { f, calls } = api((m) => (m === 'POST' ? json({ code: 'validation_error', message: 'Text is too long' }, 422) : undefined))
    await load(f)
    await click(q('source-create'))
    expect(q('source-create-error')?.textContent).toMatch(/title/)
    expect(calls.some((c) => c.m === 'POST')).toBe(false)
    await setInput(q('source-title') as HTMLInputElement, 'T')
    await typeInto(q('source-text') as HTMLTextAreaElement, 'x')
    await click(q('source-create'))
    expect(q('source-create-error')?.textContent).toMatch(/who may see/)
    expect(calls.some((c) => c.m === 'POST')).toBe(false)
    await click(q('source-owner'))
    await click(q('source-create'))
    expect(q('source-create-error')?.textContent).toBe('Text is too long')
  })
  it('deletes only after confirmation', async () => {
    const { f, calls } = api()
    await load(f)
    await click(q('source-delete'))
    expect(q('source-confirm')?.textContent).toMatch(/cannot be undone/)
    expect(calls.some((c) => c.m === 'DELETE')).toBe(false)
    await click(q('source-delete-yes'))
    expect(calls.filter((c) => c.m === 'DELETE')).toHaveLength(1)
    expect(q('source-notice')?.textContent).toBe('Source deleted.')
  })
  it('shows a delete refusal', async () => {
    const { f } = api((m) => (m === 'DELETE' ? json({ code: 'forbidden', message: 'x' }, 403) : undefined))
    await load(f)
    await click(q('source-delete'))
    await click(q('source-delete-yes'))
    expect(q('source-delete-error')?.textContent).toMatch(/role may not/)
  })
  it('renders search hits and answers as plain text, never HTML', async () => {
    const { f, calls } = api()
    const host = await load(f)
    await setInput(q('search-query') as HTMLInputElement, 'leave')
    await click(q('search-run'))
    expect(JSON.parse(calls.find((c) => c.url.includes('/search'))!.body!)).toEqual({ query: 'leave', limit: 5 })
    expect(q('search-hit')?.textContent).toContain('score 87.5%')
    expect(q('search-hit')?.textContent).toContain(EVIL)
    await setInput(q('ask-question') as HTMLInputElement, 'how many days?')
    await click(q('ask-run'))
    expect(q('ask-answer')?.textContent).toBe(EVIL)
    expect(qa('ask-citation')).toHaveLength(1)
    expect(host.querySelector('script, img')).toBeNull()
  })
  it('blocks a second search while one is running and shows the answer when it lands', async () => {
    let release: (r: Response) => void = () => {}
    const { f } = api()
    const inner = f as unknown as (u: string, i: RequestInit) => Promise<Response>
    const slow = vi.fn((url: string, init: RequestInit) => (url.includes('/search') ? new Promise<Response>((res) => { release = res }) : inner(url, init))) as unknown as typeof fetch
    await load(slow)
    await setInput(q('search-query') as HTMLInputElement, 'a')
    await act(async () => { q('search-run')!.click(); q('search-run')!.click() })
    expect(q('search-loading')).not.toBeNull()
    expect((q('search-run') as HTMLButtonElement).disabled).toBe(true)
    expect((slow as unknown as { mock: { calls: string[][] } }).mock.calls.filter((c) => c[0].includes('/search'))).toHaveLength(1)
    await act(async () => { release(json({ hits: [] })) })
    await flush()
    expect(q('search-empty')).not.toBeNull()
  })
  it('shows search and ask errors', async () => {
    const { f } = api((m, u) => (m === 'POST' && u.includes('/ask') ? json({ code: 'budget_exceeded', message: 'x' }, 402) : m === 'POST' && u.includes('/search') ? json({ code: 'forbidden' }, 403) : undefined))
    await load(f)
    await setInput(q('search-query') as HTMLInputElement, 'a')
    await click(q('search-run'))
    expect(q('search-error')?.textContent).toMatch(/role may not/)
    await setInput(q('ask-question') as HTMLInputElement, 'a')
    await click(q('ask-run'))
    expect(q('ask-error')?.textContent).toMatch(/budget/)
  })
  it('has no axe violations', async () => {
    const { f } = api()
    const host = await load(f)
    await setInput(q('search-query') as HTMLInputElement, 'leave')
    await click(q('search-run'))
    await click(q('source-delete'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
