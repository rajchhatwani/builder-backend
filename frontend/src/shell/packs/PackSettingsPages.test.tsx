import axe from 'axe-core'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { BookingSettingsPage, CurrencySettingsPage, InvoicingSettingsPage, LedgerSettingsPage, ReconSettingsPage } from './PackSettingsPages'

const m = vi.hoisted(() => ({ getBlock: vi.fn(), putBlock: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: m }))
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
const type = async (el: HTMLInputElement, v: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const field = (path: string) => host.querySelector<HTMLInputElement>(`[data-field-path="${path}"] input`)!

const OTHER = { ai: { providers: [] }, operations: { geo: { provider: 'fake' } } }
const PACKS = {
  ...OTHER,
  money: {
    ledger: { read_roles: ['admin'], post_roles: ['admin'], max_amount_minor: 9007199254740991, max_entries: 100 },
    currency: { currencies: ['USD'], rounding: 'half_even', tax: { rates_bp: { VAT: 2000 } } },
    reconciliation: { read_roles: ['admin'], run_roles: ['admin'], tolerance_minor: 0, max_lines: 1000 },
    invoicing: { read_roles: ['admin'], write_roles: ['admin'], number_prefix: 'INV-', payment_terms_days: 30, receivable_account: 'receivables', payable_account: 'payables', revenue_account: 'revenue', expense_account: 'expenses', tax_account: 'tax', cash_account: 'bank', aging_buckets_days: [30, 60, 90], payouts: null },
  },
  booking: { kinds: [{ name: 'room', mode: 'slot', timezone: 'UTC', slot_minutes: 30, schedule: { mon: [{ start: '09:00', end: '17:00' }] }, capacity: 1, min_minutes: 15, max_minutes: 43200 }], hold_ttl_seconds: 600, max_horizon_days: 365, cancellation: { free_until_hours: 24, fee_minor: 0, currency: 'USD' }, read_roles: ['admin'], book_roles: ['admin'], manage_roles: ['admin'], own_only: false },
}

const PATHS: Record<string, string> = { 'Ledger settings': 'ledger', 'Currency settings': 'currency', 'Reconciliation settings': 'reconciliation', 'Invoicing settings': 'invoicing' }
const PAGES = [
  { name: 'ledger', Page: LedgerSettingsPage, h1: 'Ledger settings', focus: 'max_entries', val: '7', check: (p: any) => p.money.ledger.max_entries === 7 },
  { name: 'currency', Page: CurrencySettingsPage, h1: 'Currency settings', focus: 'rounding', val: 'half_up', check: (p: any) => p.money.currency.rounding === 'half_up' && p.money.currency.tax.rates_bp.VAT === 2000 },
  { name: 'reconciliation', Page: ReconSettingsPage, h1: 'Reconciliation settings', focus: 'tolerance_minor', val: '5', check: (p: any) => p.money.reconciliation.tolerance_minor === 5 },
  { name: 'invoicing', Page: InvoicingSettingsPage, h1: 'Invoicing settings', focus: 'number_prefix', val: 'BILL-', check: (p: any) => p.money.invoicing.number_prefix === 'BILL-' },
  { name: 'booking', Page: BookingSettingsPage, h1: 'Booking settings', focus: 'hold_ttl_seconds', val: '300', check: (p: any) => p.booking.hold_ttl_seconds === 300 && p.booking.kinds[0].schedule.mon[0].end === '17:00' },
]

describe.each(PAGES)('$name settings page', ({ Page, h1, focus, val, check }) => {
  it('loads, edits one field, and saves the whole packs object keeping every other key', async () => {
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: { packs: unknown }) => ({ packs: b.packs, version: 4 }))
    await mount(createElement(Page, { projectId: 'p' }))
    expect(host.querySelector('h1')?.textContent).toBe(h1)
    expect(m.getBlock).toHaveBeenCalledWith('p', 'packs')
    await type(field(focus), val)
    await act(async () => { btn(/^Save$/).click() })
    const [pid, name, body] = m.putBlock.mock.calls[0]
    expect([pid, name, body.expected_version]).toEqual(['p', 'packs', 3])
    expect(body.packs.ai).toEqual(OTHER.ai)
    expect(body.packs.operations).toEqual(OTHER.operations)
    expect(check(body.packs)).toBe(true)
    if (h1 !== 'Booking settings') {
      for (const k of Object.keys(PACKS.money)) expect(body.packs.money[k]).toBeDefined()
    }
    expect(host.querySelector('[data-testid=save-note]')?.textContent).toContain('version 4')
  })

  it('shows a 409 as a stale banner and a 422 next to the form', async () => {
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    m.putBlock.mockRejectedValueOnce(new ApiError(409, { code: 'conflict', message: 'stale', details: [] }))
    await mount(createElement(Page, { projectId: 'p' }))
    await type(field(focus), val)
    await act(async () => { btn(/^Save$/).click() })
    expect(host.querySelector('[data-testid=conflict]')).not.toBeNull()
    m.putBlock.mockRejectedValueOnce(new ApiError(422, { code: 'validation_error', message: 'Invalid spec', details: [{ loc: ['body', 'packs', ...(h1 === 'Booking settings' ? ['booking'] : ['money', PATHS[h1]]), focus], msg: 'bad value' }] }))
    await act(async () => { btn(/^Reload$/).click() })
    await type(field(focus), val)
    await act(async () => { btn(/^Save$/).click() })
    expect(host.textContent).toContain('Invalid spec')
    expect(host.querySelector(`[data-field-path="${focus}"] [data-testid=field-error]`)?.textContent).toBe('bad value')
  })

  it('shows the off state when the block is empty, and Switch on saves the defaults without touching other packs', async () => {
    const without = { ...OTHER }
    m.getBlock.mockResolvedValue({ packs: without, version: 1 })
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: { packs: unknown }) => ({ packs: b.packs, version: 2 }))
    await mount(createElement(Page, { projectId: 'p' }))
    expect(host.querySelector('h1')?.textContent).toBe(h1)
    expect(host.querySelector('[data-testid=block-off]')).not.toBeNull()
    await act(async () => { btn(/^Switch on/).click() })
    const body = m.putBlock.mock.calls[0][2]
    expect(body.expected_version).toBe(1)
    expect(body.packs.ai).toEqual(OTHER.ai)
    expect(JSON.stringify(body.packs)).toContain(h1 === 'Currency settings' ? '"USD"' : '"admin"')
    expect(host.querySelector('[data-schema-form]')).not.toBeNull()
  })

  it('switches a block off after a confirmation', async () => {
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: { packs: unknown }) => ({ packs: b.packs, version: 4 }))
    await mount(createElement(Page, { projectId: 'p' }))
    await act(async () => { btn(/^Switch off/).click() })
    await act(async () => { btn(/^Yes, switch off/).click() })
    expect(m.putBlock.mock.calls[0][2].packs.ai).toEqual(OTHER.ai)
    expect(host.querySelector('[data-testid=block-off]')).not.toBeNull()
  })

  it('shows a load failure with a retry', async () => {
    m.getBlock.mockRejectedValueOnce(new Error('down'))
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    await mount(createElement(Page, { projectId: 'p' }))
    expect(host.textContent).toContain('down')
    await act(async () => { btn(/Retry|Try again/i).click() })
    expect(host.querySelector('[data-schema-form]')).not.toBeNull()
  })

  it('has no axe violations (form and off state)', async () => {
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    await mount(createElement(Page, { projectId: 'p' }))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => v.id)).toEqual([])
    act(() => root?.unmount()); host.remove()
    m.getBlock.mockResolvedValue({ packs: OTHER, version: 1 })
    await mount(createElement(Page, { projectId: 'p' }))
    const res2 = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res2.violations.map((v) => v.id)).toEqual([])
  })
})

describe('optional parts', () => {
  it('tax rates and payouts switch on with their defaults and off to null', async () => {
    m.getBlock.mockResolvedValue({ packs: { money: { invoicing: { ...PACKS.money.invoicing } } }, version: 1 })
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: { packs: unknown }) => ({ packs: b.packs, version: 2 }))
    await mount(createElement(InvoicingSettingsPage, { projectId: 'p' }))
    expect(host.querySelector('[data-field-path="payouts.commission_bp"]')).toBeNull()
    await act(async () => { host.querySelector<HTMLInputElement>('[data-field-path="payouts"] input[type=checkbox]')!.click() })
    expect(field('payouts.commission_bp').value).toBe('1000')
    await act(async () => { btn(/^Save$/).click() })
    expect(m.putBlock.mock.calls[0][2].packs.money.invoicing.payouts).toEqual({ commission_bp: 1000, seller_payable_account: 'seller_payable', commission_account: 'commission' })
  })
})
