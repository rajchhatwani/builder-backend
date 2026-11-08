/** F2-2 / F2-3: Connect pages (payments, file uploads, provider integrations, webhooks) and Operate pages
 *  (jobs and schedules, workers, workflows, observability, deploy) in the new shell.
 *  NOT run by its author (ATLAS runs the Playwright stack). No screenshot baselines are asserted.
 *  All new pages follow the single flag ui.shell=v2. The webhooks live panel needs VITE_PREVIEW_API_ORIGIN; this spec accepts
 *  either state (panel, or the "no preview API" note) because the stack may or may not set it. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
// One flag (ui.shell=v2) turns every new page on.
const flags = [{ name: 'ui.shell', value: 'v2' }]
test.use({ storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: flags }] } })

const FIXTURES = fileURLToPath(new URL('../../tests/fixtures/specs/', import.meta.url))
/** The populated pages are fed by answering GET /spec and GET /behavior/<block> with the blocks of a neutral fixture
 *  (the per-block endpoints exist since B2-11; this keeps the fixture independent of what the project stored).
 *  Everything else (auth, validator, forms) hits the real backend. */
async function injectBlocks(page: Page, projectId: string, file: string) {
  const fixture = JSON.parse(readFileSync(FIXTURES + file, 'utf8')) as Record<string, unknown>
  await page.route(new RegExp(`/projects/${projectId}/spec$`), async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const res = await route.fetch()
    const body = (await res.json()) as Record<string, unknown>
    for (const k of ['webhooks', 'providers', 'jobs', 'workflows', 'events']) if (k in fixture) body[k] = fixture[k]
    return route.fulfill({ response: res, json: body })
  })
  await page.route(new RegExp(`/projects/${projectId}/behavior/(jobs|webhooks|providers|workflows)$`), async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const key = route.request().url().split('/').pop() as string
    return route.fulfill({ json: { project_id: projectId, version: 1, row_version: 1, updated_at: null, [key]: fixture[key] ?? null } })
  })
}
/** Every value in the generated form, joined (inputs, textareas, selects). */
const formValues = (page: Page) =>
  page.locator('[data-schema-form]').evaluate((f) => [...f.querySelectorAll('input,textarea,select')].map((e) => (e as HTMLInputElement).value).join('|'))
async function axeNow(page: Page, name: string) {
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), `axe on ${name}`).toEqual([])
}
/** Light and dark (the theme tokens decide colour contrast). */
async function axeBothThemes(page: Page, name: string) {
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'))
  await axeNow(page, `${name}, light`)
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'))
  await axeNow(page, `${name}, dark`)
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'))
}
async function open(page: Page, id: string, section: string, h1: string) {
  await page.goto(`/#/p/${id}/${section}`)
  await expect(page.getByRole('heading', { level: 1, name: h1 })).toBeVisible()
}

// A route callback still running when a test ends fails it ("route.fetch: Test ended"): drop all routes first.
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('connect: webhooks and provider integrations as editable block forms, keyboard and axe', async ({ page, request }, info) => {
  test.setTimeout(120_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Connect Project')
  const watch = watchProblems(page)

  // empty: nothing declared yet
  await open(page, id, 'webhooks', 'Webhooks')
  await expect(page.locator('[data-schema-form]')).toBeVisible() // editable form even when nothing is declared
  await axeNow(page, `${info.project.name} webhooks off`)

  await injectBlocks(page, id, 'webhooks_orders.json')
  await page.reload()
  await expect(page.getByRole('heading', { level: 1, name: 'Webhooks' })).toBeVisible()
  await expect.poll(() => formValues(page)).toContain('order.created')
  await expect.poll(() => formValues(page)).toContain('payments')
  await expect(page.getByTestId('wh-live').or(page.getByTestId('wh-no-origin'))).toBeVisible()
  await axeBothThemes(page, `${info.project.name} webhooks`)

  await open(page, id, 'providers', 'Provider integrations')
  await expect.poll(() => formValues(page)).toContain('acme_mail')
  await expect.poll(() => formValues(page)).toContain('"eu"') // settings render as a JSON textarea: "region": "eu"
  await axeBothThemes(page, `${info.project.name} providers`)

  // keyboard: the command palette reaches the page (the key handler exists once the shell has rendered the h1)
  await expect(page.getByRole('heading', { level: 1, name: 'Provider integrations' })).toBeVisible()
  await page.keyboard.press('Control+k')
  const box = page.getByRole('combobox', { name: 'Search commands' })
  await expect(box).toBeFocused()
  await box.fill('Webhooks')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(new RegExp(`#/p/${id}/webhooks$`))
  await expect(page.getByRole('heading', { level: 1, name: 'Webhooks' })).toBeVisible()

  // the live panel (when a preview API exists) starts closed: a password field for the token, never prefilled
  if (await page.getByTestId('wh-live').count()) {
    await expect(page.getByLabel('Admin bearer token')).toHaveAttribute('type', 'password')
    await expect(page.getByLabel('Admin bearer token')).toHaveValue('')
  }

  // the browser keeps no secret: nothing credential-like in storage
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }))
  expect(stored).not.toMatch(/whsec_|secret_value|bearer/i)
  watch.assertNone()
})

