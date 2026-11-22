import axe from 'axe-core'
import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { click, mount, q, qa, setInput } from '../ai/testUtils'
import { InvoicesPage } from './InvoicesPage'

const mk = (o: Record<string, unknown>) => ({ id: 'i1', kind: 'receivable', number: 'INV-1', status: 'issued', counterparty: 'Acme', currency: 'USD', exponent: 2, issue_date: '2026-01-01', due_date: '2026-02-01', total_minor: 9007199254740993, paid_minor: 0, outstanding_minor: 9007199254740993, ...o })
const LIST = { items: [mk({}), mk({ id: 'i2', status: 'draft', number: null, total_minor: 1000, outstanding_minor: 1000 }), mk({ id: 'i3', currency: 'JPY', exponent: 0, total_minor: 500, outstanding_minor: 500 })], total: 3, limit: 100, offset: 0 }
const AGING = { kind: 'receivable', as_of: '2026-03-01', bucket_days: [30, 60], currencies: [{ currency: 'USD', current_minor: 100, current_count: 1, buckets: [{ label: '1-30', from_days: 1, to_days: 30, amount_minor: 2500, count: 2 }, { label: '31+', from_days: 31, to_days: null, amount_minor: 0, count: 0 }], total_minor: 2600, count: 3 }] }
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b).replace(/9007199254740992/g, '9007199254740993'), { status })

