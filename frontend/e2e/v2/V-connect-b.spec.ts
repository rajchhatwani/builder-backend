import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { members, projectId, root, time, user } from './fixtures/connect-a'
import { apiKey, app, audit, batch, batchId, blockReply, catalogue, connectSpec, platformPath, preview, previewId, previewPath, row, settings } from './fixtures/connect-b'
import type { Setting } from './fixtures/connect-b'

test.use({ locale: 'en-US', timezoneId: 'UTC' })
const screens = ['providers', 'apiedge', 'import', 'apikeys', 'apps'] as const
const states = ['normal', 'loading', 'empty', 'error'] as const
type Screen = typeof screens[number]
type State = typeof states[number]
const blocks: Partial<Record<Screen, Setting>> = { providers: 'providers', apiedge: 'api-edge', apikeys: 'api-platform' }
const bucket = root + '/imports'
const cursor = bucket + '/' + batchId

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
  const name = blocks[screen]
  let block = name && state !== 'empty' ? settings[name] : null
  let version = block ? 3 : 0
  let installed = false
  let apiKeys = [apiKey]
  const auditRows: (typeof audit)[] = []
  let current = structuredClone(batch)
  const writes: { path: string; body: unknown }[] = []
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299', 'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, POST, OPTIONS, PUT, PATCH, DELETE',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id, x-preview-token',
    }
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    const unavailable = () => json({ code: 'unavailable', message: 'Retry.', details: [] }, 503)
    const record = () => writes.push({ path, body: request.headers()['content-type']?.includes('application/json') ? request.postDataJSON() : null })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (path === '/account/refresh') return json({ access_token: 'fixture' })
    if (path === '/account/me') return json(user)
    if (path === '/orgs') return json({ items: [], total: 0 })
    if (path === root) return json({ id: projectId, name: 'People Directory', slug: 'directory', version: 1 })
    if (path === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (path === root + '/members') return json(members.map(member => member.user_id === user.id ? { ...member, role } : member))
    if (path === root + '/workspaces') return json([])
    if (path === root + '/spec') {
      if (screen === 'import' && state === 'loading') await waiting
      if (screen === 'import' && fail) return unavailable()
      return json(screen === 'import' && state === 'empty' ? { ...connectSpec, entities: [] } : connectSpec)
    }
    if (path === root + '/behavior/roles') return json({ roles: connectSpec.auth.roles })
    if (path === root + '/behavior/issues') return json({ issues: [] })
    if (path === root + '/behavior/api-platform' && screen === 'apps') return json(blockReply('api-platform', settings['api-platform']))
    if (name && path === root + '/behavior/' + name) {
      if (method === 'PUT') {
        record()
        block = request.postDataJSON()[name.replaceAll('-', '_')]
        return json(blockReply(name, block, ++version))
      }
      if (state === 'loading') await waiting
      if (fail) return unavailable()
      return json(blockReply(name, block, version))
    }
    if (path === root + '/previews') return json([preview])
    if (path === root + previewPath) return json(preview)
    if (path === root + previewPath + '/rotate-token') return json({ ...preview, token: 'preview-token' })
    if (path === previewPath + '/openapi.json') return json({ paths: {} })
    if (path === previewPath + '/auth/login') return json({ access_token: 'generated-admin' })
    if (path.startsWith(platformPath)) {
      expect(request.headers()['x-preview-token']).toBe('preview-token')
      expect(request.headers().authorization).toBe('Bearer generated-admin')
      if (path === platformPath + '/catalogue') return json(catalogue)
      if (path === platformPath + '/keys') {
        if (method === 'GET') return json(apiKeys)
        record()
        const { name, environment, scopes } = request.postDataJSON()
        const created = { ...apiKey, id: '1e712e6f-0a11-49f3-a7f7-79a98835e701', name, environment, scopes }
        apiKeys = [created, ...apiKeys]
        auditRows.unshift({ ...audit, target: created.id, detail: { environment } })
        return json({ ...created, key: 'one-time-api-key' }, 201)
      }
      if (path === platformPath + '/keys/' + apiKey.id + '/revoke') {
        record()
        const revoked = { ...apiKey, status: 'revoked', revoked_at: time }
        apiKeys = apiKeys.map(key => key.id === revoked.id ? revoked : key)
        auditRows.unshift({ ...audit, id: 'audit-2', action: 'key.revoke' })
        return json(revoked)
      }
      if (path === platformPath + '/audit') return json(auditRows)
      if (path === platformPath + '/apps') {
        if (state === 'loading') await waiting
        if (fail) return unavailable()
        if (state === 'empty') return json([])
        return json([installed ? { ...app, installed: true, installed_at: time, installation_id: apiKey.id, granted_scopes: ['Invoice'] } : app])
      }
      if (path === platformPath + '/apps/reporter/install') {
        record()
        installed = true
        return json({ installation_id: apiKey.id, app: app.name, granted_scopes: ['Invoice'], token: 'one-time-app-token', signing_secret: 'one-time-signing-secret' }, 201)
      }
      if (path === platformPath + '/apps/reporter/uninstall') {
        record()
        installed = false
        return json({ installation_id: apiKey.id, status: 'uninstalled' })
      }
    }
    if (path === bucket && method === 'POST') return json(current, 201)
    if (path === bucket) return json({ items: [{ ...current, id: batchId, filename: 'invoices.csv', created_at: time }], total: 1, offset: 0, limit: 20 })
    if (path === cursor) return json(current)
    if (path === cursor + '/rows') return json({ items: current.rejected, total: current.rejected.length, offset: 0, limit: 100 })
    if (path === cursor + '/rows/' + row.id) {
      record()
      const result = { ...row, status: 'fixed', errors: [], record: request.postDataJSON().values }
      current = { ...current, rejected: [], sample: [result], counts: { ...current.counts, rejected: 0, fixed: 1 } }
      return json(result)
    }
    if (path === cursor + '/commit') {
      record()
      current = { ...current, status: 'committed' }
      return json({ batch_id: batchId, status: 'committed', created: 1, duplicate: 0, rejected: 0 })
    }
    if (path === bucket + '/records') return json({ items: [{ id: 'first', entity: 'Invoice', data: { reference: 'A1' }, batch_id: batchId, created_at: time }], total: 1, offset: 0, limit: 20 })
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, recover: () => { fail = false }, writes }
}

