/** CP-6F/6I: Operate > Invoices. Create a draft invoice, issue it, record a part payment, void another, read the aging.
 *  The generated project's API is mocked (see preview-mock.ts) behind the preview sign-in; the project is real.
 *  Not run by its author; run with `npx playwright test e2e/invoices.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

type Inv = { id: string; kind: 'receivable' | 'payable'; number: string | null; status: string; counterparty: string; currency: string; exponent: number; issue_date: string | null; due_date: string | null; total_minor: number; paid_minor: number; outstanding_minor: number }

test('invoices: create a draft, issue it, record a payment, void one, read the aging', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Invoices Project')

  const invs: Inv[] = []
  const bodies: Record<string, unknown>[] = []
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/invoices') {
      const qs = new URLSearchParams(r.search)
      const items = invs.filter((i) => (!qs.get('kind') || i.kind === qs.get('kind')) && (!qs.get('status') || i.status === qs.get('status')))
      return { json: { items, total: items.length, limit: 100, offset: 0 } }
    }
    if (r.method === 'GET' && r.path === '/invoices/aging') {
      const open = invs.filter((i) => i.kind === 'receivable' && (i.status === 'issued' || i.status === 'partially_paid'))
      const sum = open.reduce((s, i) => s + i.outstanding_minor, 0)
      return { json: { kind: 'receivable', as_of: '2026-11-22', bucket_days: [30, 60], currencies: open.length === 0 ? [] : [{ currency: 'USD', current_minor: sum, current_count: open.length, buckets: [{ label: '1-30', from_days: 1, to_days: 30, amount_minor: 0, count: 0 }, { label: '31-60', from_days: 31, to_days: 60, amount_minor: 0, count: 0 }], total_minor: sum, count: open.length }] } }
    }
    if (r.method === 'POST' && r.path === '/invoices') {
      bodies.push(r.body!)
      const b = r.body as { kind: 'receivable' | 'payable'; counterparty: string; currency: string; lines: { quantity: number; unit_price_minor: number }[] }
      const total = b.lines.reduce((s, l) => s + l.quantity * l.unit_price_minor, 0)
      invs.push({ id: `i${invs.length + 1}`, kind: b.kind, number: null, status: 'draft', counterparty: b.counterparty, currency: b.currency, exponent: 2, issue_date: null, due_date: null, total_minor: total, paid_minor: 0, outstanding_minor: total })
      return { status: 201, json: invs.at(-1) }
    }
    const act = /^\/invoices\/([^/]+)\/(issue|payments|void)$/.exec(r.path)
    if (r.method === 'POST' && act) {
      const inv = invs.find((i) => i.id === act[1])
      if (!inv) return { status: 404, json: { code: 'not_found', message: 'no invoice' } }
      if (act[2] === 'issue') { inv.status = 'issued'; inv.number = `INV-000${invs.indexOf(inv) + 1}` }
      if (act[2] === 'payments') {
        const amt = (r.body as { amount_minor: number }).amount_minor
        inv.paid_minor += amt; inv.outstanding_minor -= amt
        inv.status = inv.outstanding_minor === 0 ? 'paid' : 'partially_paid'
      }
      if (act[2] === 'void') inv.status = 'void'
      return { json: inv }
    }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/invoices`)
  await expect(page.getByRole('heading', { level: 1, name: 'Invoices' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)
  await expect(page.getByTestId('inv-list-empty')).toBeVisible()
  await expect(page.getByTestId('aging-empty')).toBeVisible()

  // A bad draft is refused locally, nothing is sent.
  await page.getByTestId('inv-create').click()
  await expect(page.getByTestId('inv-create-error')).toHaveText('Enter the customer or supplier name.')
  expect(seen.filter((s) => s.method === 'POST')).toHaveLength(0)

  // Create two drafts.
  for (const [who, price] of [['ACME Ltd', '100.00'], ['Globex', '30.50']] as const) {
    await page.getByTestId('inv-new-counterparty').fill(who)
    await page.getByTestId('inv-line-desc').fill('Consulting')
    await page.getByTestId('inv-line-qty').fill('2')
    await page.getByTestId('inv-line-price').fill(price)
    await page.getByTestId('inv-create').click()
    await expect(page.getByTestId('inv-create-ok')).toHaveText('Draft invoice created. Issue it from the list.')
  }
  expect(bodies[0]).toMatchObject({ kind: 'receivable', counterparty: 'ACME Ltd', currency: 'USD', lines: [{ description: 'Consulting', quantity: 2, unit_price_minor: 10000 }] })
  await expect(page.getByTestId('inv-row')).toHaveCount(2)
  await expect(page.getByTestId('inv-status')).toHaveText(['draft', 'draft'])
  await expect(page.getByTestId('inv-total-total')).toHaveText('261.00') // 200.00 + 61.00

  // Issue ACME, then part-pay it.
  await page.getByRole('button', { name: 'Issue invoice ACME Ltd' }).click()
  await expect(page.getByTestId('inv-notice')).toHaveText('Invoice issued.')
  const acme = page.getByTestId('inv-row').filter({ hasText: 'ACME Ltd' })
  await expect(acme.getByTestId('inv-status')).toHaveText('issued')
  await expect(acme).toContainText('INV-0001')
  await expect(page.getByTestId('aging-row')).toContainText('200.00 (1)')
  await page.getByRole('button', { name: 'Record payment for INV-0001' }).click()
  await page.getByTestId('inv-pay-amount').fill('50.00')
  await page.getByTestId('inv-pay-submit').click()
  await expect(page.getByTestId('inv-notice')).toHaveText('Payment recorded.')
  await expect(acme.getByTestId('inv-status')).toHaveText('partially_paid')
  const pay = seen.find((s) => s.path === '/invoices/i1/payments')!
  expect(pay.body).toMatchObject({ amount_minor: 5000 })
  expect(typeof pay.body?.idempotency_key).toBe('string')
  await expect(acme).toContainText('150.00') // outstanding
  await expect(page.getByTestId('aging-row')).toContainText('150.00 (1)')

  // Void Globex: asks first.
  await page.getByRole('button', { name: 'Void invoice Globex' }).click()
  await expect(page.getByTestId('inv-void-confirm')).toBeVisible()
  await page.getByTestId('inv-void-reason').fill('Duplicate')
  await page.getByTestId('inv-void-yes').click()
  await expect(page.getByTestId('inv-notice')).toHaveText('Invoice voided.')
  expect(seen.find((s) => s.path === '/invoices/i2/void')!.body).toEqual({ reason: 'Duplicate' })
  await expect(page.getByTestId('inv-row').filter({ hasText: 'Globex' }).getByTestId('inv-status')).toHaveText('void')

  // Filtering asks the server.
  await page.getByTestId('inv-filter-status').selectOption('void')
  await expect(page.getByTestId('inv-row')).toHaveCount(1)
  expect(seen.some((s) => s.path === '/invoices' && s.search.includes('status=void'))).toBe(true)
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'invoices page')
  watch.assertNone()
})