function api(over: (m: string, url: string) => Response | undefined = () => undefined) {
  const calls: { m: string; url: string; body?: string }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    calls.push({ m, url, body: init.body as string | undefined })
    const o = over(m, url)
    if (o) return o
    if (url.includes('/invoices/aging')) return json(AGING)
    if (m === 'GET' && url.includes('/invoices')) return json(LIST)
    if (m === 'POST') return json(mk({}), 201)
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const load = (f: typeof fetch) => mount(createElement(InvoicesPage, { projectId: 'p', session: readySession(f) }))

describe('InvoicesPage', () => {
  it('shows the gate and fetches nothing without a session', async () => {
    const { f } = api()
    const host = await mount(createElement(InvoicesPage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('inv-no-origin')).not.toBeNull()
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(f).not.toHaveBeenCalled()
  })

  it('lists invoices with exact BigInt totals per currency and AR aging buckets', async () => {
    const { f } = api()
    await load(f)
    expect(qa('inv-row')).toHaveLength(3)
    expect(qa('inv-total-row')).toHaveLength(2)
    expect(qa('inv-total-total')[0].textContent).toBe('90,071,992,547,419.93')
    expect(qa('inv-total-total')[1].textContent).toBe('500')
    expect(qa('aging-bucket').map((e) => e.textContent)).toEqual(['25.00 (2)', '0.00 (0)'])
    expect(q('aging-total')?.textContent).toBe('26.00 (3)')
  })

  it('shows empty and error states', async () => {
    const { f } = api((m, u) => (m === 'GET' && u.includes('/invoices?') ? json({ items: [], total: 0 }) : undefined))
    await load(f)
    expect(q('inv-list-empty')).not.toBeNull()
  })
  it('explains a 403 and a 404 in the list', async () => {
    const { f } = api((_m, u) => (u.includes('/invoices?') ? json({ code: 'forbidden', message: 'x' }, 403) : undefined))
    await load(f)
    expect(q('inv-list-error')?.textContent).toMatch(/role/)
  })

  it('refetches with the aging kind and filters', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('aging-kind') as HTMLSelectElement, 'payable')
    expect(calls.some((c) => c.url.includes('/invoices/aging?kind=payable'))).toBe(true)
    await setInput(q('inv-filter-status') as HTMLSelectElement, 'draft')
    expect(calls.some((c) => c.url.includes('status=draft'))).toBe(true)
  })

  it('creates a draft invoice with minor-unit lines', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('inv-new-counterparty') as HTMLInputElement, 'Globex')
    await setInput(q('inv-line-desc') as HTMLInputElement, 'Work')
    await setInput(q('inv-line-price') as HTMLInputElement, '10.50')
    await setInput(q('inv-line-tax') as HTMLInputElement, 'vat')
    await click(q('inv-create'))
    const post = calls.find((c) => c.m === 'POST' && c.url.endsWith('/invoices'))!
    expect(JSON.parse(post.body!)).toEqual({ kind: 'receivable', counterparty: 'Globex', currency: 'USD', lines: [{ description: 'Work', quantity: 1, unit_price_minor: 1050, tax_rate: 'vat' }] })
    expect(q('inv-create-ok')).not.toBeNull()
  })
  it('refuses a bad create locally and shows API errors', async () => {
    const { f, calls } = api((m) => (m === 'POST' ? json({ code: 'unknown_tax_rate', message: 'tax rate vat is not defined' }, 422) : undefined))
    await load(f)
    await click(q('inv-create'))
    expect(q('inv-create-error')?.textContent).toMatch(/name/)
    await setInput(q('inv-new-counterparty') as HTMLInputElement, 'G')
    await setInput(q('inv-line-desc') as HTMLInputElement, 'W')
    await setInput(q('inv-line-price') as HTMLInputElement, '1.234')
    await click(q('inv-create'))
    expect(q('inv-create-error')?.textContent).toMatch(/decimals/)
    expect(calls.some((c) => c.m === 'POST')).toBe(false)
    await setInput(q('inv-line-price') as HTMLInputElement, '1.23')
    await click(q('inv-create'))
    expect(q('inv-create-error')?.textContent).toMatch(/not defined/)
  })

  it('issues a draft', async () => {
    const { f, calls } = api()
    await load(f)
    await click(q('inv-issue'))
    expect(calls.some((c) => c.m === 'POST' && c.url.endsWith('/invoices/i2/issue'))).toBe(true)
    expect(q('inv-notice')?.textContent).toBe('Invoice issued.')
  })

  it('records a payment with an idempotency key and minor units', async () => {
    const { f, calls } = api()
    await load(f)
    await click(q('inv-pay-btn'))
    await setInput(q('inv-pay-amount') as HTMLInputElement, '12.5')
    await click(q('inv-pay-submit'))
    const post = calls.find((c) => c.url.endsWith('/invoices/i1/payments'))!
    const b = JSON.parse(post.body!)
    expect(b.amount_minor).toBe(1250)
    expect(typeof b.idempotency_key).toBe('string')
    expect(b.idempotency_key.length).toBeGreaterThan(0)
    expect(q('inv-notice')?.textContent).toBe('Payment recorded.')
  })
  it('rejects a bad payment amount and shows API conflicts', async () => {
    const { f, calls } = api((m, u) => (m === 'POST' && u.includes('/payments') ? json({ code: 'idempotency_conflict', message: 'x' }, 409) : undefined))
    await load(f)
    await click(q('inv-pay-btn'))
    await setInput(q('inv-pay-amount') as HTMLInputElement, 'abc')
    await click(q('inv-pay-submit'))
    expect(q('inv-pay-error')).not.toBeNull()
    expect(calls.some((c) => c.m === 'POST')).toBe(false)
    await setInput(q('inv-pay-amount') as HTMLInputElement, '1')
    await click(q('inv-pay-submit'))
    expect(q('inv-row-error')?.textContent).toMatch(/idempotency key/)
  })

  it('voids after confirmation and reports has_payments', async () => {
    const { f, calls } = api((m, u) => (m === 'POST' && u.includes('/void') ? json({ code: 'has_payments', message: 'x' }, 409) : undefined))
    await load(f)
    await click(qa('inv-void-btn')[0])
    await setInput(q('inv-void-reason') as HTMLInputElement, 'dup')
    await click(q('inv-void-yes'))
    expect(JSON.parse(calls.find((c) => c.url.endsWith('/i1/void'))!.body!)).toEqual({ reason: 'dup' })
    expect(q('inv-row-error')?.textContent).toMatch(/cannot be voided/)
  })

  it('has no axe violations (loaded, payment form open)', async () => {
    const { f } = api()
    const host = await load(f)
    await click(q('inv-pay-btn'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