const copy = {
  providers: { title: 'Provider integrations', normal: 'Credential vault', empty: 'No provider settings yet', error: 'We could not load provider integrations.' },
  apiedge: { title: 'API edge', normal: 'Generated API behavior', empty: 'No API edge settings yet', error: 'We could not load API edge settings.' },
  import: { title: 'Import data', normal: 'Upload and preview', empty: 'No entities yet', error: 'We could not load the project for import.' },
  apikeys: { title: 'API keys', normal: 'Public access', empty: 'No API platform settings yet', error: 'Could not load the API platform settings.' },
  apps: { title: 'Apps', normal: 'Reporter', empty: 'No apps are defined', error: 'Could not load apps from the preview.' },
}

async function connectPreview(page: Page) {
  await page.goto(root + '/see?preview=' + previewId)
  await page.getByRole('button', { name: 'Reconnect', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm' }).click()
  await expect(page.getByRole('button', { name: 'Sign in to preview', exact: true })).toBeVisible()
}
async function jump(page: Page, name: string) {
  await page.getByRole('button', { name: 'More', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Search or jump to…' }).click()
  await page.getByRole('option', { name: `${name} Connect`, exact: true }).click()
}
async function signIn(page: Page) {
  await page.getByRole('button', { name: 'Sign in to preview', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Preview account email').fill('admin@example.test')
  await dialog.getByLabel('Preview password').fill('FixturePassword1')
  await dialog.getByRole('button', { name: 'Sign in to preview', exact: true }).click()
  await expect(dialog).toHaveCount(0)
}
async function checkLayout(page: Page) {
  await page.evaluate(() => document.fonts.ready)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0)
  const audit = await new AxeBuilder({ page }).analyze()
  expect(audit.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) }))).toEqual([])
}

for (const screen of screens) {
  for (const state of states) {
    test(screen + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, screen, state)
      const main = page.getByRole('main')
      try {
        if (screen === 'apps') {
          await connectPreview(page)
          await jump(page, 'Apps')
          await signIn(page)
        } else await page.goto(root + '/' + screen, { waitUntil: 'domcontentloaded' })
        if (state === 'loading') await expect(main.getByRole('status', { name: 'Loading…' }).first()).toBeVisible()
        else await expect(main.getByText(copy[screen][state], { exact: true }).first()).toBeVisible()
        await expect(main.getByRole('heading', { name: copy[screen].title, exact: true })).toBeVisible()
        await expect(page.getByText('Ready', { exact: true }).first()).toBeVisible()
        await checkLayout(page)
        if (screen === 'providers') {
          if (state === 'normal') await expect(page).toHaveScreenshot('providers-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('providers-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('providers-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('providers-error.png', { fullPage: true })
        }
        if (screen === 'apiedge') {
          if (state === 'normal') await expect(page).toHaveScreenshot('apiedge-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('apiedge-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('apiedge-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('apiedge-error.png', { fullPage: true })
        }
        if (screen === 'import') {
          if (state === 'normal') await expect(page).toHaveScreenshot('import-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('import-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('import-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('import-error.png', { fullPage: true })
        }
        if (screen === 'apikeys') {
          if (state === 'normal') await expect(page).toHaveScreenshot('apikeys-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('apikeys-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('apikeys-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('apikeys-error.png', { fullPage: true })
        }
        if (screen === 'apps') {
          if (state === 'normal') await expect(page).toHaveScreenshot('apps-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('apps-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('apps-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('apps-error.png', { fullPage: true })
        }
        if (state === 'error') {
          fixture.recover()
          await main.getByRole('button', { name: 'Try again' }).first().click()
          await expect(main.getByText(copy[screen].normal, { exact: true }).first()).toBeVisible()
        }
      } finally { fixture.release() }
    })
  }
}

test('import resumes a batch and commits corrected data', async ({ page }, testInfo) => {
  const fixture = await mock(page, 'import', 'normal')
  await page.goto(root + '/import?tab=history')
  await page.getByRole('button', { name: 'Resume import' }).click()
  if (testInfo.project.name.startsWith('w360')) {
    await expect(page.getByText('Open this on a desktop to edit')).toBeVisible()
    return
  }
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByLabel('Fix reference (row 1)').fill('A1')
  await page.getByRole('button', { name: 'Save row 1' }).click()
  await page.getByRole('button', { name: 'Commit 1 row' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Commit 1 row' }).click()
  await expect(page.getByText('1 created, 0 already imported, 0 rejected.')).toBeVisible()
  expect(fixture.writes).toEqual([{ path: cursor + '/rows/' + row.id, body: { values: { reference: 'A1' } } }, { path: cursor + '/commit', body: null }])
})

test('keys reveal a secret once and revoke only after confirmation', async ({ page }) => {
  const fixture = await mock(page, 'apikeys', 'normal')
  await connectPreview(page)
  await jump(page, 'API keys')
  await page.getByRole('tab', { name: 'Keys', exact: true }).click()
  await signIn(page)
  await page.getByLabel('Key name').fill('Monthly key')
  await page.getByTestId('key-scope').first().check()
  await page.getByRole('button', { name: 'Create key' }).click()
  await expect(page.getByTestId('secret-value')).toHaveText('one-time-api-key')
  await page.getByTestId('secret-dismiss').click()
  await expect(page.getByTestId('secret-value')).toHaveCount(0)
  await page.getByRole('button', { name: 'Revoke Reporting key' }).click()
  expect(fixture.writes).toHaveLength(1)
  await page.getByRole('dialog').getByRole('button', { name: 'Yes, revoke' }).click()
  await expect(page.getByText('Key revoked.')).toBeVisible()
  await page.getByRole('tab', { name: 'Audit', exact: true }).click()
  const auditTable = page.getByRole('table', { name: 'Audit', exact: true })
  await expect(auditTable.getByRole('cell', { name: 'key.create', exact: true })).toBeVisible()
  await expect(auditTable.getByRole('cell', { name: 'key.revoke', exact: true })).toBeVisible()
  expect(fixture.writes).toEqual([
    { path: platformPath + '/keys', body: { name: 'Monthly key', scopes: ['Invoice'], environment: 'prod', ttl_days: null } },
    { path: platformPath + '/keys/' + apiKey.id + '/revoke', body: null },
  ])
})

test('apps install a subset, clear secrets and uninstall after confirmation', async ({ page }) => {
  const fixture = await mock(page, 'apps', 'normal')
  await connectPreview(page)
  await jump(page, 'Apps')
  await signIn(page)
  await page.getByTestId('app-scope').last().uncheck()
  await page.getByRole('button', { name: 'Install Reporter' }).click()
  await expect(page.getByTestId('secret-value')).toHaveText(['one-time-app-token', 'one-time-signing-secret'])
  await page.getByTestId('secret-dismiss').click()
  await expect(page.getByTestId('secret-value')).toHaveCount(0)
  await page.getByRole('button', { name: 'Uninstall Reporter' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Close' }).click()
  expect(fixture.writes).toHaveLength(1)
  await page.getByRole('button', { name: 'Uninstall Reporter' }).click()
  await page.getByRole('button', { name: 'Yes, uninstall' }).click()
  await expect(page.getByText('Reporter uninstalled.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Install Reporter' })).toBeVisible()
  expect(fixture.writes.map(write => write.body)).toEqual([{ scopes: ['Invoice'] }, null])
})
