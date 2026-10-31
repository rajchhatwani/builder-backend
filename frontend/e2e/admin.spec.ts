import { expect, test } from '@playwright/test'
import { ADMIN, watchProblems } from './helpers'

const SECTIONS = ['overview', 'insights', 'users', 'organizations', 'billing', 'plans', 'projects', 'audit', 'settings']

test.describe('admin console', () => {
  test('sign in and every page loads', async ({ page }) => {
    const watch = watchProblems(page)
    await page.goto('/#/admin')
    await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
    await page.getByLabel('Password').fill(ADMIN.password)
    await page.getByRole('button', { name: /sign in/i }).click()
    await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible()
    for (const s of SECTIONS) {
      await page.goto(`/#/admin/${s === 'overview' ? '' : s}`)
      await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible()
      await expect(page.getByText(/something went wrong|unexpected error/i)).toHaveCount(0)
    }
    watch.assertNone()
  })

  test('a customer account cannot use the admin console', async ({ page, request }) => {
    const { registerViaApi } = await import('./helpers')
    const user = await registerViaApi(request)
    await page.goto('/#/admin')
    await page.getByRole('textbox', { name: 'Email' }).fill(user.email)
    await page.getByLabel('Password').fill('Correct-horse-battery-9!')
    await page.getByRole('button', { name: /sign in/i }).click()
    await expect(page.getByRole('alert')).toBeVisible()
  })
})
