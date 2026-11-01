/** F1-6B: Build > Seed data (new shell only). Refresh baselines with
 *  `npx playwright test e2e/seed.spec.ts --update-snapshots`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createProjectViaApi, signedInUser, watchProblems, type Api } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})
const FIXTURES = fileURLToPath(new URL('../../tests/fixtures/specs/', import.meta.url))

/** seed_demo.json without its seed profiles: the journeys add their own. */
async function importFixture(api: Api, projectId: string) {
  const spec = JSON.parse(readFileSync(FIXTURES + 'seed_demo.json', 'utf8'))
  spec.seed = []
  const r = await api.put(`/projects/${projectId}/spec`, spec)
  expect(r.status(), await r.text()).toBe(200)
}
const mask = (page: Page) => [page.locator('nav[data-shell="v2"] .muted, nav[data-shell="v2"] [data-testid=shell-project]')]
async function axeClean(page: Page, name: string) {
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), `axe on ${name}`).toEqual([])
}
const save = (page: Page) => page.getByRole('button', { name: 'Save', exact: true }).click()
const plan = (page: Page, entity: string) => page.getByRole('group', { name: `Plan for ${entity}` })

async function openPage(page: Page, id: string, info: { project: { name: string } }) {
  await page.goto(`/#/p/${id}/overview`)
  if (info.project.name === 'desktop') await page.locator('aside[data-sidebar]').getByRole('link', { name: 'Seed data' }).click()
  else await page.goto(`/#/p/${id}/seed`)
  await expect(page).toHaveURL(new RegExp(`#/p/${id}/seed$`))
  await expect(page.getByRole('heading', { level: 1, name: 'Seed data' })).toBeVisible()
}

test('seed: add a profile with two entity plans, save, reload, see it persisted', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Seed Desk')
  await importFixture(api, id)
  const watch = watchProblems(page)
  await openPage(page, id, info)
  await expect(page.getByTestId('seed-empty')).toContainText('Seed data is made-up sample rows')

  await page.getByRole('button', { name: 'Add a profile' }).click()
  const row = page.getByTestId('seed-row')
  await row.getByLabel('Profile name').fill('demo')
  await row.getByLabel('Seed number').fill('20261031')
  await row.getByLabel('As of date').fill('2026-10-01')
  await row.getByLabel('Tenants', { exact: true }).fill('2')

  // entity plans come from the project's entities; the required fields are offered in one click
  await page.getByLabel('Add an entity plan to demo').selectOption('Customer')
  const customers = plan(page, 'Customer')
  await customers.getByLabel('Rows').fill('5')
  await customers.getByRole('button', { name: /Add the 2 required fields \(name, email\)/ }).click()
  await expect(customers.getByTestId('field-plan')).toHaveCount(2)
  // pickers hold only possible combinations: the unique email column cannot take "words"
  await expect(customers.getByRole('group', { name: 'Customer.email' }).getByLabel('Generator').locator('option')).toHaveText(['sequence', 'email'])
  await customers.getByLabel('Add a field to fill in Customer').selectOption('active')
  await customers.getByRole('group', { name: 'Customer.active' }).getByLabel('Share of true values').fill('0.8')

  await page.getByLabel('Add an entity plan to demo').selectOption('Invoice')
  const invoices = plan(page, 'Invoice')
  await invoices.getByLabel('Rows').fill('8')
  await invoices.getByRole('button', { name: /Add the 4 required fields/ }).click()
  await expect(invoices.getByTestId('field-plan')).toHaveCount(4)
  await invoices.getByLabel('Add a field to fill in Invoice').selectOption('status')
  const status = invoices.getByRole('group', { name: 'Invoice.status' })
  await expect(status.getByLabel('Generator').locator('option')).toHaveText(['state'])
  await status.getByLabel('Weight of paid').fill('4')
  await invoices.getByRole('group', { name: 'Invoice.customer_id' }).getByLabel('How rows are chosen').selectOption('random')
  await invoices.getByRole('group', { name: 'Invoice.amount' }).getByLabel('Maximum').fill('900.00')

  await expect(row.getByTestId('cmd-seed')).toHaveText('python -m app.seed --profile demo')
  await save(page)
  await expect(page.getByTestId('save-note')).toContainText('Saved')
  await expect(page.getByTestId('issue-summary')).toHaveCount(0)
  await axeClean(page, `${info.project.name} editing`)

  await page.reload()
  await expect(page.getByTestId('seed-row')).toHaveCount(1)
  const saved = page.getByTestId('seed-row')
  await expect(saved.getByTestId('seed-summary')).toContainText('20261031')
  await expect(saved.getByTestId('seed-summary')).toContainText('2026-10-01')
  await expect(saved.getByTestId('seed-summary')).toContainText('Customer: 5 rows, 3 fields planned')
  await expect(saved.getByTestId('seed-summary')).toContainText('Invoice: 8 rows, 5 fields planned')
  await expect(saved.getByTestId('cmd-seed')).toHaveText('python -m app.seed --profile demo')
  await expect(saved.getByTestId('cmd-reset')).toHaveText('python -m app.seed --profile demo --reset')
  await expect(saved.getByTestId('cmd-check')).toHaveText('python -m app.seed --check')
  await expect(saved.getByTestId('seed-guard-note')).toContainText('refuses production-like environments')
  // the API holds what the page shows
  const body = await (await api.get(`/projects/${id}/behavior/seed`)).json()
  expect(body.seed[0].tenants).toBe(2)
  expect(body.seed[0].entities.map((e: { entity: string; count: number }) => [e.entity, e.count])).toEqual([['Customer', 5], ['Invoice', 8]])
  const amount = body.seed[0].entities[1].fields.find((f: { field: string }) => f.field === 'amount')
  expect(amount.generator).toMatchObject({ type: 'decimal_range', max: '900.00' })

  await saved.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(plan(page, 'Invoice').getByRole('group', { name: 'Invoice.status' }).getByLabel('Weight of paid')).toHaveValue('4')
  await saved.getByRole('button', { name: 'Done editing' }).click()
  await page.getByRole('heading', { level: 1, name: 'Seed data' }).scrollIntoViewIfNeeded()
  await page.waitForTimeout(300)
  await expect.soft(page).toHaveScreenshot('seed-list.png', { mask: mask(page) })
  await axeClean(page, `${info.project.name} list`)
  watch.assertNone()
})

