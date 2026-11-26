import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { members, projectId, root, user } from './fixtures/connect-a'
import { preview, previewId, previewPath } from './fixtures/connect-b'
import { aiSpec, caller, evalId, labels, paths, runId, runtimeFixture, sourceId, time } from './fixtures/operate-d'
import type { Screen } from './fixtures/operate-d'

const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]
const headers = {
  'access-control-allow-origin': 'http://localhost:5299', 'access-control-allow-credentials': 'true',
  'access-control-allow-methods': 'GET, POST, DELETE, OPTIONS',
  'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id, x-preview-token',
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
  await page.clock.setFixedTime(new Date(time))
})

async function mock(page: Page, screen: Screen, state: State = 'normal', role = 'owner') {
  let release = () => {}
  const flight = new Promise<void>(resolve => { release = resolve })
  let failing = state === 'error'
  let deleted = false
  const requests: { path: string; method: string; params: URLSearchParams; body: unknown }[] = []
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    const method = request.method()
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (pathname === '/account/refresh') return json({ access_token: 'fixture' })
    if (pathname === '/account/me') return json(user)
    if (pathname === '/orgs') return json({ items: [], total: 0 })
    if (pathname === root) return json({ id: projectId, name: 'Operations workspace', slug: 'operations', version: 3 })
    if (pathname === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (pathname === root + '/members') return json(members.map(member => member.user_id === user.id ? { ...member, role } : member))
    if (pathname === root + '/workspaces') return json([])
    if (pathname === root + '/spec') return json(aiSpec)
    if (pathname === root + '/previews') return json([preview])
    if (pathname === root + previewPath) return json(preview)
    if (pathname === root + previewPath + '/rotate-token') return json({ ...preview, token: 'preview-token' })
    if (pathname === previewPath + '/auth/login') return json({ access_token: 'runtime-user' })
    if (pathname === previewPath + '/openapi.json') return json({ paths: {} })
    if (pathname.startsWith(previewPath + '/')) {
      expect(request.headers()['x-preview-token']).toBe('preview-token')
      expect(request.headers().authorization).toBe('Bearer runtime-user')
      const path = pathname.slice(previewPath.length)
      requests.push({ path, method, params: url.searchParams, body: request.postData() ? request.postDataJSON() : undefined })
      if (method === 'GET' && (paths[screen] as readonly string[]).includes(path)) {
        if (state === 'loading') await flight
        if (failing) return json({ code: 'unavailable', details: [] }, 503)
      }
      if (path === '/ai/knowledge/sources/' + sourceId && method === 'DELETE') {
        deleted = true
        return route.fulfill({ status: 204, headers })
      }
      const payload = runtimeFixture(path, state === 'empty' || (deleted && path === '/ai/knowledge/sources'), method)
      if (payload !== undefined) return json(payload, method === 'POST' && (path.endsWith('/sources') || path.endsWith('/run') || path.endsWith('/runs')) ? 201 : 200)
    }
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, requests, recover: () => { failing = false } }
}

async function open(page: Page, name: string) {
  await page.goto(root + '/see?preview=' + previewId)
  await page.getByRole('button', { name: 'Reconnect', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm' }).click()
  await page.getByRole('button', { name: 'Sign in to preview', exact: true }).click()
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
  expect(audit.violations.map(violation => ({ id: violation.id, targets: violation.nodes.map(node => node.target) }))).toEqual([])
}

for (const screen of Object.keys(labels) as Screen[]) {
  for (const state of states) {
    test(screen + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, screen, state)
      const [nav, title, normal, empty] = labels[screen]
      const main = page.getByRole('main')
      try {
        await open(page, nav)
        await expect(main.getByRole('heading', { name: title, level: 1, exact: true })).toBeVisible()
        if (state === 'loading') {
          await expect(main.getByRole('status', { name: 'Loading…' }).first()).toBeVisible()
        } else {
          await expect.poll(() => (paths[screen] as readonly string[]).every(path => fixture.requests.some(request => request.path === path))).toBe(true)
          if (state === 'normal') await expect(main.getByTestId(normal)).toBeVisible()
          if (state === 'empty') await expect(main.getByText(empty, { exact: true })).toBeVisible()
          if (state === 'error') await expect(main.getByText('Could not load data. Try refreshing the view. (503 unavailable)', { exact: true }).first()).toBeVisible()
          await expect(main.getByRole('status', { name: 'Loading…' })).toHaveCount(0)
        }
        await checkLayout(page)
        if (state === 'normal') await expect(page).toHaveScreenshot(screen + '-normal.png', { fullPage: true })
        if (state === 'loading') await expect(page).toHaveScreenshot(screen + '-loading.png', { fullPage: true })
        if (state === 'empty') await expect(page).toHaveScreenshot(screen + '-empty.png', { fullPage: true })
        if (state === 'error') await expect(page).toHaveScreenshot(screen + '-error.png', { fullPage: true })
      } finally {
        fixture.release()
      }
    })
  }
}

test('usage keeps caller, stage and status on refresh', async ({ page }) => {
  const fixture = await mock(page, 'aiusage')
  await open(page, 'AI usage')
  await expect(page.getByTestId('usage-spent')).toHaveText('USD 0.250000')
  await expect(page.getByTestId('usage-remaining')).toHaveText('USD 0.700000')
  await expect(page.getByTestId('usage-calls')).toHaveText('3 / 1')
  await page.getByTestId('calls-stage').fill('support')
  await page.getByTestId('calls-caller').fill(caller)
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await page.getByTestId('calls-status').click()
  await page.getByRole('option', { name: 'Succeeded', exact: true }).click()
  const matches = () => fixture.requests.filter(item => item.path === '/ai/calls' && item.params.get('caller_id') === caller &&
    item.params.get('stage') === 'support' && item.params.get('status') === 'ok' && item.params.get('offset') === '0')
  await expect.poll(() => matches().length).toBe(1)
  await page.getByTestId('usage-refresh').click()
  await expect.poll(() => matches().length).toBe(2)
})

