/** F4-3: Operate > Metrics & reports (new shell only). Import a CSV through the API, create a metric and a report in the UI,
 *  and check the number on screen equals the API's number. Not run by the implementer;
 *  run with `npx playwright test e2e/metrics.spec.ts`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { API, createProjectViaApi, importInvoiceFlow, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

const CSV = 'invoice_no,amount,po_amount,status\nINV-1,100.10,100,draft\nINV-2,200.20,200,draft\nINV-3,300.30,300,draft\n'
const MAPPING = { invoice_no: 'invoice_no', amount: 'amount', po_amount: 'po_amount', status: 'status' }

for (const viewport of [{ name: 'desktop', width: 1280, height: 800 }, { name: 'phone', width: 375, height: 700 }]) {
  test(`metrics: create a metric and a report, the value matches the API (${viewport.name})`, async ({ page, request }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    const api = await signedInUser(page, request)
    const id = await createProjectViaApi(api, `Metrics ${viewport.name}`)
    await importInvoiceFlow(api, id)

    // Seed three invoices through the import API.
    const up = await request.post(`${API}/projects/${id}/imports`, {
      headers: { 'X-Requested-With': 'builder', Authorization: `Bearer ${api.token}` },
      multipart: { entity: 'Invoice', mapping: JSON.stringify(MAPPING), file: { name: 'invoices.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV) } },
    })
    expect(up.status(), await up.text()).toBeLessThan(300)
    const batch = (await up.json()).batch_id
    const commit = await api.post(`/projects/${id}/imports/${batch}/commit`)
    expect(commit.status(), await commit.text()).toBe(200)

    const watch = watchProblems(page)
    await page.goto(`/#/p/${id}/metrics`)
    await expect(page.getByRole('heading', { level: 1, name: 'Metrics & reports' })).toBeVisible()
    await expect(page.getByTestId('metrics-empty')).toBeVisible()

    // A metric.
    await page.getByRole('button', { name: 'New metric' }).click()
    await page.getByLabel('Key', { exact: true }).fill('total_billed')
    await page.getByLabel('Name', { exact: true }).fill('Total billed')
    await page.getByLabel('Entity').selectOption('Invoice')
    await page.getByLabel('Calculation').selectOption('sum')
    await page.getByLabel('Field', { exact: true }).selectOption('amount')
    await page.getByRole('button', { name: 'Create metric' }).click()
    const shown = page.getByTestId('metric-value-total_billed')
    await expect(shown).toBeVisible()

    const apiValue = (await (await api.get(`/projects/${id}/metrics/total_billed/value`)).json()).value as string
    expect(apiValue).toBe('600.6')
    await expect(shown).toHaveText('600.6')

    // A report that uses it.
    await page.getByRole('tab', { name: 'Reports' }).click()
    await expect(page.getByTestId('reports-empty')).toBeVisible()
    await page.getByRole('button', { name: 'New report' }).click()
    await page.getByLabel('Name', { exact: true }).fill('Weekly billing')
    await page.getByLabel('Schedule', { exact: true }).selectOption('weekdays')
    await page.getByLabel('Total billed', { exact: true }).check()
    await page.getByRole('button', { name: 'Create report' }).click()
    await expect(page.getByTestId('report-row')).toContainText('Weekly billing')
    await expect(page.getByTestId('report-row')).toContainText('Weekdays at 08:00')

    await page.getByRole('button', { name: 'Open report Weekly billing' }).click()
    await expect(page.getByTestId('report-value-total_billed')).toHaveText(apiValue)
    await page.getByRole('button', { name: 'Run now' }).click()
    await expect(page.getByTestId('report-run')).toContainText(`Total billed ${apiValue}`)

    const axe = await new AxeBuilder({ page }).analyze()
    expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the reports tab').toEqual([])

    await page.getByRole('tab', { name: 'Metrics' }).click()
    await expect(page.getByTestId('metric-value-total_billed')).toHaveText(apiValue)
    const axeMetrics = await new AxeBuilder({ page }).analyze()
    expect(axeMetrics.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the metrics tab').toEqual([])
    watch.assertNone()
  })
}
