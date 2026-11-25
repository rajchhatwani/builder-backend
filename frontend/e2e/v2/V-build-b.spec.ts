import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const id = '95ff34eb-4d07-4a60-8669-aaf1cf5442ca'
const root = '/projects/' + id
const behavior = root + '/behavior/'
const customPath = root + '/entities/Invoice/custom-fields'
const user = { id: 'fixture-owner', name: 'Mina Chen', email: 'mina@example.test', platform_role: 'customer', email_verified_at: '2026-01-01' }
const behaviors = {
  hooks: { title: 'Custom hooks', path: behavior + 'hooks', ready: 'check_invoice', empty: 'No hooks declared yet', error: 'We could not load hooks.', desktop: true },
  hookeffects: { title: 'Hook effects', path: behavior + 'hook-effects', ready: 'Effect settings', empty: 'Hook effects are not set up', error: 'We could not load hook effects.', desktop: true },
  events: { title: 'Events', path: behavior + 'events', ready: 'Events your project will publish', empty: 'Events are off', error: 'We could not load events.', desktop: false },
  settings: { title: 'Settings, sequences and lists', path: behavior + 'settings', ready: 'Approval threshold', empty: 'No settings yet', error: 'We could not load Settings.', desktop: false },
  seed: { title: 'Seed data', path: behavior + 'seed', ready: 'How to run it', empty: 'No seed profiles yet', error: 'We could not load seed profiles.', desktop: false },
  customfields: { title: 'Custom fields', path: customPath, ready: 'Reference code', empty: 'No custom fields yet', error: 'We could not load the supporting project information.', desktop: false },
} as const
type Screen = keyof typeof behaviors
const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]

const hook = {
  name: 'check_invoice', point: 'Invoice.validate', kind: 'pure',
  input: { name: 'CheckInvoiceInput', fields: [{ name: 'id', type: 'uuid', required: true }] },
  output: { name: 'CheckInvoiceResult', fields: [{ name: 'valid', type: 'bool', required: true }, { name: 'message', type: 'string', required: false }] },
  budget: { cpu_ms: 200, rows: 0, outbound_calls: 0 }, author: 'trusted',
}
const fields = [{ id: 'status', name: 'status', type: 'enum', enum_values: ['draft', 'approved'], required: true },
  { id: 'title', name: 'title', type: 'string', required: true, max_length: 80, unique: true }]
const machine = { entity: 'Invoice', field: 'status', initial: 'draft',
  transitions: [{ name: 'approve', from_states: ['draft'], to_state: 'approved', auto: false }] }
const settings = [{ key: 'approval_threshold', label: 'Approval threshold', type: 'int', default: 1500, minimum: 0, maximum: 9000 }]
const responsePage = (items: unknown[]) => ({ items, total: items.length, limit: 200, offset: 0 })
const envelope = { project_id: id, version: 3, row_version: 9, updated_at: '2026-01-01T00:00:00Z' }
const eventConfig = { enabled: true, adapter: 'in_process', retention_days: 14 }

