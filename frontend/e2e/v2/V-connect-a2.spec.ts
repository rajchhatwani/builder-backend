import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { members, projectId, root, time, user } from './fixtures/connect-a'
import { blockReply, blocks, spec } from './fixtures/connect-a2'
import type { Block } from './fixtures/connect-a2'

test.use({ locale: 'en-US', timezoneId: 'UTC' })
const screens = ['forms', 'notifications', 'notiftypes', 'webhooks'] as const
const states = ['normal', 'loading', 'empty', 'error'] as const
type Screen = typeof screens[number]
type State = typeof states[number]
const previewId = 'c4e1a466-1ed2-4711-b4bf-6a221f2c8a74'
const previewPath = '/previews/' + previewId
const preview = { id: previewId, project_id: projectId, workspace_id: null, is_preview: true, state: 'running',
  url_path: previewPath, created_at: time, last_request_at: time, expires_at: time, limits: {} }
const subId = '57d9995e-3b33-4a95-b51a-38a9df702ce0'
const deliveryId = '5edbf81c-525a-42ea-9aa5-4ecb3ac8a36a'
const subscription = {
  id: subId, url: 'https://hooks.example.test/invoices', description: '', event_types: ['invoice.created'], status: 'active',
  disabled_reason: null, consecutive_failures: 0, secret_version: 1, rotating: false, created_at: time,
}

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
  let failed = state === 'error'
  const block: Block = screen === 'webhooks' ? 'webhooks' : 'notifications'
  let version = state === 'empty' ? 0 : 3
  let value: unknown = state === 'empty' ? null : blocks[block]
  let subscriptions = [subscription]
  const writes: { path: string; method: string; body: unknown }[] = []
  if (screen === 'forms' && ['loading', 'error'].includes(state)) {
    await page.route(/\/src\/forms\/schemas\/observability\.json(?:\?.*)?$/, async route => {
      if (state === 'loading') await waiting
      if (failed) return route.fulfill({ status: 503, body: '' })
      return route.continue()
    })
  }
  await page.route(url => url.port === '8000', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299', 'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, POST, OPTIONS, PUT, PATCH, DELETE',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id, x-preview-token',
    }
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (path === '/account/refresh') return json({ access_token: 'fixture' })
    if (path === '/account/me') return json(user)
    if (path === '/orgs') return json({ items: [], total: 0 })
    if (path === root) return json({ id: projectId, name: 'People Directory', slug: 'directory', version: 1 })
    if (path === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (path === root + '/members') return json(members.map(member => member.user_id === user.id ? { ...member, role } : member))
    if (path === root + '/spec') return json(spec)
    if (path === root + '/behavior/roles') return json({ roles: spec.auth.roles })
    if (path === root + '/behavior/issues') return json({ issues: [] })
    if (path === root + '/workspaces') return json([])
    if (path === root + '/previews' && method === 'GET') return json([preview])
    if (path === root + previewPath) return json(preview)
    if (path === root + previewPath + '/rotate-token' && method === 'POST') return json({ ...preview, token: 'preview-token' })
    if (path === previewPath + '/openapi.json') return json({ paths: {} })
    if (path === root + '/behavior/' + block && method === 'GET') {
      if (screen !== 'forms' && state === 'loading') await waiting
      if (failed) return json({ code: 'unavailable', message: 'Retry.', details: [] }, 503)
      return json(blockReply(block, value, version))
    }
    if (path.startsWith(previewPath + '/webhooks/')) {
      expect(route.request().headers()['x-preview-token']).toBe('preview-token')
      expect(route.request().headers().authorization).toBe('Bearer generated-admin')
      const tail = path.slice(previewPath.length)
      if (method === 'GET' && tail === '/webhooks/subscriptions') return json(subscriptions)
      if (method === 'GET' && tail === '/webhooks/subscriptions/' + subId) return json(subscriptions[0])
      if (method === 'GET' && tail === '/webhooks/events') return json(['invoice.created'])
      if (method === 'GET' && tail === '/webhooks/inbound') return json([{ name: 'invoice_status', has_secret: false, secret_version: null, rotating: false, updated_at: null }])
      if (method === 'GET' && tail.endsWith('/deliveries')) return json([{
        id: deliveryId, event_id: 'event-id', event_type: 'invoice.created', status: 'delivered', attempts: 1,
        last_status_code: 200, last_error: null, created_at: time, finished_at: time,
      }])
      if (method === 'GET' && tail.endsWith('/attempts')) return json([{ attempt: 1, outcome: 'delivered', status_code: 200, duration_ms: 18, created_at: time }])
      if (method === 'POST' && tail.endsWith('/rotate')) {
        writes.push({ path, method, body: route.request().postDataJSON() })
        subscriptions = [{ ...subscription, secret_version: 2, rotating: true }]
        return json({ ...subscriptions[0], secret: 'whsec_fixture_revealed_once' })
      }
    }
    if (path === root + '/behavior/' + block && method === 'PUT') {
      const body = route.request().postDataJSON()
      writes.push({ path, method, body })
      value = body[block]
      return json(blockReply(block, value, ++version))
    }
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, recover: () => { failed = false }, writes }
}

