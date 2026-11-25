import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { members, projectId, root, user } from './fixtures/connect-a'
import { connectSpec, preview, previewId, previewPath } from './fixtures/connect-b'
import { bookingReference, fixedTime, normalTables, ownerPacks, runtimeData, runtimeMain, titles } from './fixtures/operate-b'
import type { Screen } from './fixtures/operate-b'

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
  await page.clock.setFixedTime(new Date(fixedTime))
})

async function mock(page: Page, screen: Screen, state: State, role = 'owner') {
  let release = () => {}
  const flight = new Promise<void>(resolve => { release = resolve })
  let failing = state === 'error'
  let rules = structuredClone(ownerPacks)
  const writes: { path: string; body: unknown }[] = []
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const { pathname } = new URL(request.url())
    const method = request.method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299', 'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
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
    if (pathname === root + '/spec') return json(connectSpec)
    if (pathname === root + '/previews') return json([preview])
    if (pathname === root + previewPath) return json(preview)
    if (pathname === root + previewPath + '/rotate-token') return json({ ...preview, token: 'preview-token' })
    if (pathname === root + '/behavior/packs') {
      if (method === 'PUT') {
        const body = request.postDataJSON()
        writes.push({ path: pathname, body })
        rules = { ...rules, packs: body.packs, version: rules.version + 1 }
      }
      return json(rules)
    }
    if (pathname === previewPath + '/auth/login') return json({ access_token: 'runtime-user' })
    if (pathname === previewPath + '/openapi.json') return json({ paths: {} })
    if (pathname.startsWith(previewPath + '/')) {
      const path = pathname.slice(previewPath.length)
      expect(request.headers()['x-preview-token']).toBe('preview-token')
      expect(request.headers().authorization).toBe('Bearer runtime-user')
      if (method === 'GET' && path === runtimeMain[screen]) {
        if (state === 'loading') await flight
        if (failing) return json({ code: 'unavailable', details: [] }, 503)
      }
      if (method !== 'GET') writes.push({ path, body: request.postData() ? request.postDataJSON() : null })
      const payload = runtimeData(path, state === 'empty')
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
for (const screen of Object.keys(titles) as Screen[]) {
  for (const state of states) {
    test(screen + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, screen, state)
      const main = page.getByRole('main')
      const [title, normal, empty] = titles[screen]
      try {
        await open(page, title)
        await expect(main.getByRole('heading', { level: 1, name: title, exact: true })).toBeVisible()
        await expect(page.getByText('Ready', { exact: true }).first()).toBeVisible()
        if (state === 'loading') {
          await expect(main.getByRole('status', { name: 'Loading…' }).first()).toBeVisible()
        } else if (state === 'normal') {
          if (screen === 'bookings') await expect(main.getByText(normal, { exact: true }).first()).toBeVisible()
          await expect(main.getByRole('table', { name: normalTables[screen], exact: true })
            .getByRole('cell', { name: screen === 'bookings' ? bookingReference : normal, exact: true })).toBeVisible()
        } else {
          await expect(main.getByText(state === 'empty' ? empty : 'Could not load data. Try refreshing the view.', { exact: true }).first()).toBeVisible()
        }
        await checkLayout(page)
        if (state === 'normal') await expect(page).toHaveScreenshot(screen + '-normal.png', { fullPage: true })
        if (state === 'loading') await expect(page).toHaveScreenshot(screen + '-loading.png', { fullPage: true })
        if (state === 'empty') await expect(page).toHaveScreenshot(screen + '-empty.png', { fullPage: true })
        if (state === 'error') await expect(page).toHaveScreenshot(screen + '-error.png', { fullPage: true })
      } finally { fixture.release() }
    })
  }
}
test('Ledger opens a transaction and recovers from a failed list request', async ({ page }) => {
  const fixture = await mock(page, 'ledger', 'error')
  await open(page, 'Ledger')
  const error = page.getByRole('alert').filter({ hasText: 'Could not load data. Try refreshing the view.' })
  await expect(error).toBeVisible()
  fixture.recover()
  await error.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(page.getByRole('table', { name: normalTables.ledger, exact: true })
    .getByRole('cell', { name: titles.ledger[1], exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Show entries', exact: true }).click()
  await expect(page).toHaveURL(/view=txn/)
  await expect(page.getByRole('table', { name: 'Entries', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Reverse', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Reverse', exact: true })).toBeVisible()
})
test('Booking setup saves the original packs version', async ({ page }) => {
  const fixture = await mock(page, 'bookingadmin', 'normal')
  await open(page, 'Booking admin')
  await page.getByLabel('Hold time (seconds)').fill('900')
  await page.getByRole('button', { name: 'Save rules', exact: true }).click()
  await expect(page.getByText('Rules saved. Regenerate and restart the preview to apply your changes.')).toBeVisible()
  expect(fixture.writes[0]?.body).toMatchObject({ expected_version: 3, packs: { booking: { hold_ttl_seconds: 900 } } })
})
