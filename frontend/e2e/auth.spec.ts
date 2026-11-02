import { expect, test } from '@playwright/test'
import { PASSWORD, markEmailVerified, signInViaUi, uniqueEmail } from './helpers'

test.describe('accounts', () => {
  test('sign up, sign out, sign in, wrong password', async ({ page }) => {
    const email = uniqueEmail('signup')
    await page.goto('/')
    await page.getByText('Create an account').click()
    await page.getByLabel('Name').fill('Journey User')
    await page.getByRole('textbox', { name: 'Email' }).fill(email)
    await page.getByLabel('Password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Create account' }).click()
    // 202, no session: the "check your inbox" screen, with a resend button that waits out the cooldown
    await expect(page.getByTestId('check-inbox')).toContainText('Check your inbox')
    await expect(page.getByTestId('check-inbox')).toContainText(email)
    await expect(page.getByTestId('resend')).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Sign out' })).toHaveCount(0)
    markEmailVerified(email) // test setup only: stands in for opening the e-mailed link

    await page.getByRole('link', { name: 'Back to sign in' }).click()
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()

    await page.getByRole('textbox', { name: 'Email' }).fill(email)
    await page.getByRole('button', { name: 'Continue' }).click()
    await page.getByLabel('Password').fill('definitely-the-wrong-password')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText(/invalid|incorrect|wrong/i)

    await page.getByLabel('Password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Projects', level: 1 })).toBeVisible()
  })

  test('a reload keeps you signed in (refresh cookie)', async ({ page, request }) => {
    const { registerViaApi } = await import('./helpers')
    const api = await registerViaApi(request)
    await signInViaUi(page, api.email)
    await page.reload()
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
  })
})
