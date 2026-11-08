import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WorkbenchDrawer } from './WorkbenchDrawer'

vi.mock('../../api/client', () => ({ api: { getBehaviorRoles: async () => ({ roles: [] }) } }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
afterEach(() => vi.unstubAllGlobals())

async function mount(props: { open: boolean; origin: string | null; onClose?: () => void }) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  await act(async () => root.render(createElement(WorkbenchDrawer, { projectId: 'p', onClose: props.onClose ?? (() => {}), ...props })))
  await flush()
  return { host, root }
}

describe('WorkbenchDrawer states', () => {
  it('renders nothing until first opened', async () => {
    const { host } = await mount({ open: false, origin: 'http://p.test' })
    expect(host.querySelector('[data-testid=workbench]')).toBeNull()
  })
  it('empty state when no preview origin is configured; makes no request', async () => {
    const f = vi.fn(); vi.stubGlobal('fetch', f)
    const { host } = await mount({ open: true, origin: null })
    expect(host.querySelector('[data-testid=wb-no-origin]')).not.toBeNull()
    expect(f).not.toHaveBeenCalled()
  })
  it('error state with retry when the preview API is down', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('down') }))
    const { host } = await mount({ open: true, origin: 'http://p.test' })
    expect(host.querySelector('[data-testid=wb-error]')!.textContent).toContain('Could not reach the preview API')
    expect(host.querySelector('[data-testid=wb-error] button')!.textContent).toBe('Retry')
  })
  it('loads openapi from the preview origin only, without credentials; Escape closes', async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ paths: { '/a': { get: {} } } })))
    vi.stubGlobal('fetch', f)
    const onClose = vi.fn()
    const { host } = await mount({ open: true, origin: 'http://p.test', onClose })
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('http://p.test/openapi.json')
    expect(init.credentials).toBe('omit')
    expect(host.querySelector('[data-testid=wb-console]')).not.toBeNull()
    await act(async () => { host.querySelector('[data-testid=workbench]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(onClose).toHaveBeenCalled()
  })
  it('rejects a non-OpenAPI answer', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"hello":1}')))
    const { host } = await mount({ open: true, origin: 'http://p.test' })
    expect(host.querySelector('[data-testid=wb-error]')!.textContent).toContain('not an OpenAPI')
  })
})
