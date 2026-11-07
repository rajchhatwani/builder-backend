/** F3-1..3: the "Build with AI" front door (intake, plan review, build view) in the new shell.
 *  No model is called: the run is created straight through the API, so the journey is deterministic. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

test('front door: rail group, intake box, empty plan review, build view with tabs and cancel', async ({ page, request }, info) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'AI Front Door')
  const watch = watchProblems(page)

  // intake
  await page.goto(`/#/p/${id}/intake`)
  await expect(page.getByTestId('intake-page')).toBeVisible()
  if (info.project.name === 'desktop') await expect(page.locator('aside[data-sidebar]').getByText('Build with AI', { exact: true })).toBeVisible()
  const submit = page.getByTestId('intake-submit')
  await expect(submit).toBeDisabled()
  await page.getByLabel('What should the backend do?').fill('A small leave-request system with manager approval.')
  await expect(submit).toBeEnabled()
  await page.getByLabel('Add documents').setInputFiles({ name: 'virus.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('x') })
  await expect(page.getByRole('alert').filter({ hasText: 'only PDF, text and Markdown' })).toBeVisible()
  await page.getByLabel('Add documents').setInputFiles({ name: 'brief.md', mimeType: 'text/markdown', buffer: Buffer.from('# Brief\nManagers approve leave.') })
  await expect(page.getByTestId('intake-files')).toContainText('brief.md')

  // plan review with nothing pending
  await page.goto(`/#/p/${id}/plan`)
  await expect(page.getByTestId('plan-empty')).toBeVisible()

  // build view for a run created through the API
  const created = await api.post(`/projects/${id}/agent/runs`, { goal: 'Build the leave system' })
  expect(created.status(), await created.text()).toBe(201)
  const run = await created.json()
  await page.goto(`/#/p/${id}/build?run=${run.id}`)
  await expect(page.getByTestId('run-goal')).toHaveText('Build the leave system')
  await expect(page.getByTestId('chip-state')).toBeVisible()
  await expect(page.getByTestId('chip-phase')).toContainText('plan')
  await expect(page.getByTestId('budget-steps')).toBeVisible()
  await expect(page.getByTestId('timeline')).toBeVisible()
  await page.getByRole('tab', { name: 'Diagrams' }).click()
  await expect(page.getByTestId('tab-soon')).toContainText('next checkpoint')
  await page.getByRole('tab', { name: 'Gates' }).click()
  await page.getByTestId('run-cancel').click()
  await expect(page.getByTestId('chip-state')).toHaveText('Cancelled')
  await expect(page.getByTestId('run-cancel')).toHaveCount(0)

  watch.assertNone()
})
