/** B3-10 admin page "Preview limits" (admin console, #/admin/previews), behind the single flag ui.shell=v2.
 *  NOT run by its author (ATLAS runs the Playwright stack). No screenshot baselines are asserted.
 *  The kill switch is turned on and off again, and the edited default is restored, so later specs see the platform defaults. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { ADMIN, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
const flags = [{ name: 'ui.shell', value: 'v2' }]
test.use({ storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: flags }] } })

async function adminSignIn(page: Page) {
  await page.goto('/#/admin')
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByLabel('Password').fill(ADMIN.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible()
}

test.describe('admin preview limits', () => {
  test('nav entry, defaults with bounds, save, and restore', async ({ page }) => {
    const watch = watchProblems(page)
    await adminSignIn(page)
    // The sidebar is an off-canvas drawer at phone width (other admin specs navigate by URL too): check the entry, then go.
    await expect(page.getByRole('link', { name: 'Preview limits' })).toHaveAttribute('href', '#/admin/previews')
    await page.goto('/#/admin/previews')
    await expect(page.getByRole('heading', { name: 'Preview limits', level: 1 })).toBeVisible()
    await expect(page.getByTestId('usage')).toContainText(/\d+ live previews? \(\d+ running\)/)
    const sleep = page.getByLabel(/Sleep after idle/)
    await expect(sleep).toBeVisible()
    await expect(page.getByText(/Allowed \d+(\.\d+)? to \d+/).first()).toBeVisible()
    const before = await sleep.inputValue()
    const next = String(Number(before) + 5)
    await sleep.fill(next)
    await page.getByRole('button', { name: 'Save defaults' }).click()
    await expect(page.getByTestId('save-note')).toHaveText('Saved.')
    await page.reload()
    await expect(page.getByLabel(/Sleep after idle/)).toHaveValue(next)
    // restore
    await page.getByLabel(/Sleep after idle/).fill(before)
    await page.getByRole('button', { name: 'Save defaults' }).click()
    await expect(page.getByTestId('save-note')).toHaveText('Saved.')
    watch.assertNone()
  })

  test('out-of-range value shows the server message and saves nothing', async ({ page }) => {
    await adminSignIn(page)
    await page.goto('/#/admin/previews')
    const cpu = page.getByLabel(/CPU per preview/)
    const before = await cpu.inputValue()
    await cpu.fill('999')
    await page.getByRole('button', { name: 'Save defaults' }).click()
    await expect(page.getByTestId('field-error').or(page.getByTestId('defaults-error')).first()).toBeVisible()
    await page.reload()
    await expect(page.getByLabel(/CPU per preview/)).toHaveValue(before)
  })

  test('kill switch asks for confirmation, then turns on and off', async ({ page }) => {
    await adminSignIn(page)
    await page.goto('/#/admin/previews')
    await page.getByRole('button', { name: 'Turn kill switch on' }).click()
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByTestId('kill-state')).toContainText('Off')
    await page.getByRole('button', { name: 'Turn kill switch on' }).click()
    await page.getByRole('button', { name: 'Stop all previews' }).click()
    await expect(page.getByTestId('kill-state')).toContainText('ON')
    await page.getByRole('button', { name: 'Turn kill switch off' }).click()
    await page.getByRole('button', { name: 'Allow previews' }).click()
    await expect(page.getByTestId('kill-state')).toContainText('Off')
  })

  test('add, edit and remove an organization override', async ({ page }) => {
    await adminSignIn(page)
    await page.goto('/#/admin/previews')
    const select = page.getByLabel('Organization to add')
    await expect(select).toBeVisible()
    const option = select.locator('option').nth(1)
    const name = ((await option.textContent()) ?? '').trim()
    test.skip(!name, 'the e2e database has no organization yet')
    // Target exactly this organization's row (names such as "E2E User" also match loose patterns).
    const table = page.getByTestId('override-table')
    const rowOf = () => table.getByRole('row').filter({ has: page.getByRole('rowheader', { name, exact: true }) })
    // A failed earlier run may have left an override behind: start clean.
    if (await rowOf().count()) {
      await rowOf().getByRole('button', { name: /^Remove/ }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Remove' }).click()
      await expect(rowOf()).toHaveCount(0)
    }
    await select.selectOption({ label: name })
    await page.getByRole('button', { name: 'Add override' }).click()
    const editor = page.getByTestId('org-editor')
    await expect(editor.getByLabel(/Live previews per person/)).toBeVisible()
    await editor.getByLabel(/Live previews per person/).fill('2')
    await editor.getByLabel(/Note/).fill('e2e override')
    // above the platform default is refused (422) until "allow above default" is ticked
    await editor.getByLabel(/Memory per preview/).fill('2048')
    await editor.getByRole('button', { name: 'Save override' }).click()
    await expect(page.getByTestId('org-error')).toBeVisible()
    await editor.getByLabel('Allow values above the platform default').check()
    await editor.getByRole('button', { name: 'Save override' }).click()
    await expect(rowOf()).toBeVisible()
    await rowOf().getByRole('button', { name: /^Edit/ }).click()
    await expect(page.getByTestId('org-editor').getByLabel(/Live previews per person/)).toHaveValue('2')
    await page.getByRole('button', { name: 'Close' }).click()
    await rowOf().getByRole('button', { name: /^Remove/ }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Remove' }).click()
    await expect(rowOf()).toHaveCount(0)
  })

  test('keyboard reachable and no accessibility violations', async ({ page }) => {
    await adminSignIn(page)
    await page.goto('/#/admin/previews')
    await expect(page.getByRole('button', { name: /Turn kill switch/ })).toBeVisible()
    await page.getByRole('button', { name: /Turn kill switch/ }).focus()
    await page.keyboard.press('Tab')
    await expect(page.getByLabel(/Live previews per person/).first()).toBeFocused()
    const axe = await new AxeBuilder({ page }).analyze()
    expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
  })
})
