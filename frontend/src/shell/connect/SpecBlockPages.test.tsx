import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { ApiEdgePage, EventsPage, HookEffectsPage, NotificationTypesPage } from './SpecBlockPages'

const m = vi.hoisted(() => ({ getBlock: vi.fn(), putBlock: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: m }))
vi.mock('../../components/Ui', () => ({ useUi: () => ({ confirm: vi.fn(), toast: vi.fn() }) }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount(el: ReturnType<typeof createElement>) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(el) })
  await act(async () => { await Promise.resolve() })
}
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null; Object.values(m).forEach((f) => f.mockReset()) })
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!

const PAGES = [
  { name: 'events', path: 'events', key: 'events', Page: EventsPage, title: 'Events', block: { enabled: true, adapter: 'in_process', retention_days: 14 } },
  { name: 'api edge', path: 'api-edge', key: 'api_edge', Page: ApiEdgePage, title: 'API edge', block: { enabled: true, quotas: [] } },
  { name: 'hook effects', path: 'hook-effects', key: 'hook_effects', Page: HookEffectsPage, title: 'Hook effects', block: { enabled: false, trusted_authors_only: true, webhook_hosts: [] } },
  { name: 'notification types', path: 'notifications', key: 'notifications', Page: NotificationTypesPage, title: 'Notification types', block: { enabled: true, types: [{ name: 'order_created', channels: ['email'] }] } },
]

describe.each(PAGES)('$name page', ({ path, key, Page, title, block }) => {
  beforeEach(() => { m.getBlock.mockResolvedValue({ [key]: block, version: 4 }) })

  it('loads its block from the behavior endpoint into a form', async () => {
    await mount(createElement(Page, { projectId: 'p' }))
    expect(host.querySelector('h1')?.textContent).toBe(title)
    expect(m.getBlock).toHaveBeenCalledWith('p', path)
    expect(host.querySelector('[data-schema-form]')).not.toBeNull()
  })

  it('saves under the right key with expected_version', async () => {
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: Record<string, unknown>) => ({ [key]: b[key], version: 5 }))
    await mount(createElement(Page, { projectId: 'p' }))
    await act(async () => { host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click() })
    await act(async () => { btn(/^Save$/).click() })
    const [pid, n, body] = m.putBlock.mock.calls[0]
    expect([pid, n, body.expected_version]).toEqual(['p', path, 4])
    expect(body[key]).toBeTypeOf('object')
    expect(host.querySelector('[data-testid=save-note]')?.textContent).toContain('version 5')
  })

  it('shows the error envelope message from a rejected save', async () => {
    m.putBlock.mockRejectedValue(new ApiError(422, { code: 'invalid_spec', message: 'the block is not valid', details: [] }))
    await mount(createElement(Page, { projectId: 'p' }))
    await act(async () => { host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click() })
    await act(async () => { btn(/^Save$/).click() })
    expect(host.querySelector('[role=alert]')?.textContent).toContain('the block is not valid')
  })
})
