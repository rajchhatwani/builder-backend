/** Cycle-5 pages smoke: each page loads inside the shell. Before the preview sign-in nothing is asked of the project API;
 *  after it (the session is mocked, see preview-mock.ts) and with every data call answered 500, the page shows its error
 *  state and the shell does not crash.
 *  Not run by its author; run with `npx playwright test e2e/cycle5-smoke.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'
import { mockPreviewSession, signInPreview } from './preview-mock'

const PAGES = [
  { route: 'ledger', root: 'ledger-page', error: 'ledger-accounts-error' },
  { route: 'map', root: 'map-page', error: 'map-positions-error' },
  { route: 'bookings', root: 'bookings-page', error: 'bookings-resources-error' },
  { route: 'documents', root: 'documents-page', error: 'documents-error' },
  { route: 'agentactions', root: 'agentapprovals-page', error: 'agentapprovals-error' },
] as const

test('cycle-5 pages: need the preview sign-in and fail soft when the project API errors', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Cycle5 Smoke')
  const seen = await mockPreviewSession(page, id, () => ({ status: 500, json: { code: 'boom', message: 'The preview app failed' } }))
  const watch = watchProblems(page)

  for (const p of PAGES) {
    await test.step(p.route, async () => {
      await page.goto(`/#/p/${id}/${p.route}`)
      await expect(page.getByTestId(p.root)).toBeVisible()
      await expect(page.getByTestId('preview-signin')).toBeVisible()
      const before = seen.length
      await signInPreview(page)
      await expect(page.getByTestId(p.error)).toBeVisible()
      expect(seen.length).toBeGreaterThan(before)
      await expect(page.getByTestId(p.root)).toBeVisible()
      await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible() // the shell around it is still alive
    })
  }
  watch.assertNone()
})
