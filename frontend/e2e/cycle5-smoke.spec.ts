/** Cycle-5 pages smoke: each page loads inside the v2 shell with the preview API unreachable. With no token nothing is fetched;
 *  with a token and every preview request aborted, the page shows its error state and the shell does not crash.
 *  Not run by its author; run with `npx playwright test e2e/cycle5-smoke.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'
import { PREVIEW, V2_STATE } from './preview-mock'

test.use({ storageState: V2_STATE })

const PAGES = [
  { route: 'ledger', root: 'ledger-page', prefix: 'ledger', error: 'ledger-accounts-error' },
  { route: 'map', root: 'map-page', prefix: 'map', error: 'map-positions-error' },
  { route: 'bookings', root: 'bookings-page', prefix: 'bookings', error: 'bookings-resources-error' },
  { route: 'documents', root: 'documents-page', prefix: 'documents', error: 'documents-error' },
  { route: 'agentactions', root: 'agentapprovals-page', prefix: 'agentapprovals', error: 'agentapprovals-error' },
] as const

test('cycle-5 pages: load without a project API and fail soft when it is unreachable', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Cycle5 Smoke')
  let previewHits = 0
  await page.route(`${PREVIEW}/**`, (route) => { previewHits += 1; return route.abort('connectionrefused') })
  const watch = watchProblems(page)

  for (const p of PAGES) {
    await test.step(p.route, async () => {
      await page.goto(`/#/p/${id}/${p.route}`)
      await expect(page.getByTestId(p.root)).toBeVisible()
      await expect(page.getByTestId(`${p.prefix}-notoken`)).toBeVisible()
      const before = previewHits
      await page.getByTestId(`${p.prefix}-token`).fill('e2e-smoke-' + 'token')
      await page.getByTestId(`${p.prefix}-load`).click()
      await expect(page.getByTestId(p.error)).toBeVisible()
      expect(previewHits).toBeGreaterThan(before)
      await expect(page.getByTestId(p.root)).toBeVisible()
      await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible() // the shell around it is still alive
    })
  }
  watch.assertNone()
})
