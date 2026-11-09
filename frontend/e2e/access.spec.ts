/** F4-4: Build > Access matrix (new shell only). Editing a rule shows the diff BEFORE it is applied.
 *  Not run by the implementer; run with `npx playwright test e2e/access.spec.ts`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { createProjectViaApi, importInvoiceFlow, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

test('access: change one rule, see who gains access before applying', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Access Matrix')
  await importInvoiceFlow(api, id)
  const watch = watchProblems(page)
  await page.goto(`/#/p/${id}/permissions`)
  await expect(page.getByRole('heading', { level: 1, name: 'Access' })).toBeVisible()

  const table = page.getByRole('table', { name: /Object access for Invoice/ })
  await expect(table).toBeVisible()
  await expect(table.getByRole('rowheader', { name: 'clerk' })).toBeVisible()

  // the clerk may not update invoices today: tick the box and read the review before anything is saved
  await page.getByLabel('Operation', { exact: true }).selectOption('update')
  await page.getByRole('checkbox', { name: 'clerk' }).check()
  const review = page.getByTestId('access-review')
  await expect(review.getByRole('heading', { name: 'Review changes' })).toBeVisible()
  await expect(review.getByTestId('access-diff-lines')).toContainText('Role clerk gains')
  await expect(review.getByTestId('access-weakens')).toBeVisible()
  await expect(review.getByRole('button', { name: 'Apply and confirm more access' })).toBeVisible()

  // nothing was saved yet
  const before = await (await api.get(`/projects/${id}/access/matrix`)).json()
  const cell = (m: { cells: { layer: string; entity: string; target: string; role: string; value: string }[] }) =>
    m.cells.find((c) => c.layer === 'object' && c.entity === 'Invoice' && c.target === 'update' && c.role === 'clerk')?.value
  expect(cell(before)).toBe('no')

  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the access page').toEqual([])

  await review.getByRole('button', { name: 'Apply and confirm more access' }).click()
  await expect(review).toHaveCount(0)
  await expect(table.getByRole('row', { name: /^clerk/ })).toContainText('yes')
  const after = await (await api.get(`/projects/${id}/access/matrix`)).json()
  expect(cell(after)).toBe('yes')
  watch.assertNone()
})
