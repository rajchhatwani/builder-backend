/** F4-5: Operate > Traces (new shell only). Load the example, open the rule span, land on the Rules page.
 *  Not run by the implementer; run with `npx playwright test e2e/traces.spec.ts`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

for (const [label, size] of [['desktop', { width: 1280, height: 800 }], ['phone', { width: 375, height: 700 }]] as const) {
  test(`traces (${label}): load example, open the rule span, land on Rules`, async ({ page, request }) => {
    await page.setViewportSize(size)
    const api = await signedInUser(page, request)
    const id = await createProjectViaApi(api, `Traces ${label}`)
    const watch = watchProblems(page)
    await page.goto(`/#/p/${id}/traces`)
    await expect(page.getByRole('heading', { level: 1, name: 'Traces' })).toBeVisible()
    await expect(page.getByTestId('traces-empty')).toBeVisible()

    await page.getByRole('button', { name: 'Load example' }).click()
    await expect(page.getByTestId('trace-row')).toHaveCount(7)
    await expect(page.getByTestId('trace-row').filter({ hasText: 'ERROR' })).toHaveCount(1)

    await page.getByTestId('trace-row').filter({ hasText: 'rule invoice_within_limit' }).click()
    const detail = page.getByTestId('span-detail')
    await expect(detail.getByRole('heading', { name: 'rule invoice_within_limit' })).toBeVisible()

    const axe = await new AxeBuilder({ page }).analyze()
    expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the traces page').toEqual([])

    await detail.getByRole('link', { name: /Open Rules for rule invoice_within_limit/ }).click()
    await expect(page).toHaveURL(new RegExp(`#/p/${id}/rules$`))
    await expect(page.getByRole('heading', { level: 1, name: 'Rules' })).toBeVisible()
    watch.assertNone()
  })
}
