/** F2-4: Build > History timeline (new shell only): list the spec op-log, preview, restore with confirmation.
 *  NOT run by its author (ATLAS runs the Playwright stack). No screenshot baselines: none are asserted. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

async function axeClean(page: Page, name: string) {
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), `axe on ${name}`).toEqual([])
}

test('history timeline: empty state, list, preview, cancel, restore, keyboard, axe', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Timeline Project')
  const watch = watchProblems(page)

  // empty state
  await page.goto(`/#/p/${id}/overview`)
  if (info.project.name === 'desktop') await page.locator('aside[data-sidebar]').getByRole('link', { name: 'History timeline' }).click()
  else await page.goto(`/#/p/${id}/timeline`)
  await expect(page).toHaveURL(new RegExp(`#/p/${id}/timeline$`))
  await expect(page.getByRole('heading', { level: 1, name: 'History timeline' })).toBeVisible()
  await expect(page.getByTestId('timeline-empty')).toBeVisible()
  await axeClean(page, `${info.project.name} empty`)

  // three recorded operations through the typed op API
  for (const name of ['Invoice', 'Customer', 'Payment']) {
    const r = await api.post(`/projects/${id}/spec/ops`, { op_type: 'add_entity', payload: { entity: { name } } })
    expect(r.status(), await r.text()).toBe(201)
  }
  await page.reload()
  const list = page.getByTestId('timeline-list')
  await expect(list.getByRole('button', { name: /Version 3: Added entity Payment/ })).toBeVisible()
  await expect(list.getByRole('button', { name: /Version 1: Added entity Invoice/ })).toBeVisible()
  await expect(list).toContainText(/@example\.com/)
  await expect(list.getByRole('button', { name: /^Start/ })).toBeVisible()

  // preview: nothing selected, then version 1 would take back two changes; the current version cannot be restored
  await expect(page.getByTestId('timeline-preview')).toHaveCount(0)
  await list.getByRole('button', { name: /Version 3:/ }).click()
  await expect(page.getByRole('button', { name: 'Already at this version' })).toBeDisabled()
  await list.getByRole('button', { name: /Version 1:/ }).click()
  await expect(page.getByTestId('timeline-impact')).toContainText('2 changes: 2 added entity')
  await axeClean(page, `${info.project.name} preview`)

  // restore: cancel keeps everything; confirm restores
  const restore = page.getByRole('button', { name: /Restore the draft to this version/ })
  await restore.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('Restore the draft spec to version 1?')
  await page.waitForTimeout(500) // oat <dialog> fades/scales in over 0.3 s; axe must not sample colours mid-transition
  await axeClean(page, `${info.project.name} dialog`)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(restore).toBeFocused()
  expect((await (await api.get(`/projects/${id}/spec/ops`)).json()).total).toBe(3)

  await restore.click()
  await dialog.getByRole('button', { name: 'Restore', exact: true }).click()
  await expect(list.getByRole('button', { name: /Restored the spec to version 1/ })).toBeVisible()
  const after = await (await api.get(`/projects/${id}/spec/ops`)).json()
  expect(after.total).toBe(4)
  expect(after.items[0]).toMatchObject({ origin: 'restore', ref_seq: 1 })
  const entities = await (await api.get(`/projects/${id}/entities`)).json()
  expect(entities.items.map((e: { name: string }) => e.name)).toEqual(['Invoice'])

  // undo brings them back
  await page.getByRole('button', { name: 'Undo last change' }).click()
  await expect(list.getByRole('button', { name: /Undid: / })).toBeVisible()
  await axeClean(page, `${info.project.name} after restore`)

  watch.assertNone()
})
