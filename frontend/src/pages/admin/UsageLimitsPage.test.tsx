import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { UiProvider } from '../../components/Ui'

import { UsageLimitsPage, parseLimit } from './UsageLimitsPage'

const m = vi.hoisted(() => ({ adminOrganizations: vi.fn(), adminOrgUsage: vi.fn(), adminSetOrgUsageLimit: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: m }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.setAttribute('open', '') }
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) }

const ORG = '11111111-1111-4111-8111-111111111111'
const metric = (over: Record<string, unknown> = {}) => ({ metric: 'generations', unit: 'runs', period: 'month', period_start: null, period_end: null, used: 40, limit: 100, refused: 2, ...over })

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount(readOnly = false) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(UiProvider, null, createElement(UsageLimitsPage, { readOnly }))) })
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const tick = () => new Promise((r) => setTimeout(r, 0))
const btn = (re: RegExp) => [...document.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const click = async (el: Element) => { await act(async () => { (el as HTMLElement).click(); await tick() }) }
const type = async (el: HTMLInputElement, v: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function open(metrics: unknown[]) {
  m.adminOrgUsage.mockResolvedValue({ metrics })
  await type(document.getElementById('ul-org-id') as HTMLInputElement, 'acme')
  await click(document.querySelector('[data-testid=ul-open]')!)
}
const limit = () => document.getElementById('ul-generations') as HTMLInputElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); document.body.innerHTML = ''; root = null; Object.values(m).forEach((f) => f.mockReset()) })

describe('parseLimit', () => {
  it('maps empty to unlimited and rejects bad input', () => {
    expect(parseLimit('')).toEqual({ value: null })
    expect(parseLimit(' 12 ')).toEqual({ value: 12 })
    expect(parseLimit('-1')).toHaveProperty('error')
    expect(parseLimit('1.5')).toHaveProperty('error')
    expect(parseLimit('abc')).toHaveProperty('error')
  })
})

describe('UsageLimitsPage', () => {
  it('starts idle, then shows usage for the chosen organization', async () => {
    m.adminOrganizations.mockResolvedValue({ items: [{ id: ORG, name: 'Acme' }], total: 1, limit: 50, offset: 0 })
    await mount()
    expect(document.querySelector('[data-testid=ul-idle]')).not.toBeNull()
    await open([metric()])
    expect(m.adminOrgUsage).toHaveBeenCalledWith('acme')
    const row = document.querySelector('[data-testid=metric-row]')!
    expect(row.querySelector('[data-testid=metric-used]')?.textContent).toContain('40')
    expect(row.querySelector('[data-testid=metric-refused]')?.textContent).toBe('2')
    expect(limit().value).toBe('100')
  })

  it('F-0544 a late response for the previously picked org is ignored', async () => {
    m.adminOrganizations.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
    await mount()
    let lateA!: (v: unknown) => void
    m.adminOrgUsage.mockImplementationOnce(() => new Promise((r) => { lateA = r }))
    m.adminOrgUsage.mockResolvedValueOnce({ metrics: [metric({ limit: 7 })] })
    const input = document.getElementById('ul-org-id') as HTMLInputElement
    await type(input, 'a')
    await click(document.querySelector('[data-testid=ul-open]')!)
    await type(input, 'b')
    await click(document.querySelector('[data-testid=ul-open]')!)
    expect(limit().value).toBe('7')
    await act(async () => { lateA({ metrics: [metric({ limit: 999 })] }); await tick() })
    expect(limit().value).toBe('7')
  })

  it('shows empty and error states', async () => {
    m.adminOrganizations.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
    await mount()
    await open([])
    expect(document.querySelector('[data-testid=ul-empty]')).not.toBeNull()
    m.adminOrgUsage.mockRejectedValue(new ApiError(404, 'nope'))
    await click(document.querySelector('[data-testid=ul-open]')!)
    expect(document.querySelector('[role=alert]')?.textContent).toContain('No organization with that id or slug')
  })

  it('edits a limit: confirm, PUT, refreshed table', async () => {
    m.adminOrganizations.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
    await mount()
    await open([metric()])
    await type(limit(), '250')
    await click(document.querySelector('[data-testid=metric-save]')!)
    expect(m.adminSetOrgUsageLimit).not.toHaveBeenCalled() // waits for the confirmation
    m.adminSetOrgUsageLimit.mockResolvedValue({ metrics: [metric({ limit: 250 })] })
    await click(btn(/^Change limit$/))
    expect(m.adminSetOrgUsageLimit).toHaveBeenCalledWith('acme', 'generations', 250)
    expect(limit().value).toBe('250')
  })

  it('empty box saves unlimited (null)', async () => {
    m.adminOrganizations.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
    await mount()
    await open([metric()])
    await type(limit(), '')
    m.adminSetOrgUsageLimit.mockResolvedValue({ metrics: [metric({ limit: null })] })
    await click(document.querySelector('[data-testid=metric-save]')!)
    await click(btn(/^Change limit$/))
    expect(m.adminSetOrgUsageLimit).toHaveBeenCalledWith('acme', 'generations', null)
  })

  it('rejects a negative value locally and does not call the API', async () => {
    m.adminOrganizations.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
    await mount()
    await open([metric()])
    await type(limit(), '-5')
    await click(document.querySelector('[data-testid=metric-save]')!)
    expect(document.body.textContent).toContain('cannot be negative')
    expect(m.adminSetOrgUsageLimit).not.toHaveBeenCalled()
  })

  it('shows a server failure and keeps the draft', async () => {
    m.adminOrganizations.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
    await mount()
    await open([metric()])
    await type(limit(), '7')
    m.adminSetOrgUsageLimit.mockRejectedValue(new ApiError(403, 'forbidden'))
    await click(document.querySelector('[data-testid=metric-save]')!)
    await click(btn(/^Change limit$/))
    expect(document.body.textContent).toContain('Only platform admins can change usage limits')
    expect(limit().value).toBe('7')
  })

  it('read-only staff see usage but no save buttons and disabled inputs', async () => {
    m.adminOrganizations.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
    await mount(true)
    await open([metric()])
    expect(document.querySelector('[data-testid=metric-save]')).toBeNull()
    expect(limit().disabled).toBe(true)
  })
})
