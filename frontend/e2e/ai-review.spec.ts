/** F3-4..7: approvals inbox, See it work and the build-view stage in the new shell.
 *  No model is called: the run is created straight through the API (deterministic). */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

test('approvals inbox, See it work and the stage tabs load without problems', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'AI Review')
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/approvals`)
  await expect(page.getByTestId('approvals-page')).toBeVisible()
  await expect(page.getByTestId('approvals-empty')).toContainText('Nothing is waiting')
  await page.getByTestId('tab-decided').click()
  await expect(page.getByTestId('approvals-empty')).toContainText('No decisions yet')

  await page.goto(`/#/p/${id}/see`)
  await expect(page.getByTestId('seeit-page')).toBeVisible()
  await expect(page.getByTestId('seeit-steps')).toBeVisible()
  await expect(page.getByTestId('seeit-start')).toBeEnabled()

  const created = await api.post(`/projects/${id}/agent/runs`, { goal: 'Stage check' })
  expect(created.status(), await created.text()).toBe(201)
  const run = await created.json()
  await page.goto(`/#/p/${id}/build?run=${run.id}`)
  await expect(page.getByTestId('run-goal')).toHaveText('Stage check')
  await expect(page.getByTestId('budget-steps')).toBeVisible()

  watch.assertNone()
})
