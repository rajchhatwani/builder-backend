/** F2-5: Workbench drawer (v2 shell): Scalar API reference + request console.
 *  NOT run by its author. Needs the web build/dev server started with VITE_PREVIEW_API_ORIGIN=http://localhost:8799
 *  (E2E_PREVIEW_ORIGIN overrides). The preview API itself is mocked with page.route, so no generated app is needed. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { createProjectViaApi, signedInUser } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
const PREVIEW = process.env.E2E_PREVIEW_ORIGIN ?? 'http://localhost:8799'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

const OPENAPI = {
  openapi: '3.1.0',
  info: { title: 'Invoices', version: '1' },
  paths: {
    '/invoices': {
      get: { summary: 'List invoices', responses: { 200: { description: 'ok' } } },
      post: {
        summary: 'Create invoice',
        requestBody: { content: { 'application/json': { schema: { type: 'object', required: ['number'], properties: { number: { type: 'string' } } } } } },
        responses: { 201: { description: 'created' } },
      },
    },
  },
}
const CORS = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' }

/** Desktop: the top-bar button. Phone: the top bar scrolls off-screen, so use the Ctrl+K palette command. */
async function openWorkbench(page: Page, info: TestInfo) {
  if (info.project.name === 'phone') {
    // the key handler is registered when the shell mounts: wait for the page (as shell-v2.spec does) before pressing
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
    await page.keyboard.press('Control+k')
    const box = page.getByRole('combobox', { name: 'Search commands' })
    await expect(box).toBeFocused()
    await box.fill('Workbench')
    await page.keyboard.press('Enter')
    await expect(page.getByTestId('workbench')).toBeVisible()
  } else {
    await page.getByTestId('workbench-toggle').click()
    await expect(page.getByTestId('workbench-toggle')).toHaveAttribute('aria-expanded', 'true')
  }
}

async function mockPreview(page: Page, seen: { auth: (string | undefined)[]; hosts: string[] }) {
  await page.route(`${PREVIEW}/**`, async (route) => {
    const req = route.request()
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: CORS })
    seen.auth.push(req.headers().authorization)
    const path = new URL(req.url()).pathname
    if (path === '/openapi.json') return route.fulfill({ json: OPENAPI, headers: CORS })
    if (req.method() === 'POST') return route.fulfill({ status: 422, headers: CORS, json: { detail: [{ msg: 'Field required', token: 'LEAK-ME' }] } })
    return route.fulfill({ status: 200, headers: CORS, contentType: 'text/html', body: '<img src=x onerror="window.__xss=1">' })
  })
}

test('workbench: console sends as a role to the preview origin only, history redacts, responses are text, nothing persisted', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Workbench Project')
  const seen = { auth: [] as (string | undefined)[], hosts: [] as string[] }
  page.on('request', (r) => seen.hosts.push(new URL(r.url()).origin))
  await mockPreview(page, seen)

  await page.goto(`/#/p/${id}/overview`)
  await openWorkbench(page, info)
  const drawer = page.getByTestId('workbench')
  await expect(drawer).toBeVisible()
  await expect(page.getByTestId('wb-console')).toBeVisible()

  // GET returns HTML: shown as text, never executed
  await page.getByLabel('Endpoint').selectOption('GET /invoices')
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByTestId('wb-status')).toHaveText('200')
  await expect(page.getByTestId('wb-response-body')).toContainText('<img src=x onerror=')
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined()

  // POST with generated invalid payload, with a token
  await page.getByLabel('Endpoint').selectOption('POST /invoices')
  await page.getByRole('button', { name: 'Generate invalid payload' }).click()
  const role = page.getByLabel('Act as role')
  await expect(role.locator('option').first()).toHaveText('No role (anonymous)')
  const roles = await role.locator('option').count()
  if (roles > 1) {
    await role.selectOption({ index: 1 })
    await page.getByLabel(/Test-user token/).fill('E2E-SECRET-TOKEN')
  }
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByTestId('wb-status')).toHaveText('422')
  if (roles > 1) expect(seen.auth.at(-1)).toBe('Bearer E2E-SECRET-TOKEN')

  // history: two entries, secrets redacted (response "token" key, bearer value)
  await expect(page.getByTestId('wb-history').locator('li')).toHaveCount(2)
  await page.getByTestId('wb-history').getByRole('button').first().click()
  const text = (await drawer.innerText())
  expect(text).not.toContain('LEAK-ME')
  expect(text).not.toContain('E2E-SECRET-TOKEN')

  // no storage holds the token; no request left the app/preview origins
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }))
  expect(stored).not.toContain('E2E-SECRET-TOKEN')
  const idb = await page.evaluate(async () => JSON.stringify(await (indexedDB.databases?.() ?? [])))
  expect(idb).not.toContain('E2E-SECRET')
  const allowed = new Set([PREVIEW, `http://localhost:${WEB}`, `http://localhost:${process.env.E2E_API_PORT ?? '8765'}`])
  expect(seen.hosts.filter((h) => h.startsWith('http') && !allowed.has(h))).toEqual([])

  const axe = await new AxeBuilder({ page }).include('[data-testid=workbench]').analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on console').toEqual([])
})

test('workbench: API reference renders with Scalar (lazy), keyboard close with Escape', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Workbench Ref')
  const seen = { auth: [] as (string | undefined)[], hosts: [] as string[] }
  const scalarChunks: string[] = []
  page.on('request', (r) => { if (/ScalarView/.test(r.url())) scalarChunks.push(r.url()) })
  await mockPreview(page, seen)

  await page.goto(`/#/p/${id}/overview`)
  await openWorkbench(page, info)
  await expect(page.getByTestId('wb-console')).toBeVisible()
  expect(scalarChunks).toHaveLength(0) // not fetched until the tab is shown
  await page.getByRole('button', { name: 'API reference' }).click()
  // Scalar renders the document title and the preview server it was given (operations are lazily rendered, so not asserted)
  await expect(page.getByTestId('wb-reference').getByRole('heading', { level: 1, name: 'Invoices' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('wb-reference')).toContainText(PREVIEW)
  expect(scalarChunks.length).toBeGreaterThan(0)

  await page.getByTestId('workbench').focus()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('workbench')).toBeHidden()
})

test('workbench: preview API down shows an error with retry', async ({ page, request }, info) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Workbench Down')
  await page.route(`${PREVIEW}/**`, (route) => route.abort())
  await page.goto(`/#/p/${id}/overview`)
  await openWorkbench(page, info)
  await expect(page.getByTestId('wb-error')).toContainText('Could not reach the preview API')
  await expect(page.getByTestId('wb-error').getByRole('button', { name: 'Retry' })).toBeVisible()
})
