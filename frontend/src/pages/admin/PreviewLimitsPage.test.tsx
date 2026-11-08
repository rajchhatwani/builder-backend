import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { UiProvider } from '../../components/Ui'
import { PreviewLimitsPage, showPreviewLimits } from './PreviewLimitsPage'

const m = vi.hoisted(() => ({
  adminPreviewLimits: vi.fn(), adminUpdatePreviewLimits: vi.fn(), adminPreviewOrgLimits: vi.fn(),
  adminSetPreviewOrgLimits: vi.fn(), adminClearPreviewOrgLimits: vi.fn(), adminOrganizations: vi.fn(),
  adminPreviewOrgList: vi.fn(), adminPreviewUsage: vi.fn(),
}))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: m }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

// jsdom has no <dialog> methods.
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.setAttribute('open', '') }
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) }

const ORG = '11111111-1111-4111-8111-111111111111'
const DEFAULTS = { max_live_per_user: 3, sleep_after_minutes: 30, delete_after_days: 14, cpus: 0.5, memory_mb: 512, db_mb: 1024, rate_per_minute: 120 }
const BOUNDS = { max_live_per_user: [1, 10], sleep_after_minutes: [5, 240], delete_after_days: [1, 30], cpus: [0.25, 2], memory_mb: [256, 2048], db_mb: [256, 1024], rate_per_minute: [10, 1000] }
const LIMITS = { kill_switch: false, defaults: DEFAULTS, bounds: BOUNDS, updated_at: null, updated_by: null }
const ORG_ROW = { organization_id: ORG, enabled: true, overrides: { max_live_per_user: 5 }, effective: { ...DEFAULTS, max_live_per_user: 5 }, kill_switch: false, allow_above_default: false, note: 'pilot', updated_at: '2026-11-02T10:00:00Z' }
const ROW = { organization_id: ORG, organization_name: 'Acme', organization_slug: 'acme', enabled: true, allow_above_default: false, overrides: { max_live_per_user: 5 }, note: 'pilot', updated_at: '2026-11-02T10:00:00Z' }
const page = (items: unknown[], total = items.length, offset = 0) => ({ items, total, limit: 25, offset })

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount(readOnly = false) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(UiProvider, null, createElement(PreviewLimitsPage, { readOnly }))) })
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const btn = (re: RegExp) => [...document.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const input = (id: string) => document.getElementById(id) as HTMLInputElement
const click = async (el: Element) => { await act(async () => { (el as HTMLElement).click(); await new Promise((r) => setTimeout(r, 0)) }) }
const type = async (el: HTMLInputElement, v: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
function setup(over: Record<string, unknown> = {}) {
  m.adminPreviewLimits.mockResolvedValue({ ...LIMITS, ...over })
  m.adminOrganizations.mockResolvedValue({ items: [{ id: ORG, name: 'Acme' }], total: 1, limit: 50, offset: 0 })
  m.adminPreviewOrgLimits.mockResolvedValue(ORG_ROW)
  m.adminPreviewOrgList.mockResolvedValue(page([ROW]))
  m.adminPreviewUsage.mockResolvedValue({ live: 2, running: 1, by_state: {}, orgs_with_overrides: 1, kill_switch: false })
}
afterEach(() => { act(() => root?.unmount()); host?.remove(); document.body.innerHTML = ''; root = null; Object.values(m).forEach((f) => f.mockReset()) })

describe('PreviewLimitsPage', () => {
  it('renders defaults with their bounds and the override table', async () => {
    setup()
    await mount()
    expect(host.querySelector('h1')?.textContent).toBe('Preview limits')
    expect(input('pl-def-sleep_after_minutes').value).toBe('30')
    expect(host.textContent).toContain('Allowed 0.25 to 2.')
    expect(host.querySelector('[data-testid=kill-state]')?.textContent).toContain('Off')
    expect(host.querySelector('[data-testid=override-table]')?.textContent).toContain('Acme')
    expect(host.querySelector('[data-testid=override-table]')?.textContent).toContain('pilot')
    expect(host.querySelector('[data-testid=usage]')?.textContent).toContain('2 live previews (1 running)')
    expect(m.adminPreviewOrgLimits).not.toHaveBeenCalled() // no per-org reads for the table
  })

  it('shows the empty state when no organization has an override', async () => {
    setup()
    m.adminPreviewOrgList.mockResolvedValue(page([]))
    await mount()
    expect(host.querySelector('[data-testid=no-overrides]')).not.toBeNull()
  })

  it('saves only the changed defaults', async () => {
    setup()
    m.adminUpdatePreviewLimits.mockResolvedValue({ ...LIMITS, defaults: { ...DEFAULTS, memory_mb: 768 } })
    await mount()
    expect(btn(/^Save defaults$/).disabled).toBe(true)
    await type(input('pl-def-memory_mb'), '768')
    await click(btn(/^Save defaults$/))
    expect(m.adminUpdatePreviewLimits).toHaveBeenCalledWith({ defaults: { memory_mb: 768 } })
    expect(host.querySelector('[data-testid=save-note]')?.textContent).toBe('Saved.')
  })

  it('shows 422 messages next to the field and 403 as a permission message', async () => {
    setup()
    m.adminUpdatePreviewLimits.mockRejectedValueOnce(new ApiError(422, { code: 'validation_error', message: 'Validation failed', details: [{ loc: ['body', 'defaults', 'cpus'], msg: 'cpus must be between 0.25 and 2' }] }))
    await mount()
    await type(input('pl-def-cpus'), '9')
    await click(btn(/^Save defaults$/))
    expect(host.querySelector('[data-testid=field-error]')?.textContent).toBe('cpus must be between 0.25 and 2')
    expect(input('pl-def-cpus').getAttribute('aria-invalid')).toBe('true')
    m.adminUpdatePreviewLimits.mockRejectedValueOnce(new ApiError(403, { code: 'forbidden', message: 'Forbidden', details: [] }))
    await click(btn(/^Save defaults$/))
    expect(host.querySelector('[data-testid=defaults-error]')?.textContent).toContain('Only platform admins')
  })

  it('asks for confirmation before the kill switch changes, and cancel does nothing', async () => {
    setup()
    m.adminUpdatePreviewLimits.mockResolvedValue({ ...LIMITS, kill_switch: true })
    await mount()
    await click(btn(/Turn kill switch on/))
    expect(document.body.textContent).toContain('Turn the preview kill switch on?')
    await click(btn(/^Cancel$/))
    expect(m.adminUpdatePreviewLimits).not.toHaveBeenCalled()
    await click(btn(/Turn kill switch on/))
    await click(btn(/^Stop all previews$/))
    expect(m.adminUpdatePreviewLimits).toHaveBeenCalledWith({ kill_switch: true })
    expect(host.querySelector('[data-testid=kill-state]')?.textContent).toContain('ON')
  })

  it('edits an override and sends enabled, overrides and note', async () => {
    setup()
    m.adminSetPreviewOrgLimits.mockResolvedValue(ORG_ROW)
    await mount()
    await click(btn(/^Edit/))
    await type(input('pl-org-db_mb'), '512')
    await click(btn(/^Save override$/))
    expect(m.adminSetPreviewOrgLimits).toHaveBeenCalledWith(ORG, { enabled: true, allow_above_default: false, overrides: { max_live_per_user: 5, db_mb: 512 }, note: 'pilot' })
  })

  it('sends allow_above_default and shows the 422 message for an over-default override', async () => {
    setup()
    m.adminSetPreviewOrgLimits.mockRejectedValueOnce(new ApiError(422, { code: 'validation_error', message: 'memory_mb 1024 is above the platform default 512; tick "allow above default"', details: [] }))
    await mount()
    await click(btn(/^Edit/))
    await type(input('pl-org-memory_mb'), '1024')
    await click(btn(/^Save override$/))
    expect(host.querySelector('[data-testid=org-error]')?.textContent).toContain('above the platform default')
    const box = [...document.querySelectorAll('input[type=checkbox]')].find((c) => c.parentElement?.textContent?.includes('above the platform default')) as HTMLInputElement
    await click(box)
    m.adminSetPreviewOrgLimits.mockResolvedValueOnce(ORG_ROW)
    await click(btn(/^Save override$/))
    expect(m.adminSetPreviewOrgLimits).toHaveBeenLastCalledWith(ORG, expect.objectContaining({ allow_above_default: true }))
  })

  it('pages the override list', async () => {
    setup()
    m.adminPreviewOrgList.mockResolvedValueOnce(page([ROW], 30, 0))
    await mount()
    expect(host.querySelector('[data-testid=override-range]')?.textContent).toBe('1 to 25 of 30')
    expect(btn(/^Previous$/).disabled).toBe(true)
    m.adminPreviewOrgList.mockResolvedValueOnce(page([ROW], 30, 25))
    await click(btn(/^Next$/))
    expect(m.adminPreviewOrgList).toHaveBeenLastCalledWith(25, 25)
    expect(host.querySelector('[data-testid=override-range]')?.textContent).toBe('26 to 30 of 30')
    expect(btn(/^Next$/).disabled).toBe(true)
  })

  it('removes an override after confirmation', async () => {
    setup()
    m.adminClearPreviewOrgLimits.mockResolvedValue({ ...ORG_ROW, updated_at: null, overrides: {} })
    await mount()
    await click(btn(/^Remove/))
    await click([...document.querySelectorAll('button')].filter((b) => b.textContent === 'Remove').pop()!)
    expect(m.adminClearPreviewOrgLimits).toHaveBeenCalledWith(ORG)
  })

  it('disables every control when read-only', async () => {
    setup()
    await mount(true)
    expect(input('pl-def-cpus').disabled).toBe(true)
    expect(btn(/Turn kill switch on/).disabled).toBe(true)
    expect(document.getElementById('pl-add-org')).toBeNull()
  })

  it('shows a retry when loading fails', async () => {
    m.adminPreviewLimits.mockRejectedValue(new Error('boom'))
    m.adminPreviewOrgList.mockResolvedValue(page([]))
    m.adminPreviewUsage.mockResolvedValue(null)
    m.adminOrganizations.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
    await mount()
    expect(host.querySelector('[role=alert]')?.textContent).toContain('boom')
  })
})

describe('showPreviewLimits', () => {
  it('is hidden from non-admins and without the v2 flag', () => {
    expect(showPreviewLimits('platform_admin', true)).toBe(true)
    expect(showPreviewLimits('platform_support', true)).toBe(false)
    expect(showPreviewLimits('customer', true)).toBe(false)
    expect(showPreviewLimits(undefined, true)).toBe(false)
    expect(showPreviewLimits('platform_admin', false)).toBe(false)
  })
})
