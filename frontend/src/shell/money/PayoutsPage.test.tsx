import axe from 'axe-core'
import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { click, mount, q, qa, setInput } from '../ai/testUtils'
import { PayoutsPage } from './PayoutsPage'

const INV = { id: 'i1', kind: 'receivable', number: 'INV-1', status: 'paid', counterparty: 'Acme', currency: 'USD', exponent: 2, total_minor: 10000, paid_minor: 10000, outstanding_minor: 0 }
const PAYOUT = { id: 'p1', invoice_id: 'i0', seller: 'shop-1', currency: 'USD', gross_minor: 9007199254740993, commission_bp: 1000, commission_minor: 900719925474099, seller_minor: 8106479329266894, created_at: '2026-01-01T00:00:00Z' }
const TOTAL = { seller: 'shop-1', currency: 'USD', count: 1, gross_minor: 9007199254740993, commission_minor: 1000, seller_minor: 5 }
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b).replace(/9007199254740992/g, '9007199254740993'), { status })

function api(over: (m: string, url: string) => Response | undefined = () => undefined) {
  const calls: { m: string; url: string; body?: string }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    calls.push({ m, url, body: init.body as string | undefined })
    const o = over(m, url)
    if (o) return o
    if (url.includes('/payouts/run')) return json(PAYOUT, 201)
    if (url.includes('/payouts/totals')) return json([TOTAL])
    if (url.includes('/payouts')) return json({ items: [PAYOUT], total: 1 })
    if (url.includes('/invoices')) return json({ items: [INV, { ...INV, id: 'i0' }], total: 2 })
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const load = (f: typeof fetch) => mount(createElement(PayoutsPage, { projectId: 'p', session: readySession(f) }))

describe('PayoutsPage', () => {
  it('gates without a session', async () => {
    const { f } = api()
    const host = await mount(createElement(PayoutsPage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('payouts-no-origin')).not.toBeNull()
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(f).not.toHaveBeenCalled()
  })
  it('shows payouts and exact totals, excluding already paid-out invoices from the picker', async () => {
    const { f } = api()
    await load(f)
    expect(qa('payout-row')).toHaveLength(1)
    expect(qa('payout-row')[0].textContent).toContain('90,071,992,547,409.93')
    expect(q('payout-total-seller')?.textContent).toBe('0.05')
    const opts = Array.from((q('payout-invoice') as HTMLSelectElement).options).map((o) => o.value)
    expect(opts).toEqual(['', 'i1'])
  })
  it('shows a clear message when the project has no payouts block', async () => {
    const { f } = api((_m, u) => (u.includes('/payouts') ? json({ detail: 'Not Found' }, 404) : undefined))
    await load(f)
    expect(q('payouts-disabled')?.textContent).toMatch(/no payouts block/)
    expect(q('payout-form')).toBeNull()
  })
  it('shows empty state', async () => {
    const { f } = api((_m, u) => (u.includes('/payouts/totals') ? json([]) : u.includes('/payouts') ? json({ items: [], total: 0 }) : undefined))
    await load(f)
    expect(q('payout-list-empty')).not.toBeNull()
    expect(q('payout-totals-empty')).not.toBeNull()
  })
  it('runs a payout after confirmation with an idempotency key', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('payout-invoice') as HTMLSelectElement, 'i1')
    await setInput(q('payout-seller') as HTMLInputElement, 'shop-1')
    await click(q('payout-run'))
    expect(q('payout-confirm')?.textContent).toMatch(/irreversible/)
    expect(calls.some((c) => c.url.includes('/payouts/run'))).toBe(false)
    await click(q('payout-yes'))
    const b = JSON.parse(calls.find((c) => c.url.includes('/payouts/run'))!.body!)
    expect(b).toMatchObject({ invoice_id: 'i1', seller: 'shop-1' })
    expect(b.idempotency_key.length).toBeGreaterThan(0)
    expect(q('payout-ok')?.textContent).toBe('Payout run.')
  })
  it('rejects a bad seller locally and shows API errors', async () => {
    const { f, calls } = api((m, _u) => (m === 'POST' ? json({ code: 'already_paid_out', message: 'x' }, 409) : undefined))
    await load(f)
    await setInput(q('payout-invoice') as HTMLSelectElement, 'i1')
    await setInput(q('payout-seller') as HTMLInputElement, 'bad seller')
    await click(q('payout-run'))
    expect(q('payout-error')?.textContent).toMatch(/Seller must be/)
    expect(calls.some((c) => c.m === 'POST')).toBe(false)
    await setInput(q('payout-seller') as HTMLInputElement, 'ok')
    await click(q('payout-run'))
    await click(q('payout-yes'))
    expect(q('payout-error')?.textContent).toMatch(/already been paid out/)
  })
  it('has no axe violations', async () => {
    const { f } = api()
    const host = await load(f)
    await setInput(q('payout-invoice') as HTMLSelectElement, 'i1')
    await setInput(q('payout-seller') as HTMLInputElement, 's')
    await click(q('payout-run'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