test('knowledge submits role scope and limits and confirms removal', async ({ page }) => {
  const fixture = await mock(page, 'knowledge')
  await open(page, 'Knowledge')
  await page.getByTestId('source-create').click()
  await expect(page.getByTestId('source-create-error')).toHaveText('Enter a title.')
  await page.getByTestId('source-title').fill('Policy')
  await page.getByTestId('source-text').fill('Returns are free.')
  await page.getByTestId('source-roles').fill('admin, staff')
  await page.getByTestId('source-create').click()
  await expect(page.getByTestId('source-notice')).toHaveText('Source added.')
  expect(fixture.requests.find(item => item.method === 'POST' && item.path.endsWith('/sources'))?.body)
    .toEqual({ title: 'Policy', text: 'Returns are free.', allowed_roles: ['admin', 'staff'] })
  await page.getByTestId('search-query').fill('refunds')
  await page.getByTestId('search-limit').fill('7')
  await page.getByTestId('search-run').click()
  await expect(page.getByTestId('search-hit')).toContainText('Refunds take five days.')
  expect(fixture.requests.find(item => item.path.endsWith('/search'))?.body).toEqual({ query: 'refunds', limit: 7 })
  await page.getByTestId('ask-question').fill('How long do refunds take?')
  await page.getByTestId('ask-run').click()
  await expect(page.getByTestId('ask-answer')).toHaveText('<b>Five days.</b>')
  await expect(page.getByTestId('ask-citation')).toHaveCount(1)
  expect(fixture.requests.find(item => item.path.endsWith('/ask'))?.body).toEqual({ question: 'How long do refunds take?', limit: 4 })
  await page.getByTestId('source-delete').click()
  const dialog = page.getByRole('dialog', { name: 'Delete source' })
  expect(fixture.requests.some(item => item.method === 'DELETE')).toBe(false)
  await dialog.getByRole('button', { name: 'Delete source', exact: true }).click()
  await expect(page.getByTestId('source-notice')).toHaveText('Source deleted.')
  await expect(page.getByTestId('source-row')).toHaveCount(0)
})

test('evals shows the dry verdict and the exact suite filter', async ({ page }) => {
  const fixture = await mock(page, 'evals')
  await open(page, 'Evaluations')
  await expect(page.getByTestId('suite-row')).toContainText('Never run')
  await page.getByTestId('runs-suite').fill('returns')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await page.getByTestId('run-open').click()
  await expect(page.getByTestId('eval-verdict')).toHaveText('Suite failed')
  expect(fixture.requests.some(item => item.path === '/ai/evals/runs' && item.params.get('suite') === 'returns')).toBe(true)
  expect(fixture.requests.some(item => item.path.endsWith(evalId))).toBe(true)
  await page.getByTestId('suite-run').click()
  await expect(page.getByRole('heading', { name: 'Result of the run you just started' })).toBeVisible()
  await expect(page.getByTestId('eval-case').nth(1)).toContainText('Error: budget_exceeded')
  expect(fixture.requests.find(item => item.method === 'POST' && item.path.endsWith('/run'))?.body).toBeUndefined()
})

test('agent history and stats scope independently and draft runs require confirmation', async ({ page }) => {
  const fixture = await mock(page, 'agentruns')
  await open(page, 'Agent runs')
  await page.getByRole('combobox', { name: 'Stats agent' }).click()
  await page.getByRole('option', { name: 'scribe' }).click()
  await expect.poll(() => fixture.requests.some(item => item.path.endsWith('/stats') && item.params.get('agent') === 'scribe')).toBe(true)
  expect(fixture.requests.every(item => item.path !== '/ai/agents/runs' || !item.params.has('agent'))).toBe(true)
  await page.getByTestId('start-run').click()
  await expect(page.getByTestId('start-error')).toHaveText('Choose an agent.')
  await page.getByTestId('start-agent').click()
  await page.getByRole('option', { name: 'scribe' }).click()
  await page.getByTestId('start-goal').fill('Summarize returns')
  await page.getByTestId('start-run').click()
  const dialog = page.getByRole('dialog', { name: 'Confirm run' })
  await expect(dialog).toContainText('scribe')
  expect(fixture.requests.some(item => item.method === 'POST')).toBe(false)
  await dialog.getByTestId('start-yes').click()
  await expect(page.getByTestId('start-ok')).toBeVisible()
  expect(fixture.requests.find(item => item.method === 'POST')?.body).toMatchObject({
    goal: 'Summarize returns', mode: 'draft', idempotency_key: expect.any(String),
  })
  await expect(page.getByTestId('run-status')).toHaveText('completed')
  await expect(page.getByTestId('run-proposal')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Review proposals in AI actions' })).toHaveAttribute('href', new RegExp('agentactions.*run=' + runId))
})

test('failed usage reads recover on Try again', async ({ page }) => {
  const fixture = await mock(page, 'aiusage', 'error')
  await open(page, 'AI usage')
  const budget = page.getByRole('heading', { name: 'Budget and usage' }).locator('..')
  await expect(budget.getByRole('alert')).toContainText('503 unavailable')
  fixture.recover()
  await budget.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(page.getByTestId('usage-spent')).toBeVisible()
})