test('seed: the backend message shows next to the part; a stale save is a conflict; remove', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Seed Desk 2')
  await importFixture(api, id)
  await openPage(page, id, info)

  await page.getByRole('button', { name: 'Add a profile' }).click()
  const row = page.getByTestId('seed-row')
  await page.getByLabel('Add an entity plan to demo').selectOption('Customer')
  await plan(page, 'Customer').getByRole('button', { name: /Add the 2 required fields/ }).click()
  await page.getByLabel('Add an entity plan to demo').selectOption('Invoice')
  const invoices = plan(page, 'Invoice')
  await invoices.getByRole('button', { name: /Add the 4 required fields/ }).click()
  // a plan the UI lets through but the backend refuses: min above max, and tenants left at 0 for tenant-owned entities
  const amount = invoices.getByRole('group', { name: 'Invoice.amount' })
  await amount.getByLabel('Minimum').fill('900.00')
  await amount.getByLabel('Maximum').fill('20.00')
  await save(page)
  await expect(page.getByTestId('save-note')).toContainText('Saved') // work in progress is stored; issues come back
  await expect(page.getByTestId('issue-summary')).toContainText('problem')
  await expect(amount.getByTestId('field-error')).toHaveText('min is greater than max')
  await expect(amount.getByLabel('Minimum')).toHaveAttribute('aria-invalid', 'true')
  await expect(plan(page, 'Customer').getByTestId('field-error').first()).toHaveText('Customer belongs to a tenant: set tenants to 1 or more')
  await expect(row.getByTestId('seed-issues')).toContainText('min is greater than max')
  await page.getByRole('heading', { level: 1, name: 'Seed data' }).scrollIntoViewIfNeeded()
  await page.waitForTimeout(300)
  await expect.soft(page).toHaveScreenshot('seed-issue.png', { mask: mask(page) })
  await axeClean(page, `${info.project.name} with issues`)

  // fix it: the message goes away with the edit and the next save is clean
  await row.getByLabel('Tenants', { exact: true }).fill('1')
  await amount.getByLabel('Minimum').fill('10.00')
  await save(page)
  await expect(page.getByTestId('issue-summary')).toHaveCount(0)

  // another writer saved in between: conflict, then Reload shows the server's version
  const cur = await (await api.get(`/projects/${id}/behavior/seed`)).json()
  const put = await api.put(`/projects/${id}/behavior/seed`, { seed: [{ ...cur.seed[0], name: 'other' }], expected_version: cur.version })
  expect(put.status(), await put.text()).toBe(200)
  await row.getByLabel('Seed number').fill('99')
  await save(page)
  await expect(page.getByTestId('conflict')).toBeVisible()
  await page.getByTestId('conflict').getByRole('button', { name: 'Reload' }).click()
  await expect(page.getByTestId('conflict')).toHaveCount(0)
  await expect(page.getByTestId('seed-row').locator('legend')).toHaveText('other')

  await page.getByRole('button', { name: 'Remove profile other' }).click()
  await save(page)
  await expect(page.getByTestId('save-note')).toContainText('Saved')
  await page.reload()
  await expect(page.getByTestId('seed-empty')).toBeVisible()
})

test('seed: empty and error states', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Empty Seed')
  await page.goto(`/#/p/${id}/seed`)
  await expect(page.getByTestId('seed-empty')).toBeVisible()
  await expect(page.getByText('Seed data is made-up sample rows').first()).toBeVisible()
  await page.getByRole('button', { name: 'Add a profile' }).click()
  await expect(page.getByText('Add an entity in the data model first')).toBeVisible()
  await page.route('**/behavior/seed', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ code: 'boom', message: 'Backend exploded' }) }),
  )
  await page.reload()
  await expect(page.getByRole('alert').filter({ hasText: 'We could not load seed profiles' })).toBeVisible()
  await page.unroute('**/behavior/seed')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByTestId('seed-empty')).toBeVisible()
})
