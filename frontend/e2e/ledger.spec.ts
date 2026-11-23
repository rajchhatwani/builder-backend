/** F5-1: Operate > Ledger (new shell). Sign in to the preview, load the books, post a balanced entry, see the balances move.
 *  The project API is mocked (see preview-mock.ts). Not run by its author; run with `npx playwright test e2e/ledger.spec.ts`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'
import { BEARER, SESSION, mockPreviewSession, signInPreview } from './preview-mock'


const ACCTS = [
  { id: 'a1', code: '1000', name: 'Cash', kind: 'asset', currency: 'USD', exponent: 2 },
  { id: 'a2', code: '4000', name: 'Sales', kind: 'income', currency: 'USD', exponent: 2 },
]

test('ledger: post a balanced transaction, the balances and history follow', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Ledger Project')

  type Tx = { id: string; idempotency_key: string; description: string | null; reference: string | null; reverses_id: null; reversed_by_id: null; posted_at: string; posted_by: null; entries: { id: string; line_no: number; account_id: string; currency: string; amount_minor: number; direction: string }[] }
  const txs: Tx[] = []
  const balances = () => {
    const items = ACCTS.map((a) => {
      const amts = txs.flatMap((t) => t.entries).filter((e) => e.account_id === a.id).map((e) => e.amount_minor)
      const debit = amts.filter((n) => n > 0).reduce((s, n) => s + n, 0)
      const credit = amts.filter((n) => n < 0).reduce((s, n) => s + n, 0)
      return { account_id: a.id, code: a.code, name: a.name, currency: a.currency, exponent: a.exponent, balance_minor: debit + credit, debit_total_minor: debit, credit_total_minor: credit }
    })
    return { items, totals: [{ currency: 'USD', sum_minor: items.reduce((s, b) => s + b.balance_minor, 0) }] }
  }
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/ledger/accounts') return { json: { items: ACCTS, total: 2, limit: 200, offset: 0 } }
    if (r.method === 'GET' && r.path === '/ledger/balances') return { json: balances() }
    if (r.method === 'GET' && r.path === '/ledger/transactions') return { json: { items: [...txs].reverse(), total: txs.length, limit: 20, offset: 0 } }
    const hist = /^\/ledger\/accounts\/([^/]+)\/entries$/.exec(r.path)
    if (r.method === 'GET' && hist) {
      const rows = txs.flatMap((t) => t.entries.filter((e) => e.account_id === hist[1]).map((e) => ({ id: `h-${e.id}`, transaction_id: t.id, line_no: e.line_no, currency: e.currency, amount_minor: e.amount_minor, direction: e.direction, posted_at: t.posted_at, description: t.description, reverses_id: null })))
      return { json: { items: rows, total: rows.length } }
    }
    if (r.method === 'POST' && r.path === '/ledger/transactions') {
      const b = r.body as { idempotency_key: string; description?: string; reference?: string; entries: { account_id: string; amount_minor: number }[] }
      const tx: Tx = {
        id: `t${txs.length + 1}`, idempotency_key: b.idempotency_key, description: b.description ?? null, reference: b.reference ?? null, reverses_id: null, reversed_by_id: null,
        posted_at: new Date().toISOString(), posted_by: null,
        entries: b.entries.map((e, i) => ({ id: `e${txs.length + 1}-${i}`, line_no: i + 1, account_id: e.account_id, currency: 'USD', amount_minor: e.amount_minor, direction: e.amount_minor > 0 ? 'debit' : 'credit' })),
      }
      txs.push(tx)
      return { status: 201, json: tx }
    }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/ledger`)
  await expect(page.getByTestId('ledger-page')).toBeVisible()
  expect(seen).toHaveLength(0) // nothing is fetched before a token is given
  await signInPreview(page)

  await expect(page.getByTestId('ledger-account-row')).toHaveCount(2)
  await expect(page.getByTestId('ledger-transactions-state-empty')).toBeVisible()
  await expect(page.getByTestId('ledger-balance-row')).toHaveCount(2)
  await expect(page.getByTestId('ledger-balance-check')).toHaveAttribute('data-ok', 'true')
  expect(seen.every((s) => s.auth === BEARER && s.previewToken === SESSION.previewToken && !s.search.includes(SESSION.jwt))).toBe(true)

  // An unbalanced draft is called out before anything is sent.
  const accounts = page.getByTestId('ledger-line-account')
  const amounts = page.getByTestId('ledger-line-amount')
  await accounts.nth(0).selectOption('a1')
  await accounts.nth(1).selectOption('a2')
  await page.getByTestId('ledger-line-side').nth(1).selectOption('credit')
  await amounts.nth(0).fill('123.45')
  await amounts.nth(1).fill('100.00')
  await expect(page.getByTestId('ledger-draft-sum')).toHaveText('USD: off by 23.45')
  await amounts.nth(1).fill('123.45')
  await expect(page.getByTestId('ledger-draft-sum')).toHaveText('USD: balanced')
  await page.getByTestId('ledger-description').fill('Invoice INV-7')
  await page.getByTestId('ledger-reference').fill('INV-7')
  await page.getByTestId('ledger-post').click()
  await expect(page.getByTestId('ledger-post-ok')).toHaveText('Transaction posted.')

  const post = seen.filter((s) => s.method === 'POST')
  expect(post).toHaveLength(1)
  expect(post[0].path).toBe('/ledger/transactions')
  expect(post[0].body).toMatchObject({
    description: 'Invoice INV-7', reference: 'INV-7',
    entries: [{ account_id: 'a1', amount_minor: 12345 }, { account_id: 'a2', amount_minor: -12345 }],
  })
  expect(typeof post[0].body?.idempotency_key).toBe('string')
  expect((post[0].body?.idempotency_key as string).length).toBeGreaterThan(8)

  // Balances, totals and the transaction list reflect it.
  const cash = page.getByTestId('ledger-balance-row').filter({ hasText: '1000 Cash' })
  await expect(cash).toContainText('123.45')
  await expect(page.getByTestId('ledger-balance-row').filter({ hasText: '4000 Sales' })).toContainText('-123.45')
  await expect(page.getByTestId('ledger-total-sum')).toHaveText('0.00')
  await expect(page.getByTestId('ledger-balance-check')).toHaveAttribute('data-ok', 'true')
  const row = page.getByTestId('ledger-tx-row')
  await expect(row).toHaveCount(1)
  await expect(row).toContainText('Invoice INV-7')
  await expect(row).toContainText('Posted')
  await page.getByTestId('ledger-tx-toggle').click()
  await expect(page.getByTestId('ledger-entry-row')).toHaveCount(2)
  await expect(page.getByTestId('ledger-entry-row').first().getByTestId('ledger-debit')).toHaveText('123.45')
  await expect(page.getByTestId('ledger-entry-row').nth(1).getByTestId('ledger-credit')).toHaveText('123.45')

  // Per-account history.
  await page.getByRole('button', { name: 'Entry history of 1000' }).click()
  await expect(page.getByTestId('ledger-history-row')).toHaveCount(1)
  await expect(page.getByTestId('ledger-history-row')).toContainText('Invoice INV-7')

  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the ledger page').toEqual([])
  watch.assertNone()
})
