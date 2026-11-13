/** F5-4: Operate > Documents review queue (new shell). Open a flagged document, correct the wrong field, approve it.
 *  The project API is mocked (see preview-mock.ts). Not run by its author; run with `npx playwright test e2e/documents.spec.ts`.
 *  The v2 "documents" route also renders the older PDF-templates panel above the queue, so axe is scoped to the queue page. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'
import { V2_STATE, mockPreview } from './preview-mock'

test.use({ storageState: V2_STATE })

const TOKEN = 'e2e-documents-' + 'token-1'
const TEXT = 'Invoice No: INV-0042\nTotal due: 1,250.00 USD\nDate: 2026-03-01'
const at = (quote: string) => ({ page: 1, start: TEXT.indexOf(quote), end: TEXT.indexOf(quote) + quote.length, quote })

type Field = { name: string; value: string | null; confidence_bp: number; anchor: ReturnType<typeof at> | null; corrected: boolean; original_value: string | null; review_required: boolean }

test('documents: correct a low-confidence field, approve the document', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Documents Project')

  const fields: Field[] = [
    { name: 'invoice_number', value: 'INV-0042', confidence_bp: 9800, anchor: at('INV-0042'), corrected: false, original_value: null, review_required: false },
    { name: 'total', value: '1,205.00', confidence_bp: 6000, anchor: at('1,250.00'), corrected: false, original_value: null, review_required: true },
  ]
  const doc = { id: 'd1', kind: 'invoice', title: 'Invoice ACME 0042', status: 'needs_review', call_id: null, reject_reason: null, content: TEXT, fields }
  const summary = () => ({ id: doc.id, kind: doc.kind, title: doc.title, status: doc.status, fields: doc.fields })
  const seen = await mockPreview(page, (r) => {
    if (r.method === 'GET' && r.path === '/ai/documents') {
      const st = new URLSearchParams(r.search).get('status')
      const items = doc.status === st ? [summary()] : []
      return { json: { items, total: items.length, limit: 20, offset: 0 } }
    }
    if (r.method === 'GET' && r.path === '/ai/documents/d1') return { json: doc }
    if (r.method === 'POST' && r.path === '/ai/documents/d1/fields/total/correct') {
      const f = doc.fields[1]
      Object.assign(f, { original_value: f.value, value: (r.body as { value: string }).value, corrected: true, confidence_bp: 10000, review_required: false })
      return { json: doc }
    }
    if (r.method === 'POST' && r.path === '/ai/documents/d1/approve') {
      if (doc.fields.some((f) => f.review_required)) return { status: 409, json: { code: 'review_pending', message: 'fields pending', details: [{ name: 'total' }] } }
      doc.status = 'approved'
      return { json: doc }
    }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/documents`)
  await expect(page.getByTestId('documents-page')).toBeVisible()
  await expect(page.getByTestId('documents-notoken')).toBeVisible()
  expect(seen).toHaveLength(0)
  await page.getByTestId('documents-token').fill(TOKEN)
  await page.getByTestId('documents-load').click()

  await expect(page.getByTestId('documents-live')).toHaveText('1 Needs review document, showing 1 to 1.')
  expect(seen.find((s) => s.path === '/ai/documents')!.search).toBe('?status=needs_review&limit=20&offset=0')
  await page.getByTestId('document-row-d1').click()

  // Evidence is highlighted in the text and the weak field is flagged.
  await expect(page.getByTestId('document-detail').getByRole('heading', { name: /Invoice ACME 0042/ })).toBeVisible()
  await expect(page.getByTestId('highlight-invoice_number')).toHaveText('INV-0042')
  await expect(page.getByTestId('highlight-total')).toHaveText('1,250.00')
  await expect(page.getByTestId('field-value-total')).toHaveText('1,205.00')
  await expect(page.getByTestId('field-confidence-invoice_number')).toHaveText('98%')
  await expect(page.getByTestId('field-low-total')).toBeVisible()
  await expect(page.getByTestId('field-low-invoice_number')).toHaveCount(0)

  // Correct the wrong total.
  await page.getByTestId('field-edit-total').click()
  await page.getByTestId('field-correct-total').fill('1250.00')
  await page.getByTestId('field-save-total').click()
  await expect(page.getByTestId('document-notice')).toHaveText('Field total corrected.')
  const corr = seen.find((s) => s.method === 'POST' && s.path === '/ai/documents/d1/fields/total/correct')!
  expect(corr.body).toEqual({ value: '1250.00' })
  await expect(page.getByTestId('field-value-total')).toHaveText('1250.00')
  await expect(page.getByTestId('field-row-total')).toContainText('corrected, was 1,205.00')
  await expect(page.getByTestId('field-low-total')).toHaveCount(0)

  // Approve.
  await page.getByTestId('approve-btn').click()
  await expect(page.getByTestId('document-notice')).toHaveText('Document approved.')
  const appr = seen.filter((s) => s.method === 'POST' && s.path === '/ai/documents/d1/approve')
  expect(appr).toHaveLength(1)
  expect(appr[0].body).toBeNull() // nothing to acknowledge
  await expect(page.getByTestId('document-status')).toHaveText('Approved')
  await expect(page.getByTestId('approve-btn')).toBeDisabled()
  await expect(page.getByTestId('review-disabled-note')).toContainText('final')
  await expect(page.getByTestId('documents-empty')).toBeVisible() // it left the needs-review queue

  // It is now under Approved.
  await page.getByTestId('status-filter').selectOption('approved')
  await expect(page.getByTestId('document-row-d1')).toBeVisible()
  expect(seen.some((s) => s.path === '/ai/documents' && s.search.startsWith('?status=approved'))).toBe(true)
  expect(seen.every((s) => s.auth === `Bearer ${TOKEN}` && !s.search.includes(TOKEN))).toBe(true)

  const axe = await new AxeBuilder({ page }).include('[data-testid="documents-page"]').analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the documents queue').toEqual([])
  watch.assertNone()
})
