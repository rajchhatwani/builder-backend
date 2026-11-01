/** F2-1: Connect > Forms preview (new shell only): settings forms generated from JSON Schema.
 *  NOT run by its author. Create/refresh baselines with `npx playwright test e2e/forms-preview.spec.ts --update-snapshots`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

const mask = (page: Page) => [page.locator('nav[data-shell="v2"] .muted, nav[data-shell="v2"] [data-testid=shell-project]')]
async function axeClean(page: Page, name: string) {
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), `axe on ${name}`).toEqual([])
}
const value = (page: Page) => page.getByTestId('form-value')

test('forms preview: three blocks render from schema, edit, show-when, list rows, backend messages verbatim', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Forms Project')
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/overview`)
  if (info.project.name === 'desktop') await page.locator('aside[data-sidebar]').getByRole('link', { name: 'Forms preview' }).click()
  else await page.goto(`/#/p/${id}/forms`)
  await expect(page).toHaveURL(new RegExp(`#/p/${id}/forms$`))
  await expect(page.getByRole('heading', { level: 1, name: 'Forms preview' })).toBeVisible()

  // 1. Observability: flat toggles and numbers, show-when
  const service = page.getByLabel('Service name')
  await expect(service).toBeVisible()
  await page.getByLabel('Sample ratio').fill('0.5')
  await expect(value(page)).toContainText('"sample_ratio": 0.5')
  await page.getByLabel('Enabled').uncheck()
  await expect(service).toHaveCount(0)
  await page.getByLabel('Enabled').check()
  await expect(service).toBeVisible()
  await page.getByRole('button', { name: 'Show sample backend errors' }).click()
  await expect(page.getByTestId('field-error')).toHaveText('String should have at most 80 characters')
  await expect(service).toHaveAttribute('aria-invalid', 'true')
  await axeClean(page, `${info.project.name} observability`)
  await page.waitForTimeout(300)
  await expect.soft(page).toHaveScreenshot('forms-preview-observability.png', { mask: mask(page) })

  // 2. Lists: rows with nested rows, keyboard add/remove
  await page.getByRole('button', { name: 'Lists', exact: true }).click()
  await page.getByRole('button', { name: 'Add list' }).click()
  await expect(page.getByLabel('Name')).toBeFocused().catch(() => undefined)
  await page.getByLabel('Name').fill('Priorities')
  await page.getByRole('button', { name: 'Add item' }).click()
  await page.getByLabel('Value').fill('high')
  await page.getByLabel('Label', { exact: true }).last().fill('High')
  await expect(value(page)).toContainText('"value": "high"')
  await page.getByRole('button', { name: 'Add list' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('group', { name: 'List 2' })).toBeVisible()
  await page.getByRole('button', { name: 'Remove List 2' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('group', { name: 'List 2' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Show sample backend errors' }).click()
  await expect(page.getByTestId('field-error')).toHaveText('String should have at most 80 characters')
  await axeClean(page, `${info.project.name} lists`)
  await expect.soft(page).toHaveScreenshot('forms-preview-lists.png', { mask: mask(page) })

  // 3. Storage: nested objects, enums, show-when
  await page.getByRole('button', { name: 'Storage', exact: true }).click()
  await expect(page.getByLabel('Region')).toBeVisible()
  await page.getByLabel('Backend').selectOption('minio')
  await expect(page.getByLabel('Region')).toHaveCount(0)
  await page.getByLabel('Backend').selectOption('s3')
  await page.getByLabel('Audit retention days').fill('0')
  await page.getByLabel('Audit retention days').blur()
  await expect(page.getByTestId('field-error')).toHaveText('Input should be greater than or equal to 1')
  await page.getByRole('button', { name: 'Show sample backend errors' }).click()
  await expect(page.getByTestId('field-error')).toHaveText('Input should be greater than or equal to 1')
  await page.getByLabel('Read only').check()
  await expect(page.getByLabel('Bucket')).toHaveJSProperty('readOnly', true)
  await page.getByLabel('Read only').uncheck()
  await axeClean(page, `${info.project.name} storage`)
  await expect.soft(page).toHaveScreenshot('forms-preview-storage.png', { mask: mask(page) })

  watch.assertNone()
})
