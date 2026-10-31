/** C0-F2: screenshot baselines + axe baseline for every route, at 1366x768 (desktop) and 375 (phone).
 *  First run (or UPDATE_SNAPSHOTS): `npx playwright test e2e/visual.spec.ts --update-snapshots`.
 *  Volatile text (the signed-in e-mail, org slugs, dates, tables) is masked, not ignored: layout
 *  still has to match. axe: existing violations are recorded in a11y-baseline.json and do not fail;
 *  a rule that is new for a route does. Refresh with UPDATE_A11Y_BASELINE=1. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { ADMIN, SECTION_IDS, createProjectViaApi, registerViaApi, setPlanAsAdmin, signInViaUi } from './helpers'

const BASELINE = resolve(dirname(fileURLToPath(import.meta.url)), 'a11y-baseline.json')
const found: Record<string, string[]> = {}

// Admin list pages grow with every journey that creates users/orgs/projects, so their whole body
// is masked: the shell (nav, headings position, page chrome) is still compared.
const DATA_DRIVEN = /^(admin-(overview|insights|users|organizations|billing|projects|audit)|org-audit)$/

function mask(page: Page, key: string) {
  const volatile = 'nav, aside, table, time, [data-testid=vary], .small-text'
  return [page.locator(DATA_DRIVEN.test(key) ? `${volatile}, main` : volatile)]
}

async function shoot(page: Page, info: TestInfo, key: string, ready: () => Promise<void>) {
  await ready()
  await page.waitForTimeout(500)
  await expect.soft(page).toHaveScreenshot(`${key.replace(/[^a-z0-9]+/gi, '-')}.png`, { mask: mask(page, key), fullPage: false })
  // color-contrast on data-driven pages depends on which rows/badges exist, so it is not stable there.
  const builder = new AxeBuilder({ page })
  if (DATA_DRIVEN.test(key)) builder.disableRules(['color-contrast'])
  const axe = await builder.analyze()
  found[`${info.project.name}:${key}`] = [...new Set(axe.violations.map((v) => v.id))].sort()
}

test.afterAll(() => {
  if (process.env.UPDATE_A11Y_BASELINE === '1') {
    let all: Record<string, string[]> = {}
    try { all = JSON.parse(readFileSync(BASELINE, 'utf8')) } catch { /* first run */ }
    writeFileSync(BASELINE, JSON.stringify({ ...all, ...found }, null, 1) + '\n')
    return
  }
  const baseline: Record<string, string[]> = JSON.parse(readFileSync(BASELINE, 'utf8'))
  const added = Object.entries(found).flatMap(([route, ids]) => ids.filter((id) => !(baseline[route] ?? []).includes(id)).map((id) => `${route}: ${id}`))
  expect(added, 'new accessibility violations (existing ones are baselined)').toEqual([])
})

test('public and customer routes', async ({ page, request }, info) => {
  test.setTimeout(240_000)
  await shoot(page, info, 'login', async () => {
    await page.goto('/#/')
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  })
  const api = await registerViaApi(request)
  await signInViaUi(page, api.email)
  const projectId = await createProjectViaApi(api, 'Visual Project')
  const org = await (await api.post('/orgs', { name: 'Visual Org', slug: `visual-${Date.now()}` })).json()
  await setPlanAsAdmin(request, org.id)

  await shoot(page, info, 'projects', async () => {
    await page.goto('/#/')
    await page.reload() // the project was created after the list first loaded
    await expect(page.getByText('Visual Project').first()).toBeVisible()
  })
  await shoot(page, info, 'account', async () => {
    await page.goto('/#/account')
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
  })
  for (const path of ['', '/invites', '/projects', '/plan', '/audit', '/sso', '/policies']) {
    await shoot(page, info, `org${path || '-people'}`, async () => {
      await page.goto(`/#/org/${org.slug}${path}`)
      await expect(page.getByRole('heading', { name: /Visual Org/ }).first()).toBeVisible()
    })
  }
  for (const section of SECTION_IDS) {
    await shoot(page, info, `project-${section}`, async () => {
      await page.goto(`/#/p/${projectId}/${section}`)
      await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
    })
  }
})

test('admin console routes', async ({ page }, info) => {
  test.setTimeout(180_000)
  await page.goto('/#/admin')
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByLabel('Password').fill(ADMIN.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible()
  for (const s of ['', 'insights', 'users', 'organizations', 'billing', 'plans', 'projects', 'audit', 'settings']) {
    await shoot(page, info, `admin-${s || 'overview'}`, async () => {
      await page.goto(`/#/admin/${s}`)
      await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
    })
  }
})
