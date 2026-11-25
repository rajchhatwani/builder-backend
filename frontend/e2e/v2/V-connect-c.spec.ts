import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { members, projectId, root, user } from './fixtures/connect-a'
import { packRoles, packs, packsReply, packScreens, packSpec } from './fixtures/connect-c'

test.use({ locale: 'en-US', timezoneId: 'UTC' })
const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]
type Screen = keyof typeof packScreens
const path = root + '/behavior/packs'

test.beforeEach(async ({ page }) => {
  const font = (file: string) => fileURLToPath(new URL('./fixtures/ibm-plex/' + file, import.meta.url))
  await page.route(/^https:\/\/fonts\.googleapis\.com\/css2\?family=IBM\+Plex\+Sans/, route =>
    route.fulfill({ path: font('latin.css'), contentType: 'text/css' }))
  await page.route('https://fonts.gstatic.com/v2-test-typography/*.woff2', route =>
    route.fulfill({ path: font(new URL(route.request().url()).pathname.split('/').at(-1)!), contentType: 'font/woff2',
      headers: { 'access-control-allow-origin': '*' } }))
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
})

async function mock(page: Page, screen: Screen, state: State, role = 'owner') {
  let release = () => {}
  const waiting = new Promise<void>(resolve => { release = resolve })
  let fail = state === 'error'
  let version = 3
  let current: Record<string, unknown> = structuredClone(packs)
  const [pack, block] = packScreens[screen].path
  if (state === 'empty') {
    if (block) (current[pack] as Record<string, unknown>)[block] = null
    else current[pack] = null
  }
  const writes: unknown[] = []
  let conflict = false
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    const method = request.method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299', 'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, OPTIONS, PUT', 'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id',
    }
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (pathname === '/account/refresh') return json({ access_token: 'fixture' })
    if (pathname === '/account/me') return json(user)
    if (pathname === '/orgs') return json({ items: [], total: 0 })
    if (pathname === root) return json({ id: projectId, name: 'People Directory', slug: 'directory', version: 1 })
    if (pathname === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (pathname === root + '/members') return json(members.map(member => member.user_id === user.id ? { ...member, role } : member))
    if (pathname === root + '/workspaces' || pathname === root + '/previews') return json([])
    if (pathname === root + '/spec') return json(packSpec)
    if (pathname === root + '/behavior/roles') return json({ roles: packRoles })
    if (pathname === root + '/behavior/issues') {
      const booking = current.booking as typeof packs.booking | null
      return json({ issues: booking && !booking.manage_roles.length ? [{
        path: 'packs.booking.manage_roles', code: 'empty',
        message: 'manage_roles needs at least one role (an empty list would make nobody a manager)',
      }] : [] })
    }
    if (pathname === path) {
      if (method === 'PUT') {
        const body = request.postDataJSON()
        writes.push(body)
        if (conflict) {
          conflict = false
          version++
          return json({ code: 'conflict', message: 'the packs changed since you opened them', details: [] }, 409)
        }
        current = body.packs
        return json(packsReply(current, ++version))
      }
      if (state === 'loading') await waiting
      if (fail) return json({ code: 'unavailable', message: 'Retry.', details: [] }, 503)
      return json(packsReply(current, version))
    }
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, writes, recover: () => { fail = false }, conflict: () => { conflict = true } }
}

async function verify(page: Page) {
  await page.evaluate(() => document.fonts.ready)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0)
  const audit = await new AxeBuilder({ page }).analyze()
  expect(audit.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) }))).toEqual([])
}

