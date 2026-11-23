/** F1-1: the project shell. Rail groups, Ctrl+K, deep links, screenshots + axe.
 *  Refresh with `npx playwright test e2e/shell-v2.spec.ts --update-snapshots`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { SECTION_IDS, createProjectViaApi, signedInUser, watchProblems } from './helpers'

const GROUPS = ['Build with AI', 'Build', 'Secure', 'Connect', 'Operate', 'Ship']
/** Links per rail group, from src/shell/groups.ts (CP-6I): 1+5+13+6+26+24+3 = 78 sections. A section added or removed there must change this too. */
const RAIL_COUNTS: Record<string, number> = { home: 1, ai: 5, build: 13, secure: 6, connect: 26, operate: 24, ship: 3 }

test('shell: grouped rail, deep links, Ctrl+K', async ({ page, request }, info) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Shell Project')
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/overview`)
  const rail = page.locator('aside[data-sidebar]')
  await expect(page.locator('nav[data-shell="v2"]')).toBeVisible()
  await expect(page.getByTestId('shell-project')).toHaveText('Shell Project')
  if (info.project.name === 'desktop') {
    for (const g of GROUPS) await expect(rail.getByText(g, { exact: true })).toBeVisible()
    await expect(rail.getByRole('link', { name: 'Map' })).toBeVisible()
  }
  // every section (the twelve original ids plus all later pages) is reachable from the rail and keeps its deep link
  expect(SECTION_IDS).toHaveLength(12)
  for (const [group, n] of Object.entries(RAIL_COUNTS)) {
    await expect(rail.locator(`[data-rail-group=${group}] a[href^="#/p/"]`), `rail group ${group}`).toHaveCount(n)
  }
  await expect(rail.locator('a[href^="#/p/"]')).toHaveCount(Object.values(RAIL_COUNTS).reduce((a, b) => a + b, 0))
  for (const sec of SECTION_IDS) await expect(rail.locator(`a[href="#/p/${id}/${sec}"]`), `rail link ${sec}`).toHaveCount(1)

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
})

test('shell: screenshots and axe', async ({ page, request }, info) => {
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
