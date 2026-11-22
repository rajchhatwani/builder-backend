import axe from 'axe-core'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { click, flush, mount, unmount } from '../ai/testUtils'
import { readySession, stubSession } from '../preview/testSession'
import { AppsPage } from './AppsPage'

const TOKEN = 'app_tok_TOPSECRET999'
const SIGN = 'whsec_SIGNSECRET888'
const d = (id: string) => document.querySelector(`[data-testid="${id}"]`) as HTMLElement | null
const da = (id: string) => Array.from(document.querySelectorAll(`[data-testid="${id}"]`)) as HTMLElement[]
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const app = (o: Record<string, unknown>) => ({ name: 'crm', title: 'CRM', scopes: ['order', 'customer'], events: ['order-created'], installed: false, installation_id: null, granted_scopes: [], installed_at: null, ...o })

function server(over: (m: string, url: string, body: Record<string, unknown> | null) => Response | undefined = () => undefined) {
  let installed = false
  const calls: { m: string; url: string; body: Record<string, unknown> | null }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    const body = init.body ? JSON.parse(init.body as string) : null
    calls.push({ m, url, body })
    const o = over(m, url, body)
    if (o) return o
    const path = url.replace('http://gen.test', '')
    if (path === '/platform/apps') return json([installed ? app({ installed: true, installation_id: 'i1', granted_scopes: ['order'], installed_at: '2026-03-01T00:00:00Z' }) : app({}), app({ name: 'bi', title: 'BI', scopes: ['order'], events: [] })])
    if (path === '/platform/apps/crm/install') { installed = true; return json({ installation_id: 'i1', app: 'crm', granted_scopes: body?.scopes, token: TOKEN, signing_secret: SIGN }, 201) }
    if (path === '/platform/apps/crm/uninstall') { installed = false; return json({ installation_id: 'i1', status: 'uninstalled' }) }
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const page = (f: typeof fetch, projectId = 'p') => createElement(AppsPage, { projectId, session: readySession(f) })
const storageEmpty = () => expect(window.localStorage.length + window.sessionStorage.length).toBe(0)

beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear() })
afterEach(() => { vi.restoreAllMocks() })

