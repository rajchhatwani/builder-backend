import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { DataBrowser } from './DataBrowser'
import { click, mount, q, qa } from './testUtils'

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const OPENAPI = { paths: { '/invoices': { get: {} }, '/people': { get: {} } } }
function fetcher(over: (url: string) => Response | undefined = () => undefined) {
  const calls: Array<{ url: string; init: RequestInit }> = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init })
    return over(url) ?? json(url.endsWith('/openapi.json') ? OPENAPI : { items: [{ id: 1, name: 'Acme' }], total: 1 })
  }) as unknown as typeof fetch
  return { f, calls }
}

describe('DataBrowser', () => {
  it('asks for a token and fetches nothing without one', async () => {
    const { f } = fetcher()
    await mount(createElement(DataBrowser, { previewId: 'pv', token: '', doFetch: f }))
    expect(q('data-notoken')?.textContent).toMatch(/Add a preview token/)
    expect(f).not.toHaveBeenCalled()
  })
  it('sends GET with the token header and no credentials, and renders cell text', async () => {
    const { f, calls } = fetcher()
    await mount(createElement(DataBrowser, { previewId: 'pv', token: 'tok', doFetch: f }))
    expect(calls.every((c) => c.init.method === 'GET' && c.init.credentials === 'omit')).toBe(true)
    expect(calls[0].init.headers).toMatchObject({ 'X-Preview-Token': 'tok' })
    expect(qa('data-row')[0].textContent).toBe('1Acme')
    expect(q('data-page')?.textContent).toBe('Page 1 of 1')
    expect(q('data-next')).toHaveProperty('disabled', true)
    expect(q('data-prev')).toHaveProperty('disabled', true)
  })
  it('switches entity and loads that entity list', async () => {
    const { f, calls } = fetcher()
    await mount(createElement(DataBrowser, { previewId: 'pv', token: 'tok', doFetch: f }))
    const sel = q('data-entity') as HTMLSelectElement
    expect(Array.from(sel.options).map((o) => o.textContent)).toEqual(expect.arrayContaining(['invoices', 'people']))
    await import('react').then(({ act }) => act(async () => { sel.value = sel.options[1].value; sel.dispatchEvent(new Event('change', { bubbles: true })) }))
    expect(calls.some((c) => c.url.includes(sel.options[1].value))).toBe(true)
  })
  it.each([[410, /has ended/], [401, /token was not accepted/], [429, /Too many/], [500, /answered 500/]])('explains a %i from the preview', async (status, msg) => {
    const { f } = fetcher((u) => (u.endsWith('/openapi.json') ? new Response('', { status }) : undefined))
    await mount(createElement(DataBrowser, { previewId: 'pv', token: 'tok', doFetch: f }))
    expect(q('data-error')?.textContent).toMatch(msg)
  })
  it('Retry reloads and recovers; a rows error is not erased by the other effect', async () => {
    let fail = true
    const { f } = fetcher((u) => (fail && !u.endsWith('/openapi.json') ? new Response('', { status: 500 }) : undefined))
    await mount(createElement(DataBrowser, { previewId: 'pv', token: 'tok', doFetch: f }))
    expect(q('data-error')?.textContent).toMatch(/answered 500/)
    fail = false
    await click(q('data-error')!.querySelector('button'))
    expect(q('data-error')).toBeNull()
    expect(qa('data-row')).toHaveLength(1)
  })
  it('says so when the endpoint is not a list', async () => {
    const { f } = fetcher((u) => (u.endsWith('/openapi.json') ? undefined : json('nope')))
    await mount(createElement(DataBrowser, { previewId: 'pv', token: 'tok', doFetch: f }))
    expect(q('data-error')?.textContent).toMatch(/does not return a list/)
  })
})
