/** F1-2: Home readiness board (new shell only). Parity of issue messages with the old Overview, the one
 *  Next step, "Not now" for sign-in, rail badges from the same status call, error + retry, screenshots + axe.
 *  Refresh baselines with `npx playwright test e2e/home.spec.ts --update-snapshots`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { createProjectViaApi, importBrokenInvoiceFlow, importInvoiceFlow, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

const importClean = importInvoiceFlow
const importBroken = importBrokenInvoiceFlow

const maskOf = (page: Page) => [page.locator('nav[data-shell="v2"] .muted, nav[data-shell="v2"] [data-testid=shell-project]')]

test('home: issue messages are the same as the old Overview (parity), board shows banner, one next step, 13 sections', async ({ page, request }, info) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Broken Invoices')
  await importBroken(api, id)
  const watch = watchProblems(page)

  // what the API says (source of both screens)
  const status = await (await api.get(`/projects/${id}/status`)).json()
  const validate = await (await api.post(`/projects/${id}/validate`)).json()
  expect(status.issues).toEqual(validate.issues)
  expect(status.issues.length).toBeGreaterThanOrEqual(2)

  await page.goto(`/#/p/${id}/overview`)
  await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
  const banner = page.getByTestId('readiness-banner')
  await expect(banner).toHaveAttribute('data-ready', 'false')
  await expect(banner).toContainText('Not ready yet')
  await expect(banner).toContainText(`${status.issues.length} things need fixing`)

  // exactly one next step, mapped from fix_issues, pointing at the area of the first issue
  await expect(page.getByTestId('next-step')).toHaveCount(1)
  const next = page.getByTestId('next-step')
  await expect(next).toHaveAttribute('data-step', 'fix_issues')
  await expect(next.getByRole('heading', { name: 'Fix what is blocking you' })).toBeVisible()
  await expect(next).toContainText(status.next_step.reason)
  await expect(next.getByRole('link', { name: 'Fix it' })).toHaveAttribute('href', `#/p/${id}/machines`)

  // 13 sections, the state machines card shows its problems and links to the v2 page
  const rows = page.getByTestId('home-sections').locator('li')
  await expect(rows).toHaveCount(13)
  const sm = page.locator('[data-section="state_machines"]')
  await expect(sm).toContainText(`${status.issues.length} problems`)
  await expect(sm.getByRole('link')).toHaveAttribute('href', `#/p/${id}/machines`)
  await expect(page.locator('[data-section="authorization"] a')).toHaveAttribute('href', `#/p/${id}/access`)
  await expect(page.locator('[data-section="model"] a')).toHaveAttribute('href', `#/p/${id}/model`)
  await expect(page.getByTestId('home-counts')).toContainText('1 entity')

  // rail badge (desktop: rail is visible) comes from the same call
  if (info.project.name === 'desktop') {
    await expect(page.locator('aside[data-sidebar] a', { hasText: 'State machines' }).locator('.count-badge')).toHaveText(String(status.issues.length))
  }

  const boardMessages = await page
    .getByTestId('home-issues')
    .locator('li > span')
    .evaluateAll((els) => els.map((e) => (e.firstChild?.textContent ?? '').trim()))
  expect(boardMessages).toEqual(status.issues.map((i: { message: string }) => i.message))

  // PARITY: the old Overview (flag off) lists the very same messages
  await page.evaluate(() => localStorage.setItem('ui.shell', 'v1'))
  await page.reload()
  await expect(page.locator('nav[data-shell="v2"]')).toHaveCount(0)
  await expect(page.locator('.issue-list li').first()).toBeVisible()
  const oldMessages = await page
    .locator('.issue-list li > span')
    .evaluateAll((els) => els.map((e) => (e.firstChild?.textContent ?? '').trim()))
  expect(oldMessages.length).toBeGreaterThanOrEqual(2)
  expect(boardMessages).toEqual(oldMessages)
  watch.assertNone()
})

test('home: empty project asks for an entity, sign-in can be set aside with "Not now", then Generate', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Empty Home')
  await page.goto(`/#/p/${id}/overview`)
  const banner = page.getByTestId('readiness-banner')
  await expect(banner).toContainText('Add at least one entity')
  await expect(page.getByTestId('next-step')).toHaveAttribute('data-step', 'add_entity')
  await expect(page.getByTestId('next-step').getByRole('link', { name: 'Add an entity' })).toHaveAttribute('href', `#/p/${id}/model`)
  await expect(page.getByTestId('home-issues')).toHaveCount(0)

  const r = await api.post(`/projects/${id}/entities`, { name: 'Item' })
  expect(r.status(), await r.text()).toBe(201)
  await page.reload()
  await expect(banner).toHaveAttribute('data-ready', 'true')
  await expect(banner).toContainText('Ready to generate')
  const next = page.getByTestId('next-step')
  await expect(next).toHaveAttribute('data-step', 'consider_auth')
  await expect(next.getByRole('link', { name: 'Set up sign-in' })).toHaveAttribute('href', `#/p/${id}/auth`)

  await next.getByRole('button', { name: 'Not now' }).click()
  await expect(next).toHaveAttribute('data-step', 'generate')
  await expect(next.getByRole('link', { name: 'Generate' })).toHaveAttribute('href', `#/p/${id}/generate`)
  await expect(page.getByTestId('next-step')).toHaveCount(1)
  expect(await page.evaluate((pid) => localStorage.getItem(`home.skipAuth.${pid}`), id)).toBe('1')

  // survives a reload; another project is not affected
  await page.reload()
  await expect(page.getByTestId('next-step')).toHaveAttribute('data-step', 'generate')
  // the dismissal is keyed by project id: the same browser, a project id never dismissed, still gets the suggestion
  expect(await page.evaluate(() => localStorage.getItem('home.skipAuth.00000000-0000-4000-8000-000000000000'))).toBeNull()
})

test('home: loading error shows a message and Try again recovers', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Home Errors')
  await page.route('**/status', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ code: 'boom', message: 'Status exploded' }) }),
  )
  await page.goto(`/#/p/${id}/overview`)
  await expect(page.getByRole('alert').filter({ hasText: 'We could not load the project status' })).toBeVisible()
  await expect(page.getByText('Status exploded')).toBeVisible()
  await page.unroute('**/status')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByTestId('readiness-banner')).toBeVisible()
  await expect(page.getByTestId('next-step')).toHaveAttribute('data-step', 'add_entity')
})

test('home: screenshots and axe (blocked and ready)', async ({ page, request }, info) => {
  test.setTimeout(120_000)
  const api = await signedInUser(page, request)
  const pid = await createProjectViaApi(api, 'Home Visual')
  const mask = maskOf(page)
  for (const name of ['blocked', 'ready'] as const) {
    if (name === 'blocked') await importBroken(api, pid)
    else await importClean(api, pid)
    await page.goto(`/#/p/${pid}/overview`)
    await page.reload() // the status of the other state is cached for a few seconds
    await expect(page.getByTestId('readiness-banner')).toHaveAttribute('data-ready', name === 'ready' ? 'true' : 'false')
    await expect(page.getByTestId('home-sections').locator('li')).toHaveCount(13)
    await page.waitForTimeout(500)
    await expect.soft(page).toHaveScreenshot(`home-${name}.png`, { mask })
    const axe = await new AxeBuilder({ page }).analyze()
    expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), `axe on ${info.project.name} ${name}`).toEqual([])
  }
  // dark theme too (axe only)
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'))
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), `axe dark on ${info.project.name}`).toEqual([])
})
