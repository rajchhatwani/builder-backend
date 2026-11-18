import axe from 'axe-core'
import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { click, flush, mount, q, qa, setInput } from '../ai/testUtils'
import { LedgerPage } from './LedgerPage'

const ACCTS = [
  { id: 'a1', code: '1000', name: 'Cash', kind: 'asset', currency: 'USD', exponent: 2 },
  { id: 'a2', code: '4000', name: 'Sales', kind: 'income', currency: 'USD', exponent: 2 },
  { id: 'j1', code: '1100', name: 'Yen cash', kind: 'asset', currency: 'JPY', exponent: 0 },
]
const BAL = {
  items: [
    { account_id: 'a1', code: '1000', name: 'Cash', currency: 'USD', exponent: 2, balance_minor: 123456, debit_total_minor: 123456, credit_total_minor: 0 },
    { account_id: 'a2', code: '4000', name: 'Sales', currency: 'USD', exponent: 2, balance_minor: -123456, debit_total_minor: 0, credit_total_minor: -123456 },
    { account_id: 'j1', code: '1100', name: 'Yen cash', currency: 'JPY', exponent: 0, balance_minor: 500, debit_total_minor: 500, credit_total_minor: 0 },
  ],
  totals: [{ currency: 'USD', sum_minor: 0 }, { currency: 'JPY', sum_minor: 0 }],
}
const TX = {
  id: 't1', idempotency_key: 'k', description: 'Sale', reference: 'INV-1', reverses_id: null, reversed_by_id: null, posted_at: '2026-01-01T00:00:00Z', posted_by: null,
  entries: [
    { id: 'e1', line_no: 1, account_id: 'a1', currency: 'USD', amount_minor: 123456, direction: 'debit' },
    { id: 'e2', line_no: 2, account_id: 'a2', currency: 'USD', amount_minor: -123456, direction: 'credit' },
  ],
}
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })

function api(over: (m: string, url: string) => Response | undefined = () => undefined) {
  const calls: { m: string; url: string; body?: string; auth?: string }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    calls.push({ m, url, body: init.body as string | undefined, auth: (init.headers as Record<string, string>).Authorization })
    const o = over(m, url)
    if (o) return o
    if (url.includes('/ledger/accounts/') && url.includes('/entries')) return json({ items: [{ id: 'h1', transaction_id: 't1', line_no: 1, currency: 'USD', amount_minor: -123456, direction: 'credit', posted_at: '2026-01-01', description: 'Sale', reverses_id: null }], total: 1 })
    if (url.includes('/ledger/accounts')) return json({ items: ACCTS, total: 3, limit: 200, offset: 0 })
    if (url.includes('/ledger/balances')) return json(BAL)
    if (url.includes('/ledger/transactions') && m === 'GET') return json({ items: [TX], total: 1, limit: 20, offset: 0 })
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}

async function load(f: typeof fetch) {
  const host = await mount(createElement(LedgerPage, { projectId: 'p', origin: 'http://gen.test', doFetch: f }))
  await setInput(q('ledger-token') as HTMLInputElement, 'TOK')
  await click(q('ledger-load'))
  return host
}

