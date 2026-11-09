/** F4-1: Connect > Import data (new shell only). CSV with 3 rows, one bad; fix it, commit.
 *  Not run by the implementer; run with `npx playwright test e2e/import.spec.ts`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { createProjectViaApi, importInvoiceFlow, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

const CSV = 'invoice_no,amount,po_amount,status\nINV-1,100,100,draft\nINV-2,200,200,draft\nINV-3,abc,300,draft\n'

for (const viewport of [{ name: 'desktop', width: 1280, height: 800 }, { name: 'phone', width: 375, height: 700 }]) {
  test(`import: preview, fix the bad row, commit (${viewport.name})`, async ({ page, request }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    const api = await signedInUser(page, request)
    const id = await createProjectViaApi(api, `Import ${viewport.name}`)
    await importInvoiceFlow(api, id)
    const watch = watchProblems(page)
    await page.goto(`/#/p/${id}/import`)
    await expect(page.getByRole('heading', { level: 1, name: 'Import data' })).toBeVisible()

    await page.getByLabel('Entity').selectOption('Invoice')
    await page.getByLabel('CSV file').setInputFiles({ name: 'invoices.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV) })
    await page.getByRole('button', { name: 'Upload and preview' }).click()
    await expect(page.getByTestId('import-summary')).toHaveText('3 rows, 2 ready, 1 need fixing')
    await expect(page.getByLabel('Column for amount')).toHaveValue('amount')

    const axeMapping = await new AxeBuilder({ page }).analyze()
    expect(axeMapping.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the mapping step').toEqual([])

    await page.getByRole('button', { name: 'Continue' }).click()
    const bad = page.getByTestId('import-row')
    await expect(bad).toContainText('Row 3')
    await expect(bad).toContainText('amount')
    await bad.getByLabel('Fix amount (row 3)').fill('300')
    await bad.getByRole('button', { name: 'Save row 3' }).click()
    await expect(page.getByTestId('import-no-problems')).toBeVisible()
    await expect(page.getByTestId('import-summary')).toHaveText('3 rows, 3 ready, 0 need fixing')

    const axeReview = await new AxeBuilder({ page }).analyze()
    expect(axeReview.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the review step').toEqual([])

    await page.getByRole('button', { name: 'Commit 3 rows' }).click()
    await expect(page.getByTestId('import-result')).toContainText('3 created, 0 already imported, 0 rejected')
    await expect(page.getByTestId('import-records')).toContainText('INV-1')
    const axeDone = await new AxeBuilder({ page }).analyze()
    expect(axeDone.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the done step').toEqual([])
    watch.assertNone()
  })
}
