/** F2-6: Connect > Notifications (new shell only): empty state, example, edit template, live preview, validation,
 *  save draft, preferences matrix, delivery log, keyboard, axe. NOT run by its author (ATLAS runs the Playwright stack). */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

async function axeClean(page: Page, name: string) {
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), `axe on ${name}`).toEqual([])
}

test('notifications: empty, example, edit, preview, validation, save, matrix, log, keyboard, axe', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Notifications Project')
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/overview`)
  if (info.project.name === 'desktop') await page.locator('aside[data-sidebar]').getByRole('link', { name: 'Notifications' }).click()
  else await page.goto(`/#/p/${id}/notifications`)
  await expect(page).toHaveURL(new RegExp(`#/p/${id}/notifications$`))
  await expect(page.getByRole('heading', { level: 1, name: 'Notifications' })).toBeVisible()

  // empty: the spec declares no types
  await expect(page.getByTestId('notif-empty')).toBeVisible()
  await expect(page.getByTestId('notif-readonly-note')).toContainText('no endpoint that stores it')
  await axeClean(page, `${info.project.name} empty`)

  // example, keyboard activation
  await page.getByRole('button', { name: 'Try with an example' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('notif-example')).toBeVisible()
  await expect(page.getByTestId('nt-variables')).toContainText('{{ order_number }}')
  await expect(page.getByTestId('nt-preview-body')).toContainText('Hello Sample customer name, we received your order Sample order number')
  await axeClean(page, `${info.project.name} editor`)

  // edit + live preview: markup stays text; value placeholders are filled
  const body = page.getByLabel('Message body')
  await body.fill('<img src=x onerror=alert(1)> Thanks {{ customer_name }}')
  await expect(page.getByTestId('nt-preview-body')).toHaveText('<img src=x onerror=alert(1)> Thanks Sample customer name')
  await expect(page.getByTestId('nt-preview').locator('img')).toHaveCount(0)

  // an undeclared variable blocks saving
  await body.fill('Hi {{ secret }}')
  await expect(page.getByTestId('nt-problems')).toContainText('{{ secret }} is not a declared variable')
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Fix the problems' })).toBeVisible()
  await axeClean(page, `${info.project.name} problems`)

  // fix, save
  await page.getByLabel('Subject').fill('Order {{ order_number }} is confirmed')
  await body.fill('Thanks {{ customer_name }}, total {{ total }}')
  await expect(page.getByTestId('nt-preview-subject')).toHaveText('Order Sample order number is confirmed')
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(page.getByTestId('nt-saved')).toContainText('order_confirmed / email')

  // another channel has no subject
  await page.getByLabel('Channel').selectOption('sms')
  await expect(page.getByLabel('Subject')).toHaveCount(0)
  await expect(page.getByTestId('nt-preview-body')).toContainText('Order Sample order number confirmed')

  // preferences matrix: the transactional type is locked
  await page.getByRole('button', { name: 'Preferences' }).click()
  const matrix = page.getByTestId('nt-matrix')
  await expect(matrix.getByRole('row', { name: /order_confirmed/ })).toContainText('On, locked (required)')
  await expect(matrix.getByRole('row', { name: /weekly_digest/ })).toContainText('Off by default, user can opt in')
  await axeClean(page, `${info.project.name} matrix`)

  // delivery log: masked addresses only
  await page.getByRole('button', { name: 'Delivery log' }).click()
  const log = page.getByTestId('nt-log')
  await expect(log).toContainText('a***@example.com')
  await expect(log).not.toContainText('alice@')
  await axeClean(page, `${info.project.name} log`)

  watch.assertNone()
})