test('connect: payments and file uploads forms generated from the schema', async ({ page, request }, info) => {
  test.setTimeout(120_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Forms Project')
  const watch = watchProblems(page)

  // never saved: defaults are shown and said so
  await open(page, id, 'payments', 'Payments')
  await expect(page.getByTestId('config-fresh')).toBeVisible()
  await expect(page.locator('[data-schema-form]')).toBeVisible()
  await axeBothThemes(page, `${info.project.name} payments fresh`)

  // edit by label, save, the value is on the server
  await page.getByLabel('Max amount minor').fill('12345')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-note')).toHaveText('Saved.')
  expect((await (await api.get(`/projects/${id}/payments`)).json()).max_amount_minor).toBe(12345)

  // a value the backend refuses: its own message is shown next to the field (client hint blocks first, so go below the minimum)
  await page.getByLabel('Max amount minor').fill('0')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('field-error').first()).toBeVisible()
  await axeNow(page, `${info.project.name} payments with an error`)

  // file uploads: renders (404 before the first save)
  await open(page, id, 'storage', 'File uploads')
  await expect(page.locator('[data-schema-form]')).toBeVisible()
  await axeNow(page, `${info.project.name} storage`)

  watch.assertNone()
})

test('operate: jobs, workers and workflows from the spec; observability and deploy forms', async ({ page, request }, info) => {
  test.setTimeout(150_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Operate Project')
  const watch = watchProblems(page)

  await open(page, id, 'jobs', 'Jobs and schedules')
  await expect(page.locator('[data-schema-form]')).toBeVisible()

  await injectBlocks(page, id, 'workflows_orders.json')
  await page.reload()
  await expect(page.getByRole('heading', { level: 1, name: 'Jobs and schedules' })).toBeVisible()
  await expect.poll(() => formValues(page)).toContain('send_receipt_email')
  await expect.poll(() => formValues(page)).toContain('weekly_receipts')
  await axeBothThemes(page, `${info.project.name} jobs`)

  await open(page, id, 'workers', 'Workers and queues')
  await expect(page.getByTestId('workers-table')).toContainText('default')
  await expect(page.getByTestId('queue-advisor')).toContainText('postgres')
  // the advisor route (ADVISOR_PATH in src/api/client.ts) answers, or the page shows its own retryable error
  await expect(page.getByTestId('advisor-queue').or(page.getByTestId('advisor-error'))).toBeVisible()
  await axeBothThemes(page, `${info.project.name} workers`)

  await open(page, id, 'workflows', 'Workflows')
  await expect.poll(() => formValues(page)).toContain('order_flow')
  await expect.poll(() => formValues(page)).toContain('reserve_stock')
  await axeBothThemes(page, `${info.project.name} workflows`)

  // observability form (versioned): toggle a field, save, version moves
  await open(page, id, 'observability', 'Observability')
  await expect(page.locator('[data-schema-form]')).toBeVisible()
  await axeNow(page, `${info.project.name} observability`)
  // never saved: Enabled is off and the other fields are hidden (show-when) until it is ticked
  await page.getByLabel('Enabled').check()
  await page.getByLabel('Service name').fill('orders-api')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-note')).toContainText('Saved (version')
  expect((await (await api.get(`/projects/${id}/observability`)).json()).service_name).toBe('orders-api')

  // deploy form (versioned)
  await open(page, id, 'deployment', 'Deploy')
  await expect(page.locator('[data-schema-form]')).toBeVisible()
  await page.getByLabel('Region').fill('eu-west-1')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-note')).toContainText('Saved (version')
  expect((await (await api.get(`/projects/${id}/deployment`)).json()).region).toBe('eu-west-1')
  await axeNow(page, `${info.project.name} deploy`)

  // the rail lists the new pages under Connect and Operate (desktop only: the phone rail is a drawer)
  if (info.project.name === 'desktop') {
    const rail = page.locator('aside[data-sidebar]')
    for (const name of ['Webhooks', 'Provider integrations']) await expect(rail.locator('[data-rail-group=connect]').getByRole('link', { name })).toBeVisible()
    for (const name of ['Jobs and schedules', 'Workers and queues', 'Workflows']) await expect(rail.locator('[data-rail-group=operate]').getByRole('link', { name })).toBeVisible()
  }
  watch.assertNone()
})
