/** F1-1: the new shell (flag ui.shell=v2). Rail groups, Ctrl+K, deep links, screenshots + axe.
 *  Baselines here are for the NEW shell only; the old-shell ones live in visual.spec.ts.
 *  Refresh with `npx playwright test e2e/shell-v2.spec.ts --update-snapshots`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { SECTION_IDS, createProjectViaApi, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

const GROUPS = ['Build', 'Secure', 'Connect', 'Operate', 'Ship']

test('new shell: grouped rail, deep links, Ctrl+K, flag off restores the old shell', async ({ page, request }, info) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Shell Project')
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/overview`)
  const rail = page.locator('aside[data-sidebar]')
  await expect(page.locator('nav[data-shell="v2"]')).toBeVisible()
  await expect(page.getByTestId('shell-project')).toHaveText('Shell Project')
  if (info.project.name === 'desktop') {
    for (const g of GROUPS) await expect(rail.getByText(g, { exact: true })).toBeVisible()
    await expect(rail.getByText('Map', { exact: false })).toBeVisible()
  }
  // every old section id (plus the v2-only State machines page) is reachable from the rail and keeps its deep link
  expect(await rail.locator('a[href^="#/p/"]').count()).toBe(SECTION_IDS.length + 14) // + Forms preview (F2-1), State machines (F1-4), Settings, Change history (F1-6A), Hooks (F1-5), Seed data (F1-6B), Rules (F1-3), History timeline (F2-4), Notifications (F2-6), Webhooks, Provider integrations, Jobs, Workers, Workflows (F2-2/F2-3)

  await page.goto(`/#/p/${id}/model`)
  await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
  await expect(rail.locator('a[aria-current="page"]')).toHaveAttribute('href', `#/p/${id}/model`)

  // Ctrl+K: filter, Enter navigates; Esc closes
  await page.keyboard.press('Control+k')
  const box = page.getByRole('combobox', { name: 'Search commands' })
  await expect(box).toBeFocused()
  await box.fill('deploy')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(new RegExp(`#/p/${id}/deployment$`))
  await expect(box).toHaveCount(0)
  await page.keyboard.press('Control+k')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('combobox', { name: 'Search commands' })).toHaveCount(0)

  watch.assertNone()

  // turning the flag off brings the old shell back unchanged
  await page.evaluate(() => localStorage.setItem('ui.shell', 'v1'))
  await page.reload()
  await expect(page.locator('nav[data-shell="v2"]')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '← All projects' })).toBeVisible()
})

test('new shell: screenshots and axe', async ({ page, request }, info) => {
  test.setTimeout(120_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Shell Visual')
  const mask = [page.locator('nav[data-shell="v2"] .muted, nav[data-shell="v2"] [data-testid=shell-project]')]
  for (const section of ['overview', 'model']) {
    await page.goto(`/#/p/${id}/${section}`)
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
    await page.waitForTimeout(500)
    await expect.soft(page).toHaveScreenshot(`shell-v2-${section}.png`, { mask: [...mask, page.locator('main')] })
    const axe = await new AxeBuilder({ page }).analyze()
    expect(axe.violations.map((v) => v.id), `axe on ${info.project.name} ${section}`).toEqual([])
  }
  await page.keyboard.press('Control+k')
  await expect(page.getByRole('combobox', { name: 'Search commands' })).toBeVisible()
  await page.waitForTimeout(300)
  await expect.soft(page).toHaveScreenshot('shell-v2-palette.png', { mask })
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => v.id), 'axe with palette open').toEqual([])
})
