/** CP-6F/6I: Operate > Payouts. Pick a fully paid invoice, name the seller, confirm, see the payout and the totals.
 *  The generated project's API is mocked (see preview-mock.ts) behind the preview sign-in; the project is real.
 *  Not run by its author; run with `npx playwright test e2e/payouts.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

test('payouts: run one payout for a paid invoice, with a confirmation', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Payouts Project')

  const paidInvoice = { id: 'i1', kind: 'receivable', number: 'INV-0007', status: 'paid', counterparty: 'Buyer Inc', currency: 'USD', exponent: 2, issue_date: '2026-11-01', due_date: '2026-11-15', total_minor: 20000, paid_minor: 20000, outstanding_minor: 0 }
  const payouts: { id: string; invoice_id: string; seller: string; currency: string; gross_minor: number; commission_bp: number; commission_minor: number; seller_minor: number; created_at: string }[] = []
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/payouts') return { json: { items: payouts, total: payouts.length, limit: 100, offset: 0 } }
    if (r.method === 'GET' && r.path === '/payouts/totals') {
      return { json: payouts.map((p) => ({ seller: p.seller, currency: p.currency, count: 1, gross_minor: p.gross_minor, commission_minor: p.commission_minor, seller_minor: p.seller_minor })) }
    }
    if (r.method === 'GET' && r.path === '/invoices') return { json: { items: [paidInvoice], total: 1, limit: 200, offset: 0 } }
    if (r.method === 'POST' && r.path === '/payouts/run') {
      const b = r.body as { invoice_id: string; seller: string }
      payouts.push({ id: 'p1', invoice_id: b.invoice_id, seller: b.seller, currency: 'USD', gross_minor: 20000, commission_bp: 1000, commission_minor: 2000, seller_minor: 18000, created_at: '2026-11-22T10:00:00Z' })
      return { status: 201, json: payouts[0] }
    }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/payouts`)
  await expect(page.getByRole('heading', { level: 1, name: 'Payouts' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)
  await expect(page.getByTestId('payout-list-empty')).toBeVisible()
  await expect(page.getByTestId('payout-invoice')).toContainText('INV-0007 Buyer Inc (USD 200.00)')

  // A bad seller label is refused locally, nothing is sent.
  await page.getByTestId('payout-invoice').selectOption('i1')
  await page.getByTestId('payout-seller').fill('bad seller!')
  await page.getByTestId('payout-run').click()
  await expect(page.getByTestId('payout-error')).toContainText('Seller must be 1-64 characters')
  expect(seen.filter((s) => s.method === 'POST')).toHaveLength(0)

  // Confirmation first, then the call.
  await page.getByTestId('payout-seller').fill('seller-42')
  await page.getByTestId('payout-run').click()
  await expect(page.getByTestId('payout-confirm')).toContainText('Pay out USD 200.00 for INV-0007 to seller seller-42')
  expect(seen.filter((s) => s.method === 'POST')).toHaveLength(0)
  await page.getByTestId('payout-yes').click()
  await expect(page.getByTestId('payout-ok')).toHaveText('Payout run.')
  const run = seen.find((s) => s.path === '/payouts/run')!
  expect(run.body).toMatchObject({ invoice_id: 'i1', seller: 'seller-42' })
  expect(typeof run.body?.idempotency_key).toBe('string')

  await expect(page.getByTestId('payout-row')).toHaveCount(1)
  await expect(page.getByTestId('payout-row')).toContainText('seller-42')
  await expect(page.getByTestId('payout-row')).toContainText('180.00')
  await expect(page.getByTestId('payout-total-seller')).toHaveText('180.00')
  // The invoice that was paid out no longer offers itself.
  await expect(page.getByTestId('payout-no-candidates')).toBeVisible()
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'payouts page')
  watch.assertNone()
})
