import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PreviewSession } from '../preview/previewSession'
import { stubSession } from '../preview/testSession'
import { WorkbenchDrawer } from './WorkbenchDrawer'

const apiMock = vi.hoisted(() => ({ listPreviews: vi.fn(async () => []) }))
vi.mock('../../api/client', () => ({ api: { getBehaviorRoles: async () => ({ roles: [] }), listPreviews: apiMock.listPreviews } }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
afterEach(() => { vi.unstubAllGlobals(); apiMock.listPreviews.mockClear() })

const BASE = 'http://p.test/previews/abc'
const okDoc = JSON.stringify({ paths: { '/a': { get: {} } } })
const ready = (request: PreviewSession['request'], over: Partial<PreviewSession> = {}) =>
  stubSession('ready', { base: BASE, previewState: 'running', request, ...over })

async function mount(props: { open: boolean; session: PreviewSession; onClose?: () => void }) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  await act(async () => root.render(createElement(WorkbenchDrawer, { projectId: 'p', onClose: props.onClose ?? (() => {}), ...props })))
  await flush()
  return { host, root }
}

describe('WorkbenchDrawer states', () => {
  it('renders nothing until first opened; asks for no preview and fetches nothing', async () => {
    const f = vi.fn(); vi.stubGlobal('fetch', f)
    const request = vi.fn(async () => ({ status: 200, text: okDoc }))
    const { host } = await mount({ open: false, session: ready(request) })
    expect(host.querySelector('[data-testid=workbench]')).toBeNull()
    expect(request).not.toHaveBeenCalled()
    expect(f).not.toHaveBeenCalled()
  })
  it('own session stays idle (no preview lookup, no fetch) while the drawer was never opened', async () => {
    const f = vi.fn(); vi.stubGlobal('fetch', f)
    const host = document.createElement('div'); document.body.append(host)
    await act(async () => createRoot(host).render(createElement(WorkbenchDrawer, { projectId: 'p', open: false, onClose: () => {} })))
    await flush()
    expect(apiMock.listPreviews).not.toHaveBeenCalled()
    expect(f).not.toHaveBeenCalled()
  })
  it('empty state when no preview origin is configured; makes no request', async () => {
    const f = vi.fn(); vi.stubGlobal('fetch', f)
    const request = vi.fn()
    const { host } = await mount({ open: true, session: stubSession('no-origin', { request }) })
    expect(host.querySelector('[data-testid=wb-no-origin]')).not.toBeNull()
    expect(request).not.toHaveBeenCalled()
    expect(f).not.toHaveBeenCalled()
  })
  it('shows the session waiting message while the preview is starting; no openapi call', async () => {
    const request = vi.fn()
    const { host } = await mount({ open: true, session: stubSession('starting', { base: BASE, request }) })
    expect(host.querySelector('[data-testid=preview-session-wait]')!.textContent).toContain('The preview is starting')
    expect(host.textContent).not.toContain('Could not reach the preview API')
    expect(request).not.toHaveBeenCalled()
  })
  it('offers to start a preview when none exists', async () => {
    const start = vi.fn(async () => {})
    const { host } = await mount({ open: true, session: stubSession('no-preview', { start }) })
    await act(async () => (host.querySelector('[data-testid=preview-start]') as HTMLButtonElement).click())
    expect(start).toHaveBeenCalled()
  })
  it('error state with retry when the preview API is down', async () => {
    const request = vi.fn(async () => { throw new Error('Could not reach the preview API (network error, CORS or a redirect)') })
    const { host } = await mount({ open: true, session: ready(request) })
    expect(host.querySelector('[data-testid=wb-error]')!.textContent).toContain('Could not reach the preview API')
    expect(host.querySelector('[data-testid=wb-error] button')!.textContent).toBe('Retry')
  })
  it('loads openapi from <base>/openapi.json through the session (preview token), never the bare origin; Escape closes', async () => {
    const f = vi.fn(async () => new Response(okDoc))
    vi.stubGlobal('fetch', f)
    const request = vi.fn(async (_m: string, _p: string) => ({ status: 200, text: okDoc }))
    const onClose = vi.fn()
    const { host } = await mount({ open: true, session: ready(request), onClose })
    expect(request.mock.calls[0].slice(0, 2)).toEqual(['GET', '/openapi.json'])
    expect(f).not.toHaveBeenCalled() // nothing goes around the session (bare origin)
    expect(host.querySelector('[data-testid=wb-console]')).not.toBeNull()
    await act(async () => { host.querySelector('[data-testid=workbench]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(onClose).toHaveBeenCalled()
  })
  it('rejects a non-OpenAPI answer', async () => {
    const { host } = await mount({ open: true, session: ready(async () => ({ status: 200, text: '{"hello":1}' })) })
    expect(host.querySelector('[data-testid=wb-error]')!.textContent).toContain('not an OpenAPI')
  })
})