async function mock(page: Page, surface: Screen, state: State, role = 'owner') {
  let release = () => {}
  const heldRequest = new Promise<void>(resolve => { release = resolve })
  let failed = state === 'error'
  let conflict = false
  let field = { name: 'reference_code', type: 'string', max_length: 60, enum_values: ['AA', 'BB'], required: false }
  let events = eventConfig
  const writes: Array<{ path: string; payload: unknown }> = []
  const empty = (name: Screen) => name === surface && state === 'empty'
  await page.route(url => url.port === '8000', async route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299',
      'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, PUT, PATCH, POST, DELETE, OPTIONS',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id',
    }
    const json = (value: unknown, status = 200) => route.fulfill({ status, headers, json: value })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (path === behaviors[surface].path && method === 'GET') {
      if (state === 'loading') await heldRequest
      if (failed) return json({ code: 'fixture_unavailable', message: 'Try again later.', details: [] }, 503)
    }
    if (path === '/account/refresh') return json({ access_token: 'fixture' })
    if (path === '/account/me') return json(user)
    if (path === '/orgs') return json(responsePage([]))
    if (path === root) return json({ id, name: 'Invoice project', version: 9 })
    if (path === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (path === root + '/members') return json([{ user_id: user.id, role }])
    if (path === root + '/spec') return json({
      entities: [{ name: 'Invoice', fields }], state_machines: [machine],
      providers: { enabled: true }, webhooks: { enabled: true }, notifications: { enabled: false },
    })
    if (path === root + '/entities') return json(responsePage([{ id: 'entity-1', name: 'Invoice', options: { operations: ['create', 'update'] } }]))
    if (path === '/entities/entity-1/fields') return json(responsePage(fields))
    if (path === root + '/relations') return json(responsePage([]))
    if (path === behavior + 'state-machines') return json({ ...envelope, state_machines: [machine] })
    if (path === behavior + 'issues') return json({ issues: [] })
    if (path === behavior + 'roles') return json({ roles: [{ name: 'accounts', label: 'Accounts' }] })
    if (path === behavior + 'hooks') return json({ ...envelope, hooks: empty('hooks') ? [] : [hook] })
    if (path === behavior + 'hook-effects') return json({ ...envelope,
      hook_effects: empty('hookeffects') ? null : { enabled: true, trusted_authors_only: true, webhook_hosts: ['notify.example.test'] } })
    if (path === behavior + 'events') {
      if (method === 'PUT') {
        const payload = route.request().postDataJSON()
        writes.push({ path, payload })
        if (conflict) return json({ code: 'conflict', message: 'The events changed.', details: [] }, 409)
        events = payload.events
        return json({ ...envelope, version: 4, events })
      }
      return json({ ...envelope, events: empty('events') ? null : events })
    }
    if (path === behavior + 'settings') return json({ ...envelope, settings: empty('settings') ? [] : settings })
    if (path === behavior + 'sequences') return json({ ...envelope, sequences: [{ name: 'invoice_number', prefix: 'INV-', padding: 5, start: 42 }] })
    if (path === behavior + 'lists') return json({ ...envelope, lists: [] })
    if (path === behavior + 'seed') return json({ ...envelope, seed: empty('seed') ? [] : [
      { name: 'demo', seed: 42, as_of: '2026-01-01', tenants: 0, entities: [{ entity: 'Invoice', count: 10, fields: [] }] },
    ] })
    if (path === customPath) return json({ entity: 'Invoice', enabled: true, max_keys: 50, max_bytes: 8192, items: empty('customfields') ? [] : [field] })
    if (path === customPath + '/reference_code' && method === 'PATCH') {
      const payload = route.request().postDataJSON()
      writes.push({ path, payload })
      field = payload
      return json(field)
    }
    if (path === customPath + '/reference_code/promote-check') {
      const payload = route.request().postDataJSON()
      writes.push({ path, payload })
      return json({ ok: true, proven: Boolean(payload.samples), plan_sql: ['ALTER TABLE invoices ADD COLUMN reference_code varchar(60)'],
        problems: [], warnings: payload.samples ? [] : ['The stored values were not checked.'] })
    }
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, recover: () => { failed = false }, conflict: () => { conflict = true }, writes }
}

test.beforeEach(async ({ page }) => {
  const fontFixture = (file: string) => fileURLToPath(new URL('./fixtures/ibm-plex/' + file, import.meta.url))
  // Use the same Latin faces as the screenshot baselines even when the font CDN is unavailable.
  await page.route(/^https:\/\/fonts\.googleapis\.com\/css2\?family=IBM\+Plex\+Sans/, route =>
    route.fulfill({ path: fontFixture('latin.css'), contentType: 'text/css' }))
  await page.route('https://fonts.gstatic.com/v2-test-typography/*.woff2', route => {
    const file = new URL(route.request().url()).pathname.split('/').at(-1)!
    return route.fulfill({ path: fontFixture(file), contentType: 'font/woff2', headers: { 'access-control-allow-origin': '*' } })
  })
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
})

async function opened(page: Page, screen: Screen) {
  const main = page.getByRole('main')
  await expect(main.getByRole('heading', { name: behaviors[screen].title, exact: true })).toBeVisible()
  await expect(page.locator('[aria-current="page"]').filter({ hasText: 'Invoice project' })).toBeVisible()
  await expect(page.getByText('Ready', { exact: true })).toBeVisible()
  return main
}

