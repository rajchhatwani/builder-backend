/** CP-5V admin pages "Operations" (#/admin/operations) and "Usage limits" (#/admin/usage).
 *  NOT run by its author (ATLAS runs the Playwright stack). No screenshot baselines are asserted.
 *  The edited usage limit is restored at the end so later specs see the original value. */
import { expect, test, type Page } from '@playwright/test'
import { ADMIN, watchProblems } from './helpers'

async function adminSignIn(page: Page) {
  await page.goto('/#/admin')
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByLabel('Password').fill(ADMIN.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible()
}

test.describe('admin operations', () => {
  test('overview shows jobs, idle, reports, key provider and go-live results', async ({ page }) => {
    const watch = watchProblems(page)
    await adminSignIn(page)
    await expect(page.getByRole('link', { name: 'Operations' })).toHaveAttribute('href', '#/admin/operations')
    await page.goto('/#/admin/operations')
    await expect(page.getByRole('heading', { name: 'Operations', level: 1 })).toBeVisible()
    await expect(page.getByTestId('scheduler')).toBeVisible()
    await expect(page.locator('[data-testid=job-row][data-job=reports]')).toBeVisible()
    await expect(page.locator('[data-testid=job-row][data-job=idle_sweep]')).toBeVisible()
    await expect(page.getByTestId('idle-text')).toContainText(/Idle for more than \d+ days?/)
    await expect(page.getByTestId('reports-text')).toContainText(/\d+ enabled, \d+ disabled/)
    await expect(page.getByTestId('key-state')).toBeVisible()
    await expect(page.getByTestId('golive-results')).toBeVisible()
    await page.getByTestId('golive-run').click()
    await expect(page.getByTestId('golive-summary')).toContainText(/\d+ passed, \d+ failed/)
    const statuses = await page.getByTestId('golive-row').evaluateAll((els) => els.map((e) => e.getAttribute('data-status')))
    expect(statuses.length).toBeGreaterThan(0)
    for (const s of statuses) expect(['pass', 'fail', 'warn', 'skipped']).toContain(s)
    watch.assertNone()
  })

  test('usage limits: pick an organization, edit a limit, restore it', async ({ page }) => {
    const watch = watchProblems(page)
    await adminSignIn(page)
    await page.goto('/#/admin/usage')
    await expect(page.getByRole('heading', { name: 'Usage limits', level: 1 })).toBeVisible()
    await expect(page.getByTestId('ul-idle')).toBeVisible()
    const select = page.locator('#ul-org')
    await expect(select.locator('option').nth(1)).toBeAttached()
    await select.selectOption({ index: 1 })
    await page.getByTestId('ul-open').click()
    const row = page.getByTestId('metric-row').first()
    await expect(row).toBeVisible()
    const box = row.getByRole('textbox')
    const before = await box.inputValue()
    try {
      // negative is refused in the form
      await box.fill('-1')
      await row.getByTestId('metric-save').click()
      await expect(page.getByText(/cannot be negative/)).toBeVisible()
      // real edit with confirmation
      const next = String((Number(before) || 0) + 7)
      await box.fill(next)
      await row.getByTestId('metric-save').click()
      await page.getByRole('button', { name: 'Change limit' }).click()
      await expect(box).toHaveValue(next)
    } finally {
      // runs even if an assertion above failed: the limit must not stay changed for later specs
      await box.fill(before)
      await row.getByTestId('metric-save').click()
      await page.getByRole('button', { name: 'Change limit' }).click({ timeout: 5000 }).catch(() => undefined)
    }
    await expect(box).toHaveValue(before)
    watch.assertNone()
  })
})
