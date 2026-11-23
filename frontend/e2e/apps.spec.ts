/** CP-6D/6I: Connect > Apps. Install an app (token and signing secret shown once), then uninstall it.
 *  The project comes from the real builder API; the apps come from the mocked preview app (see preview-mock.ts).
 *  Not run by its author; run with `npx playwright test e2e/apps.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { mockPreviewSession, signInPreview } from './preview-mock'

test('apps: install shows the secrets once, uninstall asks first', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Apps Project')

  const app = { name: 'reporter', title: 'Reporter', scopes: ['Invoice', 'Customer'], events: ['invoice.created'], installed: false, installation_id: null as string | null, granted_scopes: [] as string[], installed_at: null as string | null }
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/platform/apps') return { json: [app] }
    if (r.method === 'POST' && r.path === '/platform/apps/reporter/install') {
      const scopes = (r.body as { scopes: string[] }).scopes
      Object.assign(app, { installed: true, installation_id: 'inst1', granted_scopes: scopes, installed_at: new Date().toISOString() })
      return { status: 201, json: { installation_id: 'inst1', app: 'reporter', granted_scopes: scopes, token: 'app_tok_ONLY-ONCE', signing_secret: 'whsec_ONLY-ONCE' } }
    }
    if (r.method === 'POST' && r.path === '/platform/apps/reporter/uninstall') {
      Object.assign(app, { installed: false, installation_id: null, granted_scopes: [], installed_at: null })
      return { json: { ok: true } }
    }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/apps`)
  await expect(page.getByRole('heading', { level: 1, name: 'Apps' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)

  const item = page.getByTestId('app-item')
  await expect(item).toHaveCount(1)
  await expect(item).toHaveAttribute('data-installed', 'false')
  await expect(page.getByTestId('app-status')).toContainText('Not installed')

  // Install with only one of the two entities.
  await page.getByTestId('app-scope').nth(1).uncheck() // Customer
  await page.getByRole('button', { name: 'Install Reporter' }).click()
  const secret = page.getByTestId('secret-panel')
  await expect(secret).toBeVisible()
  await expect(secret.getByTestId('secret-value')).toHaveText(['app_tok_ONLY-ONCE', 'whsec_ONLY-ONCE'])
  expect(seen.find((s) => s.method === 'POST' && s.path === '/platform/apps/reporter/install')!.body).toEqual({ scopes: ['Invoice'] })
  await expect(item).toHaveAttribute('data-installed', 'true')
  await expect(page.getByTestId('app-status')).toContainText('reads Invoice')
  await expectAxeClean(page, 'apps with the secrets shown')
  await page.getByTestId('secret-dismiss').click()
  await expect(secret).toHaveCount(0)

  // Uninstall: "Keep it" changes nothing, then confirm.
  await page.getByRole('button', { name: 'Uninstall Reporter' }).click()
  await page.getByRole('button', { name: 'Keep it' }).click()
  expect(seen.some((s) => s.path.endsWith('/uninstall'))).toBe(false)
  await page.getByRole('button', { name: 'Uninstall Reporter' }).click()
  await page.getByTestId('uninstall-confirm').click()
  await expect(page.getByTestId('apps-note')).toHaveText('Reporter uninstalled.')
  await expect(item).toHaveAttribute('data-installed', 'false')
  await expect(page.getByRole('button', { name: 'Install Reporter' })).toBeVisible()

  await expectAxeClean(page, 'apps page')
  watch.assertNone()
})