for (const [screen, info] of Object.entries(behaviors) as Array<[Screen, typeof behaviors[Screen]]>) {
  for (const state of states) {
    test(screen + ' ' + state, async ({ page }) => {
      const { release, recover } = await mock(page, screen, state)
      try {
        await page.goto(root + '/' + screen, { waitUntil: 'domcontentloaded' })
        const main = await opened(page, screen)
        const phone = info.desktop && (page.viewportSize()?.width ?? 0) < 700
        if (phone) await expect(main.getByText('Open this on a desktop to edit')).toBeVisible()
        else if (state === 'loading') await expect(main.getByRole('status', { name: 'Loading…' }).first()).toBeVisible()
        else if (state === 'error') await expect(main.getByText(info.error, { exact: true })).toBeVisible()
        else if (state === 'empty') await expect(main.getByRole('heading', { name: info.empty })).toBeVisible()
        else if (screen === 'customfields') await expect(main.getByText('reference_code', { exact: true })).toBeVisible()
        else await expect(main.getByText(info.ready, { exact: true }).first()).toBeVisible()

        await page.evaluate(() => document.fonts.ready.then(() => undefined))
        const size = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
        expect(size[0]).toBe(size[1])
        const audit = await new AxeBuilder({ page }).analyze()
        expect(audit.violations.map(violation => ({ id: violation.id, targets: violation.nodes.map(node => node.target) }))).toEqual([])
        if (state === 'normal') await expect(page).toHaveScreenshot(screen + '-normal.png', { fullPage: true })
        if (state === 'loading') await expect(page).toHaveScreenshot(screen + '-loading.png', { fullPage: true })
        if (state === 'empty') await expect(page).toHaveScreenshot(screen + '-empty.png', { fullPage: true })
        if (state === 'error') await expect(page).toHaveScreenshot(screen + '-error.png', { fullPage: true })
        if (state === 'error' && !phone) {
          recover()
          await main.getByRole('button', { name: 'Try again' }).click()
          await expect(main.getByText(info.error, { exact: true })).toBeHidden()
        }
      } finally {
        release()
      }
    })
  }
}

test('events preserves the version through a conflict', async ({ page }) => {
  const fixture = await mock(page, 'events', 'normal')
  await page.goto(root + '/events')
  const main = await opened(page, 'events')
  const retention = main.getByLabel('Retention days')
  await retention.fill('30')
  fixture.conflict()
  await main.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(main.getByText(/Someone else changed this section/)).toBeVisible()
  expect(fixture.writes[0]).toEqual({ path: behavior + 'events', payload: {
    expected_version: 3, events: { ...eventConfig, retention_days: 30 },
  } })
  await expect(retention).toHaveValue('30')
  await main.getByRole('button', { name: 'Reload', exact: true }).click()
  await expect(retention).toHaveValue('14')
})

test('customfields checks typed samples and confirms a cast result', async ({ page }) => {
  const fixture = await mock(page, 'customfields', 'normal')
  await page.goto(root + '/customfields')
  const main = await opened(page, 'customfields')
  await main.getByRole('button', { name: 'Check reference_code for promotion' }).click()
  await expect(main.getByText('Not proven', { exact: true })).toBeVisible()
  await expect(main.getByRole('button', { name: 'Promote to a column' })).toBeDisabled()
  await main.getByLabel('Sample values').fill('["AA", "BB"]')
  await main.getByRole('button', { name: 'Run promotion check' }).click()
  await expect(main.getByText('Ready', { exact: true })).toBeVisible()
  expect(fixture.writes.at(-1)?.payload).toEqual({ samples: ['AA', 'BB'] })
  await main.getByRole('button', { name: 'Promote to a column' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
})

test('settings viewer can browse tabs and cannot edit', async ({ page }) => {
  await mock(page, 'settings', 'normal', 'viewer')
  await page.goto(root + '/settings')
  const main = await opened(page, 'settings')
  await expect(main.getByText(/Your role is viewer/)).toBeVisible()
  await expect(main.getByLabel('Default value')).toBeDisabled()
  await main.getByRole('tab', { name: 'Sequences' }).click()
  const preview = main.getByRole('tabpanel', { name: 'Sequences' }).getByTestId('seq-preview')
  await expect(preview).toBeVisible()
  await expect(preview).toHaveText('INV-00042')
  expect(new URL(page.url()).searchParams.get('tab')).toBe('sequences')
  await expect(main.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
})
