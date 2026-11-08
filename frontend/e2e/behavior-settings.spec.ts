/** F1-6A: Build > Settings (settings, sequences, lists) and Build > Change history (new shell only).
 *  Refresh baselines with `npx playwright test e2e/behavior-settings.spec.ts --update-snapshots`. */
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

async function importFixture(api: Api, projectId: string, file: string) {
  const spec = JSON.parse(readFileSync(FIXTURES + file, 'utf8'))
  const r = await api.put(`/projects/${projectId}/spec`, spec)
  expect(r.status(), await r.text()).toBe(200)
}
const row = (page: Page, name: string) => page.getByTestId('setting-row').filter({ has: page.locator(`legend:text-is("${name}")`) })
const mask = (page: Page) => [page.locator('nav[data-shell="v2"] .muted, nav[data-shell="v2"] [data-testid=shell-project]')]
async function axeClean(page: Page, name: string) {
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), `axe on ${name}`).toEqual([])
}

test('settings: edit a setting, a sequence and a list, save, reload, still there', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Order Desk')
  await importFixture(api, id, 'runtime_config.json')
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/overview`)
  if (info.project.name === 'desktop') await page.locator('aside[data-sidebar]').getByRole('link', { name: 'Settings' }).click()
  else await page.goto(`/#/p/${id}/settings`)
  await expect(page).toHaveURL(new RegExp(`#/p/${id}/settings$`))
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
  await expect(page.getByTestId('setting-row')).toHaveCount(4)

  await row(page, 'approval_threshold').getByLabel('Default value').fill('2500')
  await expect(page.getByText('Unsaved changes')).toBeVisible()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-note')).toContainText('Saved')

  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: 'Sequences' }).click()
  const seq = page.getByTestId('sequence-row').first()
  await expect(seq.getByLabel('Name')).toHaveValue('invoice_no')
  await seq.getByLabel('Digits (padding)').fill('6')
  await expect(seq.getByTestId('seq-preview')).toHaveText('INV-000001')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-note')).toContainText('Saved')

  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: 'Lists' }).click()
  await page.getByRole('button', { name: 'Add item' }).click()
  const items = page.getByTestId('list-item-row')
  await expect(items).toHaveCount(5)
  await items.nth(4).getByLabel('Value of item 5').fill('returned')
  await items.nth(4).getByLabel('Label of item 5').fill('Returned')
  await items.nth(4).getByLabel('Colour of item 5').fill('#aa3300')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-note')).toContainText('Saved')

  await page.reload()
  await expect(row(page, 'approval_threshold').getByLabel('Default value')).toHaveValue('2500')
  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: 'Sequences' }).click()
  await expect(page.getByTestId('sequence-row').first().getByLabel('Digits (padding)')).toHaveValue('6')
  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: 'Lists' }).click()
  await expect(page.getByTestId('list-item-row')).toHaveCount(5)
  await expect(page.getByLabel('Value of item 5')).toHaveValue('returned')

  await page.waitForTimeout(300)
  await expect.soft(page).toHaveScreenshot('settings-lists.png', { mask: mask(page) })
  await axeClean(page, info.project.name)
  watch.assertNone()
})

test('settings: backend validation message next to the field, and a stale save is a conflict', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Order Desk 2')
  await importFixture(api, id, 'runtime_config.json')
  await page.goto(`/#/p/${id}/settings`)
  const vat = row(page, 'vat_rate')
  await vat.getByLabel('Default value').fill('5')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  // saved (work in progress is allowed), and the validator's own message sits under the field
  await expect(page.getByTestId('issue-summary')).toContainText('1 problem')
  await expect(vat.getByTestId('field-error')).toHaveText('default is above the maximum')
  await expect(vat.getByLabel('Default value')).toHaveAttribute('aria-invalid', 'true')
  await page.waitForTimeout(300)
  await expect.soft(page).toHaveScreenshot('settings-issue.png', { mask: mask(page) })
  await axeClean(page, `${info.project.name} with issues`)

  // someone else saves the section first -> our next save gets 409 and a reload prompt
  const cur = await (await api.get(`/projects/${id}/behavior/settings`)).json()
  const put = await api.put(`/projects/${id}/behavior/settings`, { settings: cur.settings, expected_version: cur.version })
  expect(put.status()).toBe(200)
  await vat.getByLabel('Default value').fill('0.5')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('conflict')).toBeVisible()
  await page.getByTestId('conflict').getByRole('button', { name: 'Reload' }).click()
  await expect(page.getByTestId('conflict')).toHaveCount(0)
  await expect(vat.getByLabel('Default value')).toHaveValue('5')
})

