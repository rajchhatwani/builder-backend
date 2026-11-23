/** CP-6C/6I: Secure > Compliance. Controls per framework, the evidence bundle download, and a settings save. All of it talks to the real
 *  builder API (the controls and evidence are computed from the project's spec); nothing is mocked.
 *  Not run by its author; run with `npx playwright test e2e/compliance.spec.ts`. */
import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'

test('compliance: pick a framework, download its evidence bundle, save a consent purpose', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Compliance Project')
  const watch = watchProblems(page)

  const all = await (await api.get(`/projects/${id}/compliance/controls`)).json()
  const soc2 = await (await api.get(`/projects/${id}/compliance/controls?framework=soc2`)).json()
  expect(all.controls.length).toBeGreaterThan(0)
  expect(soc2.controls.length).toBeGreaterThan(0)
  expect(soc2.controls.length).toBeLessThan(all.controls.length)

  await page.goto(`/#/p/${id}/compliance`)
  await expect(page.getByRole('heading', { level: 1, name: 'Compliance' })).toBeVisible()
  await expect(page.getByTestId('controls-summary')).toContainText(`${all.met} met, ${all.unmet} unmet, ${all.not_applicable} not applicable.`)
  await expect(page.getByTestId('control-row')).toHaveCount(all.controls.length)
  // "All" has no evidence bundle: the button is off and says why.
  await expect(page.getByTestId('evidence-download')).toBeDisabled()
  await expect(page.getByTestId('evidence-hint')).toBeVisible()

  await page.getByTestId('fw-soc2').click()
  await expect(page.getByTestId('fw-soc2')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('control-row')).toHaveCount(soc2.controls.length)
  await expect(page.getByTestId('evidence-hint')).toHaveCount(0)

  // The status filter narrows the table to what the server counted.
  await page.getByLabel('Show').selectOption('unmet')
  await expect(page.getByTestId('control-row')).toHaveCount(soc2.unmet)
  await expect(page.getByTestId('control-row').and(page.locator('[data-status="unmet"]'))).toHaveCount(soc2.unmet)
  await page.getByLabel('Show').selectOption('')

  const [download] = await Promise.all([page.waitForEvent('download'), page.getByTestId('evidence-download').click()])
  expect(download.suggestedFilename()).toBe('evidence-soc2.zip')
  const bytes = readFileSync(await download.path())
  expect(bytes.subarray(0, 2).toString('latin1'), 'a zip starts with PK').toBe('PK')
  await expect(page.getByTestId('evidence-note')).toHaveText('Downloaded evidence-soc2.zip.')

  // Settings: a consent purpose is saved through the behaviour API.
  await page.getByLabel('Purposes').fill('marketing')
  await page.getByTestId('settings-save').click()
  await expect(page.getByTestId('settings-note')).toContainText('Saved (version')
  const saved = await (await api.get(`/projects/${id}/behavior/compliance`)).json()
  expect(saved.compliance.consent_purposes).toEqual(['marketing'])

  await expect(page.getByTestId('regulated-summary')).toContainText('Not configured')
  await expectAxeClean(page, 'compliance page')
  watch.assertNone()
})
