import axe from 'axe-core'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../../api/client'
import { click, flush, mount, setInput, unmount } from '../ai/testUtils'
import { readySession, stubSession } from '../preview/testSession'
import { ApiKeysPage } from './ApiKeysPage'

const role = vi.hoisted(() => ({ value: 'editor' as string | null }))
vi.mock('../ai/useMyRole', () => ({ useMyRole: () => role.value }))

const BLOCK = { enabled: true, roles: ['admin'], entities: [{ entity: 'order', fields: ['id', 'total'], sandbox: true }], rate_limit: '60/minute', sandbox_rate_limit: '20/minute', key_ttl_days: 90, apps: [], extra_key: 1 }
const CAT = { entities: [{ entity: 'order', plural_path: 'orders', fields: ['id', 'total'], sandbox: true }, { entity: 'customer', plural_path: 'customers', fields: ['id'], sandbox: false }], rate_limit: '60/minute', sandbox_rate_limit: '20/minute', key_ttl_days: 90 }
const key = (o: Record<string, unknown>) => ({ id: 'k1', name: 'Zapier', prefix: 'pk_abc', kind: 'key', app: null, environment: 'prod', scopes: ['order'], created_at: '2026-03-01T00:00:00Z', expires_at: '2026-06-01T00:00:00Z', revoked_at: null, last_used_at: null, status: 'active', ...o })
const SECRET = 'sk_live_SUPERSECRETVALUE123'
const d = (id: string) => document.querySelector(`[data-testid="${id}"]`) as HTMLElement | null
const da = (id: string) => Array.from(document.querySelectorAll(`[data-testid="${id}"]`)) as HTMLElement[]
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })

function server(over: (m: string, url: string, body: Record<string, unknown> | null) => Response | undefined = () => undefined) {
  const keys = [key({}), key({ id: 'k2', name: 'Old', status: 'revoked', revoked_at: '2026-03-02T00:00:00Z' })]
  const calls: { m: string; url: string; body: Record<string, unknown> | null }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    const body = init.body ? JSON.parse(init.body as string) : null
    calls.push({ m, url, body })
    const o = over(m, url, body)
    if (o) return o
    const path = url.replace('http://gen.test', '')
    if (path === '/platform/catalogue') return json(CAT)
    if (path === '/platform/keys' && m === 'GET') return json(keys)
    if (path === '/platform/keys' && m === 'POST') {
      const made = { id: 'k3', name: body?.name, prefix: 'pk_new', environment: body?.environment, scopes: body?.scopes, expires_at: '2026-07-01T00:00:00Z', created_at: '', key: SECRET }
      keys.push(key({ id: 'k3', name: String(body?.name), prefix: 'pk_new' }))
      return json(made, 201)
    }
    if (path.endsWith('/revoke')) { keys[0] = key({ status: 'revoked' }); return json(keys[0]) }
    if (path.startsWith('/platform/audit')) return json([{ id: 'a1', at: '2026-03-01T10:00:00Z', actor: 'admin@x.io', action: 'key.create', target: 'pk_abc', detail: { scopes: ['order'] } }])
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}

let getBlock: ReturnType<typeof vi.spyOn>
let putBlock: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  role.value = 'editor'
  getBlock = vi.spyOn(api, 'getBlock').mockResolvedValue({ api_platform: BLOCK, version: 3 })
  putBlock = vi.spyOn(api, 'putBlock').mockImplementation(async (_p: string, _n: string, body: Record<string, unknown>) => ({ api_platform: body.api_platform, version: 4 }))
  vi.spyOn(api, 'getBehaviorIssues').mockResolvedValue({ issues: [] })
  window.localStorage.clear(); window.sessionStorage.clear()
})
afterEach(() => { vi.restoreAllMocks() })

const page = (f: typeof fetch, projectId = 'p') => createElement(ApiKeysPage, { projectId, session: readySession(f) })
const input = (id: string) => document.getElementById(id) as HTMLInputElement
const storageEmpty = () => expect(window.localStorage.length + window.sessionStorage.length).toBe(0)
const create = async (name = 'My key') => {
  await setInput(input('key-name'), name)
  await click(da('key-scope')[0])
  await click(d('key-create'))
}

