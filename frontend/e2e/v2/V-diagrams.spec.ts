import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const id = '95ff34eb-4d07-4a60-8669-aaf1cf5442ca'
const root = '/projects/' + id
const user = { id: 'fixture-owner', name: 'Mina Chen', email: 'mina@example.test', platform_role: 'customer', email_verified_at: '2026-01-01' }
const spec = {
  project: { name: 'Invoice project', db_engine: 'postgres' },
  entities: [
    { name: 'Invoice', table_name: 'invoices', plural_path: 'invoices', fields: [{ name: 'reference', type: 'string', required: true }] },
    { name: 'Customer', table_name: 'customers', plural_path: 'customers', fields: [{ name: 'name', type: 'string' }] },
  ],
  relations: [{ kind: 'one_to_many', from_entity: 'Customer', to_entity: 'Invoice', from_name: 'invoices', to_name: 'customer', on_delete: 'restrict' }],
  auth: { enabled: true, roles: [{ name: 'billing', label: 'Billing' }] },
}
const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]

async function mock(page: Page, state: State, role = 'owner') {
  let release = () => {}
  const wait = new Promise<void>(resolve => { release = resolve })
  let failed = state === 'error'
  const requests: string[] = []
  await page.route(url => url.port === '8000', async route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299',
      'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, POST, OPTIONS',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id',
    }
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    requests.push(method + ' ' + path)
    if (path === '/account/refresh') return json({ access_token: 'fixture' })
    if (path === '/account/me') return json(user)
    if (path === '/orgs') return json({ items: [], total: 0 })
    if (path === root) return json({ id, name: 'Invoice project', version: 9 })
    if (path === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (path === root + '/members') return json([{ user_id: user.id, role }])
    if (path === root + '/spec') {
      if (state === 'loading') await wait
      if (failed) return json({ code: 'fixture_unavailable', message: 'Please retry.', details: [] }, 503)
      return json(state === 'empty' ? { project: spec.project, entities: [], relations: [] } : spec)
    }
    if (path === root + '/access/matrix') return json({ roles: ['billing', '(public)'], entities: ['Invoice'],
      cells: [{ entity: 'Invoice', role: 'billing', value: 'yes', layer: 'object', target: 'get' }] })
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, recover: () => { failed = false }, requests }
}

test.beforeEach(async ({ page }) => {
  const fontFixture = (file: string) => fileURLToPath(new URL('./fixtures/ibm-plex/' + file, import.meta.url))
  await page.route(/^https:\/\/fonts\.googleapis\.com\/css2\?family=IBM\+Plex\+Sans/, route =>
    route.fulfill({ path: fontFixture('latin.css'), contentType: 'text/css' }))
  await page.route('https://fonts.gstatic.com/v2-test-typography/*.woff2', route =>
    route.fulfill({ path: fontFixture(new URL(route.request().url()).pathname.split('/').at(-1)!), contentType: 'font/woff2',
      headers: { 'access-control-allow-origin': '*' } }))
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
})

async function open(page: Page, search = '') {
  await page.goto(root + '/diagrams' + search, { waitUntil: 'domcontentloaded' })
  const main = page.getByRole('main')
  await expect(main.getByRole('heading', { name: 'Diagrams', exact: true })).toBeVisible()
  await expect(page.locator('[aria-current="page"]').filter({ hasText: 'Invoice project' })).toBeVisible()
  await expect(page.getByText('Ready', { exact: true })).toBeVisible()
  return main
}

for (const state of states) {
  test('diagrams ' + state, async ({ page }) => {
    const fixture = await mock(page, state)
    try {
      const main = await open(page)
      if (state === 'normal') {
        await expect(main.getByRole('heading', { name: 'Entity-relationship', exact: true })).toBeVisible()
        await expect(main.locator('.v2-diagrams-canvas')).toBeVisible()
      }
      if (state === 'loading') await expect(main.getByRole('status', { name: 'Loading diagrams' })).toBeVisible()
      if (state === 'empty') await expect(main.getByRole('link', { name: 'Open the data model' })).toBeVisible()
      if (state === 'error') await expect(main.getByRole('alert')).toContainText('We could not load your diagrams')

      await page.evaluate(() => document.fonts.ready)
      const size = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
      expect(size[0]).toBe(size[1])
      const audit = await new AxeBuilder({ page }).analyze()
      expect(audit.violations.map(violation => ({ id: violation.id, targets: violation.nodes.map(node => node.target) }))).toEqual([])
      if (state === 'normal') await expect(page).toHaveScreenshot('diagrams-normal.png', { fullPage: true })
      if (state === 'loading') await expect(page).toHaveScreenshot('diagrams-loading.png', { fullPage: true })
      if (state === 'empty') await expect(page).toHaveScreenshot('diagrams-empty.png', { fullPage: true })
      if (state === 'error') await expect(page).toHaveScreenshot('diagrams-error.png', { fullPage: true })
      if (state === 'error') {
        fixture.recover()
        await main.getByRole('button', { name: 'Try again' }).click()
        await expect(main.getByRole('heading', { name: 'Entity-relationship', exact: true })).toBeVisible()
      }
    } finally {
      fixture.release()
    }
  })
}

test('viewer opens an evaluated matrix from the catalogue and reloads its deep link', async ({ page }) => {
  const fixture = await mock(page, 'normal', 'viewer')
  const main = await open(page)
  await expect(main.getByText('Read-only view of the saved project.')).toBeVisible()
  await main.getByRole('button', { name: /Access matrix heat-map/ }).click()
  await expect(page).toHaveURL(/view=D13/)
  await expect(main.getByRole('heading', { name: 'Access matrix heat-map', exact: true })).toBeFocused()
  await expect(main.getByRole('table')).toContainText('billing')
  await page.reload()
  await expect(main.getByRole('table')).toContainText('billing')
  expect(fixture.requests.filter(request => request.endsWith('/access/matrix')).length).toBeGreaterThan(0)
  expect(fixture.requests.some(request => /^(PUT|PATCH|DELETE) /.test(request))).toBe(false)
})
