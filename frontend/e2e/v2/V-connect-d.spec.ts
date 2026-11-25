import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { members, projectId, root, user } from './fixtures/connect-a'
import { packRoles, packsReply } from './fixtures/connect-c'
import { advancedPacks, advancedPackSpec, advancedScreens } from './fixtures/connect-d'

test.use({ locale: 'en-US', timezoneId: 'UTC' })
const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]
type Screen = keyof typeof advancedScreens
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
  let current: Record<string, unknown> = structuredClone(advancedPacks)
  const [pack, block] = advancedScreens[screen].path
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
    if (pathname === root + '/spec') return json(advancedPackSpec)
    if (pathname === root + '/behavior/roles') return json({ roles: packRoles })
    if (pathname === root + '/behavior/issues') return json({ issues: [] })
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

for (const [id, copy] of Object.entries(advancedScreens)) {
  const screen = id as Screen
  for (const state of states) {
    test(screen + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, screen, state)
      const main = page.getByRole('main')
      try {
        await page.goto(root + '/' + screen, { waitUntil: 'domcontentloaded' })
        await expect(main.getByRole('heading', { name: copy.title, exact: true })).toBeVisible()
        await expect(page.getByText('Ready', { exact: true }).first()).toBeVisible()
        if (state === 'loading') await expect(main.getByRole('status', { name: 'Loading…' }).first()).toBeVisible()
        if (state === 'empty') await expect(main.getByTestId('block-off')).toBeVisible()
        if (state === 'error') await expect(main.getByText('We could not load ' + copy.title.toLowerCase() + '.', { exact: true })).toBeVisible()
        if (state === 'normal') {
          await expect(main.getByRole('heading', { name: copy.normal, exact: true })).toBeVisible()
          await expect(main.getByTestId('switch-off').getByRole('button')).toBeEnabled()
          await expect(main.getByRole('checkbox', { name: 'Member', exact: true }).first()).toBeVisible()
        }
        await verify(page)
        if (screen === 'matchingsettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('matchingsettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('matchingsettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('matchingsettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('matchingsettings-error.png', { fullPage: true })
        }
        if (screen === 'predictionsettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('predictionsettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('predictionsettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('predictionsettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('predictionsettings-error.png', { fullPage: true })
        }
        if (screen === 'aigatewaysettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('aigatewaysettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('aigatewaysettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('aigatewaysettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('aigatewaysettings-error.png', { fullPage: true })
        }
        if (screen === 'aidocssettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('aidocssettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('aidocssettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('aidocssettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('aidocssettings-error.png', { fullPage: true })
        }
        if (screen === 'knowledgesettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('knowledgesettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('knowledgesettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('knowledgesettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('knowledgesettings-error.png', { fullPage: true })
        }
        if (screen === 'agentssettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('agentssettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('agentssettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('agentssettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('agentssettings-error.png', { fullPage: true })
        }
        if (screen === 'evalssettings') {
          if (state === 'normal') await expect(page).toHaveScreenshot('evalssettings-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('evalssettings-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('evalssettings-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('evalssettings-error.png', { fullPage: true })
        }
      } finally { fixture.release() }
    })
  }
}


test('matching preserves sibling blocks through a conflict, save, and removal', async ({ page }) => {
  const fixture = await mock(page, 'matchingsettings', 'normal')
  await page.goto(root + '/matchingsettings')
  const load = page.getByRole('spinbutton', { name: 'Max load' })
  await expect(load).toBeEditable()
  await load.fill('0')
  await load.blur()
  await expect(page.getByText('Max load must be a whole number from 1 to 1,000,000.')).toBeVisible()
  await load.fill('20')
  fixture.conflict()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('conflict')).toBeVisible()
  await expect(load).toHaveValue('20')
  await page.getByRole('button', { name: 'Reload', exact: true }).click()
  await expect(load).toHaveValue('10')
  await load.fill('20')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-note')).toHaveText('Saved (version 5).')
  await page.getByRole('button', { name: 'Switch off matching settings' }).click()
  await page.getByRole('button', { name: 'Yes, switch off' }).click()
  await expect(page.getByTestId('block-off')).toBeVisible()
  expect(fixture.writes).toMatchObject([
    { expected_version: 3 },
    { expected_version: 4, packs: { ...advancedPacks, operations: { ...advancedPacks.operations,
      matching: { ...advancedPacks.operations.matching, max_load: 20 } } } },
    { expected_version: 5, packs: { ai: advancedPacks.ai, operations: { prediction: advancedPacks.operations.prediction } } },
  ])
  expect(fixture.writes[2]).not.toHaveProperty('packs.operations.matching')
})

test('viewer can read agent settings without write controls', async ({ page }) => {
  await mock(page, 'agentssettings', 'normal', 'viewer')
  await page.goto(root + '/agentssettings')
  const main = page.getByRole('main')
  await expect(main.getByText('You can look at this but not change it. Your role is viewer.')).toBeVisible()
  await expect(main.getByRole('textbox', { name: 'Description' })).not.toBeEditable()
  await expect(main.getByRole('button', { name: 'Add agent' })).toHaveCount(0)
  await verify(page)
})

test('a failed load can recover with Try again', async ({ page }) => {
  const fixture = await mock(page, 'knowledgesettings', 'error')
  await page.goto(root + '/knowledgesettings')
  const retry = page.getByRole('main').getByRole('button', { name: 'Try again' })
  await expect(retry).toBeVisible()
  fixture.recover()
  await retry.click()
  await expect(page.getByRole('heading', { name: 'Source limits' })).toBeVisible()
})
