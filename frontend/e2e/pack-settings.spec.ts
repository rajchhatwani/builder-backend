/** CP-6F/6I: Connect > pack settings forms generated from JSON Schema (ledger settings as the example, reconciliation as the "off" state).
 *  Everything is the real builder API: the money_ledger fixture is imported, one field is edited and saved, the spec holds the new value.
 *  Not run by its author; run with `npx playwright test e2e/pack-settings.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, importFixture, signedInUser, watchProblems } from './helpers'

test('pack settings: edit and save the ledger form, an absent block shows as switched off', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Pack Settings')
  await importFixture(api, id, 'money_ledger.json')
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/ledgersettings`)
  await expect(page.getByRole('heading', { level: 1, name: 'Ledger settings' })).toBeVisible()
  const form = page.locator('[data-schema-form]')
  await expect(form).toBeVisible()
  await expect(form.getByLabel('Max entries')).toHaveValue('100')
  await expect(form.getByLabel('Read roles')).toHaveValue(/admin, ?member/)

  await form.getByLabel('Max entries').fill('250')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-note')).toContainText('Saved (version')
  const packs = (await (await api.get(`/projects/${id}/behavior/packs`)).json()).packs
  expect(packs.money.ledger.max_entries).toBe(250)
  expect(packs.money.ledger.read_roles).toEqual(['admin', 'member'])
  expect(packs.money.currency.currencies).toEqual(['EUR', 'JPY', 'KWD', 'USD']) // the other blocks are untouched

  // The edit survives a reload.
  await page.reload()
  await expect(page.getByRole('heading', { level: 1, name: 'Ledger settings' })).toBeVisible()
  await expect(page.locator('[data-schema-form]').getByLabel('Max entries')).toHaveValue('250')
  await expect(page.getByTestId('switch-off')).toBeVisible()
  await expectAxeClean(page, 'ledger settings')

  // A block the spec does not have is offered as switched off, not as an error.
  await page.goto(`/#/p/${id}/reconsettings`)
  await expect(page.getByRole('heading', { level: 1, name: 'Reconciliation settings' })).toBeVisible()
  await expect(page.getByTestId('block-off')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Switch on reconciliation settings' })).toBeEnabled()
  await expectAxeClean(page, 'reconciliation settings, off')
  watch.assertNone()
})
