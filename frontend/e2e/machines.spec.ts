/** F1-4: Build > State machines (new shell only). Imports the neutral example specs through the API,
 *  opens the page, checks the diagram and the transition detail, empty/error states, screenshots + axe.
 *  Refresh baselines with `npx playwright test e2e/machines.spec.ts --update-snapshots`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createProjectViaApi, signedInUser, watchProblems, type Api } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

const FIXTURES = fileURLToPath(new URL('../../tests/fixtures/specs/', import.meta.url))

async function importFixture(api: Api, projectId: string, file: string) {
  const spec = JSON.parse(readFileSync(FIXTURES + file, 'utf8'))
  const r = await api.put(`/projects/${projectId}/spec`, spec)
  expect(r.status(), await r.text()).toBe(200)
}

test('state machines: list, diagram, transition detail (leave request)', async ({ page, request }, info) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Leave Flow')
  await importFixture(api, id, 'flow_leave.json')
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/overview`)
  if (info.project.name === 'desktop') {
    await page.locator('aside[data-sidebar]').getByRole('link', { name: 'State machines' }).click()
  } else {
    await page.goto(`/#/p/${id}/machines`) // the rail is behind the menu button on a phone
  }
  await expect(page).toHaveURL(new RegExp(`#/p/${id}/machines$`))
  await expect(page.getByRole('heading', { level: 1, name: 'State machines' })).toBeVisible()

  await expect(page.getByRole('navigation', { name: 'State machines' }).getByText('LeaveRequest')).toBeVisible()
  const diagram = page.getByTestId('machine-diagram')
  await expect(diagram.locator('.react-flow__node')).toHaveCount(6) // requested, manager_review, hr_review, approved, declined, cancelled
  await expect(page.getByTestId('transition-detail-empty')).toBeVisible()

  // click a transition label in the diagram
  await diagram.locator('button[data-transition="manager_approve"]').click()
  const detail = page.getByTestId('transition-detail')
  await expect(detail.getByRole('heading', { name: 'manager_approve' })).toBeVisible()
  await expect(detail).toContainText('manager_review → approved')
  await expect(detail).toContainText('manager')
  await expect(detail).toContainText('Manually')
  await expect(detail).toContainText('None')

  // an automatic transition with a guard, chosen from the list (keyboard path)
  await page.getByRole('list', { name: 'LeaveRequest transitions' }).getByRole('button', { name: /route_short/ }).click()
  await expect(detail.getByRole('heading', { name: 'route_short' })).toBeVisible()
  await expect(detail.locator('code')).toHaveText('days <= 5 and days <= balance')
  await expect(detail).toContainText('Automatically')
  watch.assertNone()
})

test('state machines: switching project data, empty and error states', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const empty = await createProjectViaApi(api, 'No Machines')
  await page.goto(`/#/p/${empty}/machines`)
  await expect(page.getByTestId('machines-empty')).toBeVisible()
  await expect(page.getByText('No state machines yet')).toBeVisible()

  await page.route('**/behavior/state-machines', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ code: 'boom', message: 'Backend exploded' }) }),
  )
  await page.reload()
  await expect(page.getByRole('alert').filter({ hasText: 'We could not load the state machines' })).toBeVisible()
  await expect(page.getByText('Backend exploded')).toBeVisible()
  await page.unroute('**/behavior/state-machines')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByTestId('machines-empty')).toBeVisible()
})

test('state machines: screenshots and axe (invoice approval)', async ({ page, request }, info) => {
  test.setTimeout(120_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Invoice Flow')
  await importFixture(api, id, 'flow_invoices.json')
  await page.goto(`/#/p/${id}/machines`)
  const diagram = page.getByTestId('machine-diagram')
  await expect(diagram.locator('.react-flow__node')).toHaveCount(6)
  await diagram.locator('button[data-transition="approve_large"]').click()
  await expect(page.getByTestId('transition-detail').getByRole('heading', { name: 'approve_large' })).toBeVisible()
  await page.waitForTimeout(800) // fitView settles
  const mask = [page.locator('nav[data-shell="v2"] .muted, nav[data-shell="v2"] [data-testid=shell-project]')]
  await expect.soft(page).toHaveScreenshot('machines-invoices.png', { mask })
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), `axe on ${info.project.name}`).toEqual([])
})