describe('ApiKeysPage structure', () => {
  it('has one h1 and no skipped heading level, headings Settings / Keys / Audit', async () => {
    const host = await mount(page(server().f))
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    const hs = Array.from(host.querySelectorAll('h1,h2,h3,h4'))
    const levels = hs.map((h) => Number(h.tagName[1]))
    levels.forEach((l, i) => { if (i) expect(l - levels[i - 1]).toBeLessThanOrEqual(1) })
    expect(Array.from(host.querySelectorAll('h2')).map((h) => h.textContent)).toEqual(['Settings', 'Keys', 'Audit'])
  })

  it('has no axe violations', async () => {
    const host = await mount(page(server().f))
    const r = await axe.run(host, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })
    expect(r.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' | ')}`)).toEqual([])
  })

  it('shows the key list with status as icon plus text, prefix, environment, never-used', async () => {
    await mount(page(server().f))
    expect(da('key-row')).toHaveLength(2)
    expect(da('key-status').map((c) => c.textContent)).toEqual(['✓ Active', '✗ Revoked'])
    expect(da('key-row')[0].textContent).toContain('pk_abc')
    expect(da('key-row')[0].textContent).toContain('Never')
    expect(da('revoke')).toHaveLength(1) // only the active key can be revoked
    expect(da('audit-row')).toHaveLength(1)
  })

  it('shows the session gate instead of keys when the preview is not connected', async () => {
    const host = await mount(createElement(ApiKeysPage, { projectId: 'p', session: stubSession('needs-signin') }))
    expect(d('preview-signin')).not.toBeNull()
    expect(d('keys-table')).toBeNull()
    expect(host.querySelectorAll('h2')).toHaveLength(3)
  })

  it('403 names api_platform.roles and the preview account', async () => {
    await mount(page(server((_m, url) => (url.endsWith('/platform/catalogue') ? json({ message: 'no' }, 403) : undefined)).f))
    const t = d('keys-error')?.textContent ?? ''
    expect(t).toContain('api_platform.roles')
    expect(t).toContain('preview account')
    expect(d('key-form')).toBeNull()
  })

  it('other errors show the server message and retry works', async () => {
    let fail = true
    const s = server((_m, url) => (fail && url.endsWith('/platform/catalogue') ? json({ code: 'x', message: 'database is down', details: [] }, 500) : undefined))
    await mount(page(s.f))
    expect(d('keys-error')?.textContent).toContain('database is down')
    fail = false
    await click(d('keys-error')!.querySelector('button'))
    expect(d('key-form')).not.toBeNull()
  })

  it('a 200 that is not the catalogue is an error', async () => {
    await mount(page(server((_m, url) => (url.endsWith('/platform/catalogue') ? json({ hello: 1 }) : undefined)).f))
    expect(d('keys-error')?.textContent).toContain('not the API platform catalogue')
  })
})

describe('ApiKeysPage keys', () => {
  it('create posts name, scopes, environment, ttl and shows the key once', async () => {
    const s = server()
    await mount(page(s.f))
    await setInput(document.getElementById('key-env') as unknown as HTMLSelectElement, 'sandbox')
    await setInput(input('key-ttl'), '30')
    await create('CI key')
    const post = s.calls.find((c) => c.m === 'POST' && c.url.endsWith('/platform/keys'))!
    expect(post.body).toEqual({ name: 'CI key', scopes: ['order'], environment: 'sandbox', ttl_days: 30 })
    expect(d('secret-panel')?.textContent).toContain(SECRET)
    expect(da('key-row')).toHaveLength(3)
    expect(document.body.textContent).toContain(SECRET)
    expect(da('secret-value')).toHaveLength(1)
    storageEmpty()
    // the list itself never carries the secret
    expect(d('keys-table')?.textContent).not.toContain(SECRET)
  })

  it('dismiss removes the secret from the page', async () => {
    await mount(page(server().f))
    await create()
    expect(document.body.textContent).toContain(SECRET)
    await click(d('secret-dismiss'))
    expect(d('secret-panel')).toBeNull()
    expect(document.body.textContent).not.toContain(SECRET)
    storageEmpty()
  })

  it('unmount clears it', async () => {
    await mount(page(server().f))
    await create()
    unmount()
    expect(document.body.textContent).not.toContain(SECRET)
    storageEmpty()
  })

  it('a project change clears it', async () => {
    const s = server()
    const host = document.createElement('div'); document.body.appendChild(host)
    const root = createRoot(host)
    await act(async () => { root.render(page(s.f, 'p1')) }); await flush()
    await create()
    expect(host.textContent).toContain(SECRET)
    await act(async () => { root.render(page(s.f, 'p2')) }); await flush()
    expect(host.textContent).not.toContain(SECRET)
    await act(async () => { root.unmount() }); host.remove()
  })

  it('does not log the secret', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((k) => vi.spyOn(console, k).mockImplementation(() => undefined))
    await mount(page(server().f))
    await create()
    expect(spies.flatMap((s) => s.mock.calls).join(' ')).not.toContain(SECRET)
  })

  it('copy button copies and says so; a refused clipboard says to copy by hand', async () => {
    const write = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true })
    await mount(page(server().f))
    await create()
    await click(d('secret-panel')!.querySelector('button.outline'))
    expect(write).toHaveBeenCalledWith(SECRET)
    expect(d('secret-copied')?.textContent).toContain('copied')
    write.mockRejectedValueOnce(new Error('denied'))
    await click(d('secret-panel')!.querySelector('button.outline'))
    expect(d('secret-copied')?.textContent).toContain('by hand')
  })

  it('checks the form before posting', async () => {
    const s = server()
    await mount(page(s.f))
    await click(d('key-create'))
    expect(d('key-form-error')?.textContent).toContain('name')
    await setInput(input('key-name'), 'n')
    await click(d('key-create'))
    expect(d('key-form-error')?.textContent).toContain('at least one entity')
    await click(da('key-scope')[0]); await setInput(input('key-ttl'), '999')
    await click(d('key-create'))
    expect(d('key-form-error')?.textContent).toContain('1 to 90')
    expect(s.calls.some((c) => c.m === 'POST')).toBe(false)
  })

  it('a refused create shows the server message and no secret panel', async () => {
    await mount(page(server((m, url) => (m === 'POST' && url.endsWith('/platform/keys') ? json({ code: 'bad', message: 'scope order is not public for sandbox', details: [] }, 422) : undefined)).f))
    await create()
    expect(d('key-form-error')?.textContent).toContain('not public for sandbox')
    expect(d('secret-panel')).toBeNull()
  })

  it('a 403 on create names api_platform.roles', async () => {
    await mount(page(server((m, url) => (m === 'POST' && url.endsWith('/platform/keys') ? json({ message: 'no' }, 403) : undefined)).f))
    await create()
    expect(d('key-form-error')?.textContent).toContain('api_platform.roles')
  })

  it('revoke asks first, then posts and refreshes', async () => {
    const s = server()
    await mount(page(s.f))
    await click(d('revoke'))
    expect(s.calls.some((c) => c.url.endsWith('/revoke'))).toBe(false)
    await click(d('revoke-confirm'))
    expect(s.calls.some((c) => c.m === 'POST' && c.url.endsWith('/platform/keys/k1/revoke'))).toBe(true)
    expect(d('key-note')?.textContent).toBe('Key revoked.')
    expect(da('key-status').map((c) => c.textContent)).toEqual(['✗ Revoked', '✗ Revoked'])
  })

  it('shows a revoke error', async () => {
    await mount(page(server((_m, url) => (url.endsWith('/revoke') ? json({ code: 'x', message: 'already gone', details: [] }, 409) : undefined)).f))
    await click(d('revoke')); await click(d('revoke-confirm'))
    expect(d('key-action-error')?.textContent).toContain('already gone')
  })

  it('ignores a stale catalogue answer after the session changes', async () => {
    let release!: (r: Response) => void
    const slow = vi.fn(() => new Promise<Response>((r) => { release = r })) as unknown as typeof fetch
    const s2 = server()
    const host = document.createElement('div'); document.body.appendChild(host)
    const root = createRoot(host)
    await act(async () => { root.render(createElement(ApiKeysPage, { projectId: 'p', session: readySession(slow) })) }); await flush()
    await act(async () => { root.render(createElement(ApiKeysPage, { projectId: 'p', session: readySession(s2.f) })) }); await flush()
    await act(async () => { release(json({ entities: [{ entity: 'stale', fields: [], sandbox: false }], rate_limit: '', sandbox_rate_limit: '', key_ttl_days: 5 })) }); await flush()
    expect(host.textContent).toContain('customer')
    expect(host.textContent).not.toContain('stale')
    await act(async () => { root.unmount() }); host.remove()
  })
})

describe('ApiKeysPage settings', () => {
  it('loads the block and saves the whole block with expected_version, carrying unknown keys', async () => {
    await mount(page(server().f))
    await setInput(input('ap-ttl'), '30')
    await click(d('settings-save'))
    expect(putBlock).toHaveBeenCalledTimes(1)
    const [pid, name, body] = putBlock.mock.calls[0] as [string, string, { api_platform: Record<string, unknown>; expected_version: number }]
    expect(pid).toBe('p'); expect(name).toBe('api_platform'); expect(body.expected_version).toBe(3)
    expect(body.api_platform).toMatchObject({ enabled: true, roles: ['admin'], key_ttl_days: 30, extra_key: 1, rate_limit: '60/minute' })
    expect(d('settings-note')?.textContent).toBe('Saved (version 4).')
  })

  it('refuses a bad rate limit and ttl client-side', async () => {
    await mount(page(server().f))
    await setInput(input('ap-rate'), '60 per minute')
    await setInput(input('ap-ttl'), '400')
    await click(d('settings-save'))
    expect(putBlock).not.toHaveBeenCalled()
    expect(da('field-error').length).toBe(2)
  })

  it('adds entity and app rows and sends them', async () => {
    await mount(page(server().f))
    await click(d('add-entity'))
    const rows = da('entity-row')
    expect(rows).toHaveLength(2)
    const idEnt = rows[1].querySelectorAll('input')[0] as HTMLInputElement
    await setInput(idEnt, 'customer')
    const fieldsInput = rows[1].querySelectorAll('input')[1] as HTMLInputElement
    await setInput(fieldsInput, 'id, name')
    await click(d('add-app'))
    const app = da('app-row')[0].querySelectorAll('input')
    await setInput(app[0] as HTMLInputElement, 'crm'); await setInput(app[2] as HTMLInputElement, 'order')
    await click(d('settings-save'))
    const body = (putBlock.mock.calls[0] as unknown[])[2] as { api_platform: { entities: unknown[]; apps: unknown[] } }
    expect(body.api_platform.entities[1]).toEqual({ entity: 'customer', fields: ['id', 'name'], sandbox: false })
    expect(body.api_platform.apps).toEqual([{ name: 'crm', title: '', scopes: ['order'], events: [] }])
  })

  it('409 shows the conflict banner; 422 shows details', async () => {
    putBlock.mockRejectedValueOnce(new ApiError(409, { code: 'conflict', message: 'stale', details: [] }))
    await mount(page(server().f))
    await setInput(input('ap-ttl'), '31'); await click(d('settings-save'))
    expect(d('conflict')).not.toBeNull()
    putBlock.mockRejectedValueOnce(new ApiError(422, { code: 'invalid', message: 'Spec invalid', details: [{ path: 'api_platform.roles[0]', message: "no auth role named 'x'" }] }))
    await setInput(input('ap-ttl'), '32'); await click(d('settings-save'))
    expect(d('settings-save-error')?.textContent).toBe('Spec invalid')
    expect(d('server-issues')?.textContent).toContain("api_platform.roles[0]: no auth role named 'x'")
  })

  it('shows a load error with retry', async () => {
    getBlock.mockRejectedValueOnce(new Error('boom'))
    await mount(page(server().f))
    expect(d('settings-error')?.textContent).toContain('boom')
    await click(d('settings-error')!.querySelector('button'))
    expect(input('ap-ttl')).not.toBeNull()
  })

  it('viewer sees read-only settings with no save or add buttons', async () => {
    role.value = 'viewer'
    await mount(page(server().f))
    expect(d('settings-readonly')).not.toBeNull()
    expect(input('ap-ttl').disabled).toBe(true)
    expect(d('settings-save')).toBeNull(); expect(d('add-entity')).toBeNull(); expect(d('add-app')).toBeNull()
  })

  it('ignores a stale settings answer after a project change', async () => {
    let first!: (v: unknown) => void
    getBlock.mockImplementationOnce(() => new Promise((r) => { first = r }))
    const s = server()
    const host = document.createElement('div'); document.body.appendChild(host)
    const root = createRoot(host)
    await act(async () => { root.render(page(s.f, 'p1')) }); await flush()
    await act(async () => { root.render(page(s.f, 'p2')) }); await flush()
    await act(async () => { first({ api_platform: { ...BLOCK, key_ttl_days: 11 }, version: 9 }) }); await flush()
    expect(input('ap-ttl').value).toBe('90')
    await act(async () => { root.unmount() }); host.remove()
  })
})