describe('LedgerPage', () => {
  it('explains when no preview origin is configured and fetches nothing', async () => {
    const { f } = api()
    await mount(createElement(LedgerPage, { projectId: 'p', origin: null, doFetch: f }))
    expect(q('ledger-no-origin')).not.toBeNull()
    expect(f).not.toHaveBeenCalled()
  })

  it('asks for a token first, then loads with a Bearer header', async () => {
    const { f, calls } = api()
    await mount(createElement(LedgerPage, { projectId: 'p', origin: 'http://gen.test', doFetch: f }))
    expect(q('ledger-notoken')).not.toBeNull()
    expect(f).not.toHaveBeenCalled()
    expect((q('ledger-token') as HTMLInputElement).type).toBe('password')
    await setInput(q('ledger-token') as HTMLInputElement, 'TOK')
    await click(q('ledger-load'))
    expect(calls.length).toBeGreaterThan(2)
    expect(calls.every((c) => c.auth === 'Bearer TOK' && c.url.startsWith('http://gen.test/ledger/'))).toBe(true)
  })

  it('shows accounts, formatted balances and the books-balance check with per-currency totals', async () => {
    const { f } = api()
    await load(f)
    expect(qa('ledger-account-row')).toHaveLength(3)
    expect(qa('ledger-balance-row')[0].textContent).toContain('1,234.56')
    expect(qa('ledger-balance-row')[1].textContent).toContain('-1,234.56')
    expect(qa('ledger-balance-row')[2].textContent).toContain('500')
    expect(qa('ledger-total-row')).toHaveLength(2)
    expect(qa('ledger-total-sum').map((e) => e.textContent)).toEqual(['0.00', '0'])
    expect(q('ledger-balance-check')?.dataset.ok).toBe('true')
    expect(q('ledger-balance-check')?.textContent).toMatch(/Books balance/)
  })

  it('flags books that do not balance', async () => {
    const { f } = api((_m, u) => (u.includes('/ledger/balances') ? json({ ...BAL, totals: [{ currency: 'USD', sum_minor: 5 }] }) : undefined))
    await load(f)
    expect(q('ledger-balance-check')?.dataset.ok).toBe('false')
    expect(q('ledger-balance-check')?.textContent).toMatch(/do NOT balance/)
  })

  it('expands a transaction into debit and credit columns', async () => {
    const { f } = api()
    await load(f)
    expect(q('ledger-tx-entries')).toBeNull()
    await click(q('ledger-tx-toggle'))
    const rows = qa('ledger-entry-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].querySelector('[data-testid="ledger-debit"]')?.textContent).toBe('1,234.56')
    expect(rows[0].querySelector('[data-testid="ledger-credit"]')?.textContent).toBe('')
    expect(rows[1].querySelector('[data-testid="ledger-credit"]')?.textContent).toBe('1,234.56')
    expect(q('ledger-tx-toggle')?.getAttribute('aria-expanded')).toBe('true')
  })

  it('shows the entry history of an account', async () => {
    const { f, calls } = api()
    await load(f)
    await click(qa('ledger-history-btn')[0])
    expect(calls.some((c) => c.url.includes('/ledger/accounts/a1/entries'))).toBe(true)
    expect(qa('ledger-history-row')).toHaveLength(1)
  })

  it('shows an error state (not a crash) when a 2xx answer is not the expected JSON', async () => {
    const html = () => new Response('<html>x</html>', { status: 200 })
    const { f } = api((_m, u) => (u.includes('/ledger/accounts') || u.includes('/ledger/balances') || u.includes('/ledger/transactions') ? html() : undefined))
    await load(f)
    expect(q('ledger-accounts-error')).not.toBeNull()
    expect(q('ledger-balances-state-error')).not.toBeNull()
    expect(q('ledger-transactions-state-error')).not.toBeNull()
  })

  it('pages through all accounts when the total is above one page', async () => {
    const mk = (i: number) => ({ id: `x${i}`, code: String(i), name: `A${i}`, kind: 'asset', currency: 'USD', exponent: 2 })
    const { f, calls } = api((_m, u) => {
      if (!/\/ledger\/accounts\?/.test(u)) return undefined
      const off = Number(new URL(u).searchParams.get('offset'))
      return json({ items: Array.from({ length: off === 0 ? 200 : 5 }, (_x, i) => mk(off + i)), total: 205, limit: 200, offset: off })
    })
    await load(f)
    expect(calls.filter((c) => /\/ledger\/accounts\?/.test(c.url)).map((c) => new URL(c.url).searchParams.get('offset'))).toEqual(['0', '200'])
    expect(qa('ledger-history-btn')).toHaveLength(205)
  })

  it('offers Show more when an account has more entries than one page', async () => {
    const ent = (i: number) => ({ id: `h${i}`, transaction_id: 't1', line_no: 1, currency: 'USD', amount_minor: 1, direction: 'debit', posted_at: '2026-01-01', description: 'd', reverses_id: null })
    const { f, calls } = api((_m, u) => {
      if (!u.includes('/entries')) return undefined
      const off = Number(new URL(u).searchParams.get('offset') ?? 0)
      return json({ items: off === 0 ? [ent(1), ent(2)] : [ent(3)], total: 3 })
    })
    await load(f)
    await click(qa('ledger-history-btn')[0])
    expect(qa('ledger-history-row')).toHaveLength(2)
    await click(q('ledger-history-more'))
    expect(calls.some((c) => c.url.includes('/entries') && c.url.includes('offset=2'))).toBe(true)
    expect(qa('ledger-history-row')).toHaveLength(3)
    expect(q('ledger-history-more')).toBeNull()
  })

  it('shows empty and error states', async () => {
    const { f } = api((_m, u) => (u.includes('/ledger/transactions') ? json({ items: [], total: 0, limit: 20, offset: 0 }) : u.includes('/ledger/balances') ? json({ code: 'forbidden', message: 'no', details: [] }, 403) : undefined))
    await load(f)
    expect(q('ledger-transactions-state-empty')).not.toBeNull()
    expect(q('ledger-balances-state-error')?.textContent).toMatch(/role may not/)
  })

  it('posts a balanced transaction in minor units with an auto key', async () => {
    const { f, calls } = api((m) => (m === 'POST' ? json(TX, 201) : undefined))
    await load(f)
    const key = (q('ledger-key') as HTMLInputElement).value
    expect(key.length).toBeGreaterThan(8)
    const [l1, l2] = qa('ledger-line')
    await setInput(l1.querySelector('[data-testid="ledger-line-account"]') as HTMLSelectElement, 'a1')
    await setInput(l1.querySelector('[data-testid="ledger-line-amount"]') as HTMLInputElement, '10.50')
    await setInput(l2.querySelector('[data-testid="ledger-line-account"]') as HTMLSelectElement, 'a2')
    await setInput(l2.querySelector('[data-testid="ledger-line-amount"]') as HTMLInputElement, '10.50')
    expect(q('ledger-draft-sum')?.textContent).toContain('USD: balanced')
    await click(q('ledger-post'))
    const post = calls.find((c) => c.m === 'POST')!
    expect(post.url).toBe('http://gen.test/ledger/transactions')
    expect(JSON.parse(post.body!)).toEqual({ idempotency_key: key, entries: [{ account_id: 'a1', amount_minor: 1050 }, { account_id: 'a2', amount_minor: -1050 }] })
    expect(q('ledger-post-ok')?.textContent).toMatch(/posted/)
    expect((q('ledger-key') as HTMLInputElement).value).not.toBe(key)
  })

  it('shows the unbalanced error from a 422 with per-currency details', async () => {
    const { f } = api((m) => (m === 'POST' ? json({ code: 'unbalanced', message: 'sum', details: [{ currency: 'USD', sum_minor: 100 }] }, 422) : undefined))
    await load(f)
    const [l1, l2] = qa('ledger-line')
    await setInput(l1.querySelector('[data-testid="ledger-line-account"]') as HTMLSelectElement, 'a1')
    await setInput(l1.querySelector('[data-testid="ledger-line-amount"]') as HTMLInputElement, '3')
    await setInput(l2.querySelector('[data-testid="ledger-line-account"]') as HTMLSelectElement, 'a2')
    await setInput(l2.querySelector('[data-testid="ledger-line-amount"]') as HTMLInputElement, '2')
    expect(q('ledger-draft-sum')?.textContent).toContain('USD: off by 1.00')
    await click(q('ledger-post'))
    expect(q('ledger-post-error')?.textContent).toMatch(/does not balance: USD is off by 1\.00/)
  })

  it('asks for confirmation before reversing, then shows already_reversed from a 409', async () => {
    const { f, calls } = api((m, u) => (m === 'POST' && u.includes('/reverse') ? json({ code: 'already_reversed', message: 'x', details: [] }, 409) : undefined))
    await load(f)
    await click(q('ledger-reverse-btn'))
    expect(q('ledger-reverse-confirm')).not.toBeNull()
    expect(calls.some((c) => c.m === 'POST')).toBe(false)
    await click(q('ledger-reverse-no'))
    expect(q('ledger-reverse-confirm')).toBeNull()
    await click(q('ledger-reverse-btn'))
    await click(q('ledger-reverse-yes'))
    expect(calls.find((c) => c.m === 'POST')?.url).toBe('http://gen.test/ledger/transactions/t1/reverse')
    expect(q('ledger-reverse-error')?.textContent).toBe('This transaction has already been reversed.')
  })

  it('has no axe violations (loaded, expanded, form present)', async () => {
    const { f } = api()
    const host = await load(f)
    await click(q('ledger-tx-toggle'))
    await click(q('ledger-reverse-btn'))
    await flush()
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
