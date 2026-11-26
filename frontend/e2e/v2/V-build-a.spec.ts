import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { desktop, expectations, fixture, pendingPaths, projectRoot, sections } from '../../src/v2/features/build-spec/__tests__/fixtures'
import type { Screen } from '../../src/v2/features/build-spec/__tests__/fixtures'
import { members, projectId, root, user } from './fixtures/connect-a'

const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]

async function mock(page: Page, section: Screen, state: State, role = 'editor') {
  let release = () => {}
  const wait = new Promise<void>(resolve => { release = resolve })
  let markLoadingRequest = () => {}
  const loadingRequest = new Promise<void>(resolve => { markLoadingRequest = resolve })
  let failed = state === 'error'
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299',
      'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id',
    }
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (path === '/account/refresh') return json({ access_token: 'fixture' })
    if (path === '/account/me') return json(user)
    if (path === root) return json({ id: projectId, name: 'Warehouse', version: 5 })
    if (path === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (path === root + '/previews' || path === root + '/tokens') return json([])
    if (path === root + '/presence/heartbeat') return route.fulfill({ status: 204, headers })
    if (path === root + '/members') return json(members.map(member => member.user_id === user.id ? { ...member, role } : member))
    if (path === root + pendingPaths[section]) {
      if (state === 'loading') {
        markLoadingRequest()
        await wait
      }
      if (failed) return json({ code: 'fixture', details: [] }, 500)
    }
    const fixturePath = path.startsWith(root + '/') ? projectRoot + path.slice(root.length) : path
    const value = fixture(fixturePath, role, state === 'empty')
    return value === undefined ? json({ code: 'not_found', details: [] }, 404) : json(value)
  })
  return { loadingRequest, release, recover: () => { failed = false } }
}

test.use({ locale: 'en-US', timezoneId: 'UTC' })
test.beforeEach(async ({ page }) => {
  const font = (file: string) => fileURLToPath(new URL('./fixtures/ibm-plex/' + file, import.meta.url))
  await page.route(/^https:\/\/fonts\.googleapis\.com\/css2\?family=IBM\+Plex\+Sans/, route =>
    route.fulfill({ path: font('latin.css'), contentType: 'text/css' }))
  await page.route('https://fonts.gstatic.com/v2-test-typography/*.woff2', route =>
    route.fulfill({ path: font(new URL(route.request().url()).pathname.split('/').at(-1)!), contentType: 'font/woff2',
      headers: { 'access-control-allow-origin': '*' } }))
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
})

async function expectWorkspace(page: Page) {
  const header = page.getByRole('banner')
  const current = header.getByRole('navigation', { name: 'Breadcrumb' }).locator('[aria-current="page"]')
  await expect(current).toHaveCount(1)
  await expect(current).toContainText('Warehouse')
  await expect(header.getByText('Ready', { exact: true })).toBeVisible()
}

for (const section of sections) {
  for (const state of states) {
    test(section + ' ' + state, async ({ page }, testInfo) => {
      const { loadingRequest, release, recover } = await mock(page, section, state)
      const phone = (page.viewportSize()?.width ?? 0) < 700 && desktop.has(section)
      const example = section === 'specdiff' && state === 'normal' ? '?base=1' : ''
      const content = page.getByRole('main')
      try {
        await page.goto(root + '/' + section + example)
        await expectWorkspace(page)
        if (!phone && state === 'loading') await loadingRequest
        const ready = phone ? content.getByRole('heading', { name: 'Open this on a desktop to edit' })
          : state === 'loading' ? content.getByRole('status', { name: 'Loading…' })
          : state === 'error' ? content.getByText('We could not load this page.')
          : content.getByText(expectations[section][state], { exact: true })
        await expect(ready.first()).toBeVisible()
        if (!phone && state === 'normal' && section === 'machines') {
          await expect(content.getByRole('button', { name: 'Fit diagram' })).toBeVisible()
        }
        if (!phone && (state === 'normal' || state === 'empty') && section !== 'specdiff') {
          await expect(content.getByText('We could not check your project role.')).toHaveCount(0)
        }
        await page.evaluate(() => document.fonts.ready)
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth))
        const { violations } = await new AxeBuilder({ page }).analyze()
        expect(violations.map(({ id, nodes }) => ({ id, nodes: nodes.map(node => node.target) }))).toEqual([])
        if (state === 'normal') await expect(page).toHaveScreenshot(section + '-normal.png', { fullPage: true })
        if (state === 'loading') await expect(page).toHaveScreenshot(section + '-loading.png', { fullPage: true })
        if (state === 'empty') await expect(page).toHaveScreenshot(section + '-empty.png', { fullPage: true })
        if (state === 'error') await expect(page).toHaveScreenshot(section + '-error.png', { fullPage: true })
        if (!phone && state === 'error') {
          recover()
          await content.getByRole('button', { name: 'Try again' }).first().click()
          await expect(content.getByText(expectations[section][section === 'specdiff' ? 'empty' : 'normal'], { exact: true }).first()).toBeVisible()
        }
      } finally {
        release()
      }
      expect(testInfo.project.name).toMatch(/^w(360|768|1280)-(light|dark)$/)
    })
  }
}

test('a viewer can read change history without write access', async ({ page }) => {
  await mock(page, 'history', 'normal', 'viewer')
  await page.goto(root + '/history')
  await expectWorkspace(page)
  await expect(page.getByText('Fields to record')).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'title', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
})