for (const [id, copy] of Object.entries(packScreens)) {
  const screen = id as Screen
  for (const state of states) {
    test(screen + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, screen, state)
      const main = page.getByRole('main')
      try {
        await page.goto(root + '/' + screen + (screen === 'bookingsettings' ? '?bookingKind=0' : ''), { waitUntil: 'domcontentloaded' })
        await expect(main.getByRole('heading', { name: copy.title, exact: true })).toBeVisible()
        await expect(page.getByText('Ready', { exact: true }).first()).toBeVisible()
        if (state === 'loading') await expect(main.getByRole('status', { name: 'Loading…' }).first()).toBeVisible()
        if (state === 'empty') await expect(main.getByTestId('block-off')).toBeVisible()
        if (state === 'error') await expect(main.getByText('We could not load ' + copy.title.toLowerCase() + '.', { exact: true })).toBeVisible()
        if (state === 'normal') {
          await expect(main.getByRole('heading', { name: copy.normal, exact: true })).toBeVisible()
          await expect(main.getByTestId('switch-off').getByRole('button')).toBeEnabled()
          if (screen !== 'currencysettings') await expect(main.getByRole('checkbox', { name: 'Member', exact: true }).first()).toBeVisible()
        }
        await verify(page)
        if (screen === 'ledgersettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('ledgersettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('ledgersettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('ledgersettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('ledgersettings-error.png', { fullPage: true })
        }
        if (screen === 'currencysettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('currencysettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('currencysettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('currencysettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('currencysettings-error.png', { fullPage: true })
        }
        if (screen === 'reconsettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('reconsettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('reconsettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('reconsettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('reconsettings-error.png', { fullPage: true })
        }
        if (screen === 'invoicingsettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('invoicingsettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('invoicingsettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('invoicingsettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('invoicingsettings-error.png', { fullPage: true })
        }
        if (screen === 'bookingsettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('bookingsettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('bookingsettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('bookingsettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('bookingsettings-error.png', { fullPage: true })
        }
        if (screen === 'geosettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('geosettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('geosettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('geosettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('geosettings-error.png', { fullPage: true })
        }
        if (screen === 'locationsettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('locationsettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('locationsettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('locationsettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('locationsettings-error.png', { fullPage: true })
        }
      } finally { fixture.release() }
    })
  }
}

test('ledger preserves sibling packs through validation, conflict, save and removal', async ({ page }) => {
  const fixture = await mock(page, 'ledgersettings', 'normal')
  await page.goto(root + '/ledgersettings')
  const entries = page.getByRole('spinbutton', { name: 'Max entries' })
  await expect(entries).toBeEditable()
  await entries.fill('1')
  await entries.blur()
  await expect(page.getByText('Max entries must be a whole number from 2 to 1,000.')).toBeVisible()
  await entries.fill('250')
  fixture.conflict()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('conflict')).toBeVisible()
  await expect(entries).toHaveValue('250')
  await page.getByRole('button', { name: 'Reload', exact: true }).click()
  await expect(entries).toHaveValue('100')
  await entries.fill('250')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-note')).toHaveText('Saved (version 5).')
  await page.reload()
  await expect(entries).toHaveValue('250')
  await page.getByRole('button', { name: 'Switch off ledger settings' }).click()
  await expect(page.getByRole('dialog').getByText('Reconciliation settings depend on the ledger.')).toBeVisible()
  await page.getByRole('button', { name: 'Yes, switch off' }).click()
  await expect(page.getByTestId('block-off')).toBeVisible()
  expect(fixture.writes).toMatchObject([
    { expected_version: 3, packs: { money: { ledger: { max_entries: 250 } } } },
    { expected_version: 4, packs: { ...packs, money: { ...packs.money, ledger: { ...packs.money.ledger, max_entries: 250 } } } },
    { expected_version: 5, packs: { booking: packs.booking, operations: packs.operations, ai: packs.ai } },
  ])
})

test('booking edits structured windows and confirms clearing manager roles', async ({ page }) => {
  const fixture = await mock(page, 'bookingsettings', 'normal')
  await page.goto(root + '/bookingsettings?bookingKind=0')
  await page.getByText('Monday · 1 window', { exact: true }).click()
  await page.getByRole('textbox', { name: 'Window 1 end' }).fill('16:00')
  const manage = page.getByRole('group', { name: 'Manage roles' })
  await manage.getByRole('checkbox', { name: 'Administrator' }).uncheck()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  const confirmation = page.getByRole('dialog')
  await expect(confirmation.getByText('Any signed-in user could call manager routes. Nobody would have manager status for booking visibility.')).toBeVisible()
  await confirmation.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-note')).toHaveText('Saved (version 4).')
  await expect(page.getByText(/manage_roles needs at least one role/)).toBeVisible()
  expect(fixture.writes).toMatchObject([{ expected_version: 3, packs: { booking: {
    manage_roles: [], kinds: [{ schedule: { mon: [{ start: '09:00', end: '16:00' }] } }, {}],
  } } }])
})

test('viewer can review geo settings without write controls', async ({ page }) => {
  await mock(page, 'geosettings', 'normal', 'viewer')
  await page.goto(root + '/geosettings')
  await expect(page.getByText('You can look at this but not change it. Your role is viewer.')).toBeVisible()
  await expect(page.getByRole('spinbutton', { name: 'Grid cell micro' })).not.toBeEditable()
  await expect(page.getByRole('button', { name: 'Switch off geo settings' })).toHaveCount(0)
  await verify(page)
})
