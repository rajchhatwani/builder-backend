import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { members, projectId, root, user } from './fixtures/connect-a'
import { connectSpec, preview, previewId, previewPath } from './fixtures/connect-b'
import { builderFixture, id, labels, paths, runtimeFixture, time } from './fixtures/operate-c'
import type { Screen } from './fixtures/operate-c'

const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]
test.use({ locale: 'en-US', timezoneId: 'UTC' })
test.beforeEach(async ({ page }) => {
  const font = (file: string) => fileURLToPath(new URL('./fixtures/ibm-plex/' + file, import.meta.url))
  await page.route(/^https:\/\/fonts\.googleapis\.com\/css2\?family=IBM\+Plex\+Sans/, route =>
    route.fulfill({ path: font('latin.css'), contentType: 'text/css' }))
  await page.route('https://fonts.gstatic.com/v2-test-typography/*.woff2', route =>
    route.fulfill({ path: font(new URL(route.request().url()).pathname.split('/').at(-1)!), contentType: 'font/woff2',
      headers: { 'access-control-allow-origin': '*' } }))
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
  await page.clock.setFixedTime(new Date(time))
})

async function mock(page: Page, screen: Screen | 'pdf', state: State, role = 'owner') {
  let release = () => {}
  const flight = new Promise<void>(resolve => { release = resolve })
  let failing = state === 'error'
  const writes: { path: string; body: unknown }[] = []
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    const method = request.method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299', 'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id, x-preview-token',
    }
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (pathname === '/account/refresh') return json({ access_token: 'fixture' })
    if (pathname === '/account/me') return json(user)
    if (pathname === '/orgs') return json({ items: [], total: 0 })
    if (pathname === root) return json({ id: projectId, name: 'Operations workspace', slug: 'operations', version: 3 })
    if (pathname === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (pathname === root + '/members') return json(members.map(m => m.user_id === user.id ? { ...m, role } : m))
    if (pathname === root + '/workspaces') return json([])
    if (pathname === root + '/spec') return json({ ...connectSpec, auth: { enabled: true, roles: [{ name: 'admin', label: 'Admin' }] } })
    if (pathname === root + '/previews') return json([preview])
    if (pathname === root + previewPath) return json(preview)
    if (pathname === root + previewPath + '/rotate-token') return json({ ...preview, token: 'preview-token' })
    if (pathname === previewPath + '/auth/login') return json({ access_token: 'runtime-user' })
    if (pathname === previewPath + '/openapi.json') return json({ paths: {} })
    if (pathname === (screen === 'pdf' ? root + '/documents' : previewPath + paths[screen])) {
      if (state === 'loading') await flight
      if (failing) return json({ code: 'unavailable', details: [] }, 503)
    }
    if (method === 'PUT' && pathname === root + '/documents') {
      writes.push({ path: pathname, body: request.postDataJSON() })
      return json({ code: 'conflict', message: 'The document settings were updated.', details: [] }, 409)
    }
    const builder = builderFixture(pathname, root, projectId, screen === 'pdf' && state === 'empty')
    if (builder !== undefined) return json(builder)
    if (pathname.startsWith(previewPath + '/')) {
      const path = pathname.slice(previewPath.length)
      expect(request.headers()['x-preview-token']).toBe('preview-token')
      expect(request.headers().authorization).toBe('Bearer runtime-user')
      if (method !== 'GET') writes.push({ path, body: request.postData() ? request.postDataJSON() : null })
      if (path === '/ai/documents/' + id + '/approve') {
        if (!request.postData()) return json({ code: 'review_pending', details: [{ name: 'total' }] }, 409)
        return json({ ...runtimeFixture('/ai/documents/' + id) as object, status: 'approved' })
      }
      const payload = runtimeFixture(path, state === 'empty' && screen !== 'pdf')
      if (payload !== undefined) return json(payload)
    }
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, writes, recover: () => { failing = false } }
}
async function open(page: Page, name: string) {
  await page.goto(root + '/see?preview=' + previewId)
  await page.getByRole('button', { name: 'Reconnect', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm' }).click()
  const signIn = page.getByRole('button', { name: 'Sign in to preview', exact: true })
  await signIn.click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Preview account email').fill('admin@example.test')
  await dialog.getByLabel('Preview password').fill('FixturePassword1')
  await dialog.getByRole('button', { name: 'Sign in to preview', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: 'More', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Search or jump to…' }).click()
  await page.getByRole('option', { name: name + ' Operate', exact: true }).click()
}
async function checkLayout(page: Page) {
  await page.evaluate(() => document.fonts.ready)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0)
  const audit = await new AxeBuilder({ page }).analyze()
  expect(audit.violations.map(v => ({ id: v.id, targets: v.nodes.map(n => n.target) }))).toEqual([])
}

for (const name of [...Object.keys(labels), 'pdf'] as (Screen | 'pdf')[]) {
  for (const state of states) {
    test(name + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, name, state)
      const main = page.getByRole('main')
      const [nav, title, normal, empty] = name === 'pdf' ? ['Documents', 'Documents', 'Invoice template', 'No templates yet.'] : labels[name]
      try {
        if (name === 'pdf') await page.goto(root + '/documents?tab=pdf')
        else await open(page, nav)
        await expect(main.getByRole('heading', { name: title, level: 1, exact: true })).toBeVisible()
        if (name === 'routing' && state !== 'empty') {
          await main.getByLabel('Address', { exact: true }).fill('Central warehouse')
          await main.getByRole('button', { name: 'Geocode', exact: true }).first().click()
        }
        if (state === 'loading') await expect(main.getByRole('status', { name: 'Loading…' }).first()).toBeVisible()
        if (state === 'normal') {
          if (name === 'places' || name === 'pdf') {
            await expect(main.getByRole('table', { name: name === 'places' ? 'Places' : 'Your templates', exact: true })
              .getByRole('cell', { name: normal, exact: true })).toBeVisible()
          } else if (name === 'routing') {
            await expect(main.getByText(normal, { exact: true }).first()).toBeVisible()
          } else {
            await expect(main.getByRole('button', { name: normal, exact: true }).first()).toBeVisible()
          }
        }
        if (state === 'empty') await expect(main.getByText(empty, { exact: true }).first()).toBeVisible()
        if (state === 'error') await expect(main.getByText('Could not load data. Try refreshing the view.', { exact: true }).first()).toBeVisible()
        await checkLayout(page)
        if (state === 'normal') await expect(page).toHaveScreenshot(name + '-normal.png', { fullPage: true })
        if (state === 'loading') await expect(page).toHaveScreenshot(name + '-loading.png', { fullPage: true })
        if (state === 'empty') await expect(page).toHaveScreenshot(name + '-empty.png', { fullPage: true })
        if (state === 'error') await expect(page).toHaveScreenshot(name + '-error.png', { fullPage: true })
      } finally {
        fixture.release()
      }
    })
  }
}

test('acknowledges flagged fields after a document approval conflict', async ({ page }) => {
  const fixture = await mock(page, 'documents', 'normal')
  await open(page, 'Documents')
  await page.getByRole('button', { name: 'Reviewed invoice' }).click()
  await expect(page.locator('mark')).toHaveText('54')
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  await page.getByRole('button', { name: 'Acknowledge and approve' }).click()
  await expect.poll(() => fixture.writes.at(-1)).toEqual({ path: '/ai/documents/' + id + '/approve', body: { acknowledge: ['total'] } })
})

test('PDF settings use the loaded version and preserve the draft on conflict', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.startsWith('w360'), 'PDF authoring is desktop and tablet only')
  const fixture = await mock(page, 'pdf', 'normal')
  await page.goto(root + '/documents?tab=pdf')
  await page.getByLabel('Rate limit per client').fill('40/minute')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Someone else saved these document settings.', { exact: false })).toBeVisible()
  await expect(page.getByLabel('Rate limit per client')).toHaveValue('40/minute')
  expect(fixture.writes.at(-1)?.body).toMatchObject({ expected_version: 3, rate_limit: '40/minute' })
})

test('viewer can read PDF settings without editing them', async ({ page }) => {
  await mock(page, 'pdf', 'normal', 'viewer')
  await page.goto(root + '/documents?tab=pdf')
  await expect(page.getByRole('table', { name: 'Your templates' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
})