test('settings: empty and error states', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Empty Settings')
  await page.goto(`/#/p/${id}/settings`)
  await expect(page.getByTestId('settings-empty')).toBeVisible()
  await expect(page.getByText('Runtime settings are values').first()).toBeVisible()
  await page.route('**/behavior/settings', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ code: 'boom', message: 'Backend exploded' }) }),
  )
  await page.reload()
  await expect(page.getByRole('alert').filter({ hasText: 'We could not load settings' })).toBeVisible()
  await page.unroute('**/behavior/settings')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByTestId('settings-empty')).toBeVisible()
})

test('history: change audited fields and retention, save, reload; secret fields are disabled', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Notes Trail')
  await importFixture(api, id, 'history_notes.json')
  const ents = await (await api.get(`/projects/${id}/entities`)).json()
  const note = ents.items.find((e: { name: string }) => e.name === 'Note')
  const f = await api.post(`/entities/${note.id}/fields`, { name: 'api_token', type: 'string', required: false, unique: false, indexed: false })
  expect(f.status(), await f.text()).toBe(201)
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/overview`)
  if (info.project.name === 'desktop') await page.locator('aside[data-sidebar]').getByRole('link', { name: 'Change history' }).click()
  else await page.goto(`/#/p/${id}/history`)
  await expect(page).toHaveURL(new RegExp(`#/p/${id}/history$`))
  await expect(page.getByRole('heading', { level: 1, name: 'Change history' })).toBeVisible()
  const noteRow = page.getByTestId('history-row').filter({ has: page.locator('legend:text-is("Note")') })
  await expect(noteRow.getByLabel('title')).toBeChecked()
  await expect(noteRow.getByLabel('private_note')).not.toBeChecked()
  await expect(noteRow.getByLabel('api_token')).toBeDisabled()
  await expect(noteRow).toContainText('Looks like a secret')

  await noteRow.getByLabel('private_note').check()
  await noteRow.getByLabel('Keep for (days)').fill('120')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-note')).toContainText('Saved')
  await page.reload()
  const after = page.getByTestId('history-row').filter({ has: page.locator('legend:text-is("Note")') })
  await expect(after.getByLabel('private_note')).toBeChecked()
  await expect(after.getByLabel('Keep for (days)')).toHaveValue('120')

  await page.waitForTimeout(300)
  await expect.soft(page).toHaveScreenshot('history.png', { mask: mask(page) })
  await axeClean(page, info.project.name)
  watch.assertNone()
})

test('history: backend validation message for a bad retention', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Notes Trail 2')
  await importFixture(api, id, 'history_notes.json')
  await page.goto(`/#/p/${id}/history`)
  const ticket = page.getByTestId('history-row').filter({ has: page.locator('legend:text-is("Ticket")') })
  await ticket.getByLabel('Keep for (days)').fill('0')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(ticket.getByTestId('field-error')).toHaveText('retention_days must be 1 to 3650')
  await expect(page.getByTestId('issue-summary')).toContainText('1 problem')
  await axeClean(page, `${info.project.name} with issue`)
})

test('history: empty and error states', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const empty = await createProjectViaApi(api, 'No History')
  await page.goto(`/#/p/${empty}/history`)
  await expect(page.getByTestId('history-empty')).toBeVisible()
  await page.route('**/behavior/history', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ code: 'boom', message: 'Backend exploded' }) }),
  )
  await page.reload()
  await expect(page.getByRole('alert').filter({ hasText: 'We could not load the change history settings' })).toBeVisible()
  await page.unroute('**/behavior/history')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByTestId('history-empty')).toBeVisible()
})