const copy = {
  forms: { title: 'Forms preview', normal: 'Flat toggles and numbers, show-when', empty: 'Start with schema defaults', error: 'The schema preview could not be rendered.' },
  notifications: { title: 'Notifications', normal: 'Default template', empty: 'This spec declares no notification types (notifications are off)', error: 'Could not load notifications: Could not load the spec' },
  notiftypes: { title: 'Notification types', normal: 'Notification settings', empty: 'No notification types', error: 'Could not load the notification settings.' },
  webhooks: { title: 'Webhooks', normal: 'Webhook settings', empty: 'Webhooks are not set up', error: 'Could not load webhook settings.' },
} as const

for (const screen of screens) {
  for (const state of states) {
    test(screen + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, screen, state)
      try {
        await page.goto(root + '/' + screen + (screen === 'forms' && state === 'empty' ? '?tab=lists' : ''), { waitUntil: 'domcontentloaded' })
        const main = page.getByRole('main')
        await expect(main.getByRole('heading', { name: copy[screen].title, exact: true })).toBeVisible()
        await expect(page.locator('[aria-current="page"]').filter({ hasText: 'People Directory' })).toBeVisible()
        await expect(page.getByText('Ready', { exact: true }).first()).toBeVisible()
        if (state === 'loading') await expect(main.getByRole('status', { name: 'Loading…' }).first()).toBeVisible()
        else await expect(main.getByText(copy[screen][state], { exact: true }).first()).toBeVisible()
        if (screen === 'webhooks' && state === 'normal') await expect(main.getByText('/webhooks/in/invoice_status', { exact: true })).toBeVisible()
        await page.evaluate(() => document.fonts.ready)
        expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0)
        const audit = await new AxeBuilder({ page }).analyze()
        expect(audit.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) }))).toEqual([])
        if (screen === 'forms') {
          if (state === 'normal') await expect(page).toHaveScreenshot('forms-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('forms-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('forms-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('forms-error.png', { fullPage: true })
        }
        if (screen === 'notifications') {
          if (state === 'normal') await expect(page).toHaveScreenshot('notifications-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('notifications-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('notifications-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('notifications-error.png', { fullPage: true })
        }
        if (screen === 'notiftypes') {
          if (state === 'normal') await expect(page).toHaveScreenshot('notiftypes-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('notiftypes-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('notiftypes-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('notiftypes-error.png', { fullPage: true })
        }
        if (screen === 'webhooks') {
          if (state === 'normal') await expect(page).toHaveScreenshot('webhooks-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('webhooks-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('webhooks-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('webhooks-error.png', { fullPage: true })
        }
        if (state === 'error') {
          fixture.recover()
          await main.getByRole('button', { name: 'Try again' }).first().click()
          await expect(main.getByText(copy[screen].normal, { exact: true })).toBeVisible()
        }
      } finally { fixture.release() }
    })
  }
}

test('forms resets local data on tab changes and supports keyboard list edits', async ({ page }) => {
  await mock(page, 'forms', 'normal')
  await page.goto(root + '/forms')
  await page.getByRole('button', { name: 'Show sample backend errors' }).click()
  await expect(page.getByText('String should have at most 80 characters')).toBeVisible()
  await page.getByRole('tab', { name: 'Lists' }).click()
  await expect(page.getByRole('button', { name: 'Clear backend errors' })).toBeDisabled()
  await page.getByRole('button', { name: 'Add list' }).press('Enter')
  const list = page.getByRole('group', { name: 'List 1' })
  await expect(list.getByRole('textbox', { name: 'Name', exact: true })).toBeFocused()
  await list.getByRole('button', { name: 'Add item' }).click()
  const value = list.getByRole('textbox', { name: 'Value', exact: true })
  await expect(value).toBeFocused()
  await value.fill('approved')
  await expect(page.getByTestId('form-value')).toContainText('approved')
})

test('notifications saves only the selected template and renders preference defaults', async ({ page }) => {
  const fixture = await mock(page, 'notifications', 'normal')
  await page.goto(root + '/notifications')
  const body = page.getByRole('textbox', { name: 'Message body' })
  await body.fill('Hello {{ customer }}')
  await expect(page.getByTestId('nt-preview-body')).toContainText('Hello Sample customer')
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(page.getByText('Saved the invoice_ready / email template.', { exact: true })).toBeVisible()
  expect(fixture.writes[0]).toMatchObject({ method: 'PUT', body: { expected_version: 3, notifications: {
    types: [{ templates: [{ body: 'Hello {{ customer }}' }, { channel: 'sms' }] }],
  } } })
  await page.getByRole('tab', { name: 'Preferences' }).click()
  await expect(page.getByRole('table', { name: 'Preferences matrix' })).toBeVisible()
})

test('notification types persists a settings change with the loaded version', async ({ page }) => {
  const fixture = await mock(page, 'notiftypes', 'normal')
  await page.goto(root + '/notiftypes')
  await page.getByRole('spinbutton', { name: 'Max attempts' }).fill('6')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Saved (version 4).', { exact: true })).toBeVisible()
  expect(fixture.writes[0]).toMatchObject({ method: 'PUT', body: { expected_version: 3, notifications: { max_attempts: 6 } } })
})

test('webhooks loads actual preview records and reveals a rotated secret once', async ({ page }) => {
  const fixture = await mock(page, 'webhooks', 'normal')
  await page.goto(root + '/see?preview=' + previewId)
  await page.getByRole('button', { name: 'Reconnect', exact: true }).click()
  const confirmation = page.getByRole('dialog')
  await confirmation.getByRole('button', { name: 'Confirm' }).click()
  await expect(page.getByRole('button', { name: 'Sign in to preview' })).toBeVisible()
  // Navigate within the project so the shell keeps its in-memory preview credential.
  await page.getByRole('button', { name: 'More', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Search or jump to…' }).click()
  await page.getByRole('option', { name: 'Webhooks' }).click()
  await page.getByRole('tab', { name: 'Subscriptions and deliveries' }).click()
  await page.getByLabel('Admin bearer token').fill('generated-admin')
  await page.getByRole('button', { name: 'Load subscriptions' }).click()
  await page.getByRole('button', { name: 'Delivery log' }).click()
  await page.getByRole('button', { name: 'Attempts' }).click()
  const attempts = page.getByRole('dialog', { name: 'Delivery attempts' })
  await expect(attempts.getByText('18 ms')).toBeVisible()
  await attempts.getByRole('button', { name: 'Close' }).click()
  await page.getByRole('button', { name: 'Details' }).click()
  await page.getByRole('button', { name: 'Rotate secret' }).click()
  const rotate = page.getByRole('dialog', { name: 'Rotate signing secret?' })
  await rotate.getByRole('spinbutton', { name: 'Overlap hours' }).fill('36')
  await rotate.getByRole('button', { name: 'Rotate secret' }).click()
  const secret = page.getByRole('dialog', { name: 'Signing secret' })
  await expect(secret.getByText('whsec_fixture_revealed_once')).toBeVisible()
  await secret.getByRole('button', { name: 'I stored it' }).click()
  await expect(page.getByText('whsec_fixture_revealed_once')).toHaveCount(0)
  expect(fixture.writes).toEqual([{
    path: previewPath + '/webhooks/subscriptions/' + subId + '/rotate', method: 'POST', body: { overlap_hours: 36 },
  }])
})
