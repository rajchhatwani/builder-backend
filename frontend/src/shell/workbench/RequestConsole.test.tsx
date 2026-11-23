import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RequestConsole } from './RequestConsole'
import { sendRequest } from './sendRequest'

vi.mock('../../api/client', () => ({
  api: { getBehaviorRoles: async () => ({ roles: [{ name: 'clerk', label: 'Clerk' }] }) },
}))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const doc = { paths: { '/ping': { get: { summary: 'Ping' } } } }
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear() })

describe('RequestConsole', () => {
  it('sends as a role, never stores the token, redacts history, renders response as text', async () => {
    const fetchSpy = vi.fn(async (_u: string, _i: RequestInit) => new Response('<b id="x">hi</b>', { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)
    // the real hook's request, with a fixed preview token: URLs are <base><path>, the preview token is always sent
    const session = { base: 'http://p.test/previews/abc', request: (m: string, path: string, body?: unknown, o?: { bearer?: string | null }) =>
      sendRequest({ url: `http://p.test/previews/abc${path}`, origin: 'http://p.test', method: m, body: body === undefined ? undefined : JSON.stringify(body), previewToken: 'PT-1', bearer: o?.bearer ?? undefined }, fetchSpy as unknown as typeof fetch) }
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    await act(async () => root.render(createElement(RequestConsole, { projectId: 'p', session, doc })))
    await flush()
    const role = host.querySelector('#wb-role') as HTMLSelectElement
    expect([...role.options].map((o) => o.value)).toEqual(['', 'clerk'])
    const set = (el: HTMLSelectElement | HTMLInputElement, v: string) => {
      const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype
      Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, v)
      el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
    }
    await act(async () => set(role, 'clerk'))
    const tok = host.querySelector('#wb-token') as HTMLInputElement
    expect(tok.type).toBe('password')
    await act(async () => set(tok, 'TOPSECRET-123'))
    await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
    await flush()
    const calls = fetchSpy.mock.calls as unknown as [string, RequestInit][]
    expect(calls[0][0]).toBe('http://p.test/previews/abc/ping')
    expect((calls[0][1].headers as Record<string, string>)['X-Preview-Token']).toBe('PT-1')
    expect((calls[0][1].headers as Record<string, string>).Authorization).toBe('Bearer TOPSECRET-123')
    // response is text, not DOM
    expect(host.querySelector('#x')).toBeNull()
    expect(host.querySelector('[data-testid=wb-response-body]')!.textContent).toBe('<b id="x">hi</b>')
    // history shows the call without the token
    const hist = host.querySelector('[data-testid=wb-history]')!.textContent!
    expect(hist).toContain('GET /ping as clerk: 200')
    expect(host.querySelector('.wb-history')!.innerHTML).not.toContain('TOPSECRET-123')
    expect(host.querySelector('.wb-response')!.innerHTML).not.toContain('TOPSECRET-123')
    // nothing in browser storage
    expect(JSON.stringify({ ...localStorage })).not.toContain('TOPSECRET')
    expect(JSON.stringify({ ...sessionStorage })).not.toContain('TOPSECRET')
    await act(async () => root.unmount())
    host.remove()
  })
})