describe('AppsPage', () => {
  it('has one h1, no skipped level, and no axe violations', async () => {
    const host = await mount(page(server().f))
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    const levels = Array.from(host.querySelectorAll('h1,h2,h3,h4')).map((h) => Number(h.tagName[1]))
    levels.forEach((l, i) => { if (i) expect(l - levels[i - 1]).toBeLessThanOrEqual(1) })
    const r = await axe.run(host, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })
    expect(r.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' | ')}`)).toEqual([])
  })

  it('lists apps with status as icon plus text', async () => {
    await mount(page(server().f))
    expect(da('app-item')).toHaveLength(2)
    expect(da('app-status')[0].textContent).toBe('– Not installed')
  })

  it('shows the session gate when not connected', async () => {
    await mount(createElement(AppsPage, { projectId: 'p', session: stubSession('no-preview') }))
    expect(d('preview-session-none')).not.toBeNull()
    expect(da('app-item')).toHaveLength(0)
  })

  it('403 names api_platform.roles; other errors show the server message', async () => {
    await mount(page(server(() => json({ message: 'no' }, 403)).f))
    expect(d('apps-error')?.textContent).toContain('api_platform.roles')
    unmount()
    await mount(page(server(() => json({ message: 'boom today', details: [] }, 500)).f))
    expect(d('apps-error')?.textContent).toContain('boom today')
  })

  it('installs a chosen subset of scopes and shows token and secret once', async () => {
    const s = server()
    await mount(page(s.f))
    const first = da('app-item')[0]
    await click(first.querySelectorAll('[data-testid="app-scope"]')[1]) // untick customer
    await click(first.querySelector('[data-testid="install"]'))
    const post = s.calls.find((c) => c.url.endsWith('/install'))!
    expect(post.body).toEqual({ scopes: ['order'] })
    const t = d('secret-panel')?.textContent ?? ''
    expect(t).toContain(TOKEN); expect(t).toContain(SIGN)
    expect(da('app-status')[0].textContent).toContain('Installed')
    storageEmpty()
  })

  it('refuses an install with no scopes picked', async () => {
    const s = server()
    await mount(page(s.f))
    const first = da('app-item')[0]
    for (const c of Array.from(first.querySelectorAll('[data-testid="app-scope"]'))) await click(c)
    await click(first.querySelector('[data-testid="install"]'))
    expect(d('apps-action-error')?.textContent).toContain('at least one')
    expect(s.calls.some((c) => c.m === 'POST')).toBe(false)
  })

  it('shows the server message of a refused install and no panel', async () => {
    await mount(page(server((_m, url) => (url.endsWith('/install') ? json({ code: 'x', message: 'already installed', details: [] }, 409) : undefined)).f))
    await click(da('app-item')[0].querySelector('[data-testid="install"]'))
    expect(d('apps-action-error')?.textContent).toContain('already installed')
    expect(d('secret-panel')).toBeNull()
  })

  it('dismiss, unmount and project change all drop the secrets', async () => {
    const s = server()
    await mount(page(s.f))
    await click(da('app-item')[0].querySelector('[data-testid="install"]'))
    expect(document.body.textContent).toContain(TOKEN)
    await click(d('secret-dismiss'))
    expect(document.body.textContent).not.toContain(TOKEN)
    expect(document.body.textContent).not.toContain(SIGN)
    unmount()

    const host = document.createElement('div'); document.body.appendChild(host)
    const root = createRoot(host)
    await act(async () => { root.render(page(s.f, 'p1')) }); await flush()
    await act(async () => { root.render(page(server().f, 'p1')) }); await flush()
    await click(host.querySelector('[data-testid="install"]'))
    expect(host.textContent).toContain(SIGN)
    await act(async () => { root.render(page(s.f, 'p2')) }); await flush()
    expect(host.textContent).not.toContain(SIGN)
    expect(host.textContent).not.toContain(TOKEN)
    await act(async () => { root.render(createElement('div')) }); await flush()
    await act(async () => { root.unmount() }); host.remove()
    storageEmpty()
  })

  it('does not log the secrets', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((k) => vi.spyOn(console, k).mockImplementation(() => undefined))
    await mount(page(server().f))
    await click(da('app-item')[0].querySelector('[data-testid="install"]'))
    const all = spies.flatMap((x) => x.mock.calls).join(' ')
    expect(all).not.toContain(TOKEN); expect(all).not.toContain(SIGN)
  })

  it('uninstall asks first, posts, and refreshes', async () => {
    const s = server()
    await mount(page(s.f))
    await click(da('app-item')[0].querySelector('[data-testid="install"]'))
    await click(d('secret-dismiss'))
    await click(d('uninstall'))
    expect(s.calls.some((c) => c.url.endsWith('/uninstall'))).toBe(false)
    await click(d('uninstall-confirm'))
    expect(s.calls.some((c) => c.m === 'POST' && c.url.endsWith('/platform/apps/crm/uninstall'))).toBe(true)
    expect(d('apps-note')?.textContent).toBe('CRM uninstalled.')
    expect(da('app-status')[0].textContent).toBe('– Not installed')
  })

  it('ignores a stale apps answer after the session changes', async () => {
    let release!: (r: Response) => void
    const slow = vi.fn(() => new Promise<Response>((r) => { release = r })) as unknown as typeof fetch
    const host = document.createElement('div'); document.body.appendChild(host)
    const root = createRoot(host)
    await act(async () => { root.render(createElement(AppsPage, { projectId: 'p', session: readySession(slow) })) }); await flush()
    await act(async () => { root.render(createElement(AppsPage, { projectId: 'p', session: readySession(server().f) })) }); await flush()
    await act(async () => { release(json([app({ name: 'ghost', title: 'Ghost' })])) }); await flush()
    expect(host.textContent).toContain('CRM'); expect(host.textContent).not.toContain('Ghost')
    await act(async () => { root.unmount() }); host.remove()
  })
})
