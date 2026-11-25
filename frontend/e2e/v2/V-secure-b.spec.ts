import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const id = '8e87dc58-c920-4ca1-93af-aed0ed17397f'
const root = '/projects/' + id
const user = { id: 'owner', name: 'Mina Chen', email: 'mina@example.test', platform_role: 'customer', email_verified_at: '2026-01-01' }
const hash = 'sha256:' + 'a'.repeat(64)
const request = {
  id: 'request-1', package: 'httpx', version: '0.28.1', reason: 'Connect to the scheduling service.',
  status: 'pending', hashes: [hash], created_at: '2026-01-01T10:00:00Z', requested_by: 'owner',
  decided_by: null, decided_at: null, decision_note: null, expires_at: null, revoked_by: null, revoked_at: null,
}
const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]
type Section = 'access' | 'dependencies' | 'compliance'

async function mock(page: Page, section: Section, state: State, role = 'owner') {
  let release = () => {}
  const waiting = new Promise<void>(resolve => { release = resolve })
  let failed = state === 'error'
  const empty = state === 'empty'
  const target = section === 'access' ? '/authorization' : section === 'compliance' ? '/compliance/controls' : '/dependencies'
  const decisions: unknown[] = []
  let approved = false
  await page.route(url => url.port === '8000', async route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299',
      'access-control-allow-credentials': 'true', 'access-control-allow-methods': 'GET, POST, OPTIONS, PUT, PATCH, DELETE',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id',
    }
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (path === '/account/refresh') return json({ access_token: 'fixture' })
    if (path === '/account/me') return json(user)
    if (path === '/orgs') return json({ items: [], total: 0 })
    if (path === root) return json({ id, name: 'People Directory', slug: 'directory', version: 1 })
    if (path === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (path === root + '/members') return json([{ user_id: user.id, role }])
    if (path === root + target) {
      if (state === 'loading') await waiting
      if (failed) return json({ code: 'fixture_unavailable', message: 'Please retry.', details: [] }, 503)
    }
    if (path === root + '/authorization') return json({
      project_id: id, model: 'rbac', policies: [], attachments: {}, field_access: [],
      version: empty ? 0 : 1, updated_at: empty ? null : '2026-01-01T10:00:00Z',
    })
    if (path === root + '/authorization/issues') return json({ issues: [] })
    if (path === root + '/roles') return json({
      items: empty ? [] : [{ id: 'member', name: 'member', label: 'Member', position: 0, is_default: true }], total: empty ? 0 : 1,
    })
    if (path === root + '/spec') return json({
      auth: { enabled: true, provider: 'builtin', roles: [], multi_tenant: false },
      entities: empty ? [] : [{ name: 'Employee', fields: [{ name: 'team', type: 'string' }], options: { operations: ['list', 'get'] } }],
    })
    if (path === root + '/dependencies') return json({
      curated_sets: { 'web-core': { fastapi: '0.115.6' } }, allow_list: ['orjson'], pending_requests: empty || approved ? 0 : 1,
      approved: approved ? [{ ...request, expires_at: '2026-03-01T10:00:00Z' }] : [],
    })
    if (path === root + '/dependencies/requests') return json(empty ? [] : [{ ...request, status: approved ? 'approved' : 'pending' }])
    if (path === root + '/dependencies/requests/' + request.id + '/approve') {
      decisions.push(route.request().postDataJSON())
      approved = true
      return json({ ...request, status: 'approved' })
    }
    if (path === root + '/registry/blocks') return json([])
    if (path === root + '/registry/hooks') return json(empty ? [] :
      [{ id: 'h1', hook_name: 'before_save', content_hash: 'b'.repeat(64), author: 'Mina Chen', approved_by: null, created_at: request.created_at }])
    if (path === root + '/registry/deps') return json([])
    if (path === root + '/compliance/controls') return json({
      met: 0, unmet: empty ? 0 : 1, not_applicable: 0, controls: empty ? [] : [{
        id: 'SOC2-CC6.5', framework: 'soc2', title: 'Retention and disposal', description: 'Data is disposed of on schedule.',
        status: 'unmet', reason: 'No retention rule is configured.',
        evidence: [{ fact: 'compliance.retention', value: [] }],
        tests: [{ file: 'tests/test_compliance.py', name: 'test_retention_purges_expired_rows', where: 'generated' }],
      }],
    })
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, recover: () => { failed = false }, decisions }
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

const specs = {
  access: { title: 'Authorization', loading: 'Loading…', normal: 'Saved settings',
    empty: 'This project uses roles and permissions by default. Choose a model or add a role to start.',
    error: 'Could not load the authorization settings.' },
  dependencies: { title: 'Dependencies', loading: 'Loading…', normal: 'Policy',
    empty: 'No requests yet.', error: 'Could not reach the server. Check your connection and try again.' },
  compliance: { title: 'Compliance', loading: 'Loading controls…', normal: 'Retention and disposal',
    empty: 'No controls are mapped for this framework.', error: 'Could not load the controls. Check your connection and try again.' },
} as const

for (const section of ['access', 'dependencies', 'compliance'] as const) {
  const copy = specs[section]
  for (const state of states) {
    test(section + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, section, state)
      try {
        await page.goto(root + '/' + section, { waitUntil: 'domcontentloaded' })
        const main = page.getByRole('main')
        await expect(main.getByRole('heading', { name: copy.title, exact: true })).toBeVisible()
        await expect(page.locator('[aria-current="page"]').filter({ hasText: 'People Directory' })).toBeVisible()
        await expect(page.getByText('Ready', { exact: true })).toBeVisible()
        if (state === 'loading') await expect(main.getByRole('status', { name: copy.loading })).toBeVisible()
        else if (state === 'error') await expect(main.getByRole('alert')).toContainText(copy.error)
        else await expect(main.getByText(copy[state], { exact: true }).filter({ visible: true })).toBeVisible()
        if ((state === 'normal' || state === 'empty') && section === 'dependencies') {
          await expect(main.getByRole('button', { name: 'Send request' })).toBeVisible()
        }
        if ((state === 'normal' || state === 'empty') && section === 'access' && (page.viewportSize()?.width ?? 0) >= 700) {
          await expect(main.getByRole('button', { name: 'Attribute rules (ABAC)' })).toBeEnabled()
        }
        await page.evaluate(() => document.fonts.ready)
        expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0)
        const audit = await new AxeBuilder({ page }).analyze()
        expect(audit.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) }))).toEqual([])
        if (section === 'access') {
          if (state === 'normal') await expect(page).toHaveScreenshot('access-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('access-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('access-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('access-error.png', { fullPage: true })
        }
        if (section === 'dependencies') {
          if (state === 'normal') await expect(page).toHaveScreenshot('dependencies-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('dependencies-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('dependencies-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('dependencies-error.png', { fullPage: true })
        }
        if (section === 'compliance') {
          if (state === 'normal') await expect(page).toHaveScreenshot('compliance-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('compliance-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('compliance-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('compliance-error.png', { fullPage: true })
        }
        if (state === 'error') {
          fixture.recover()
          await main.getByRole('button', { name: 'Try again' }).click()
          await expect(main.getByText(copy.normal, { exact: true }).filter({ visible: true })).toBeVisible()
        }
      } finally {
        fixture.release()
      }
    })
  }
  test(section + ' viewer', async ({ page }) => {
    await mock(page, section, 'normal', 'viewer')
    await page.goto(root + '/' + section, { waitUntil: 'domcontentloaded' })
    const main = page.getByRole('main')
    await expect(main.getByText(copy.normal, { exact: true }).filter({ visible: true })).toBeVisible()
    await expect(main.getByText('You can look at this but not change it. Your role is viewer.')).toBeVisible()
    await expect(main.getByRole('button', { name: /^(Save|Approve|Send request)$/ })).toHaveCount(0)
  })
}

test('an owner approves the exact reviewed package pin', async ({ page }) => {
  const { decisions } = await mock(page, 'dependencies', 'normal')
  await page.goto(root + '/dependencies')
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Approve httpx 0.28.1?' })
  await expect(dialog.getByText(hash)).toBeVisible()
  expect(decisions).toEqual([])
  await dialog.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(page.getByText('Request list updated.')).toBeVisible()
  expect(decisions).toEqual([{ package: 'httpx', version: '0.28.1', hashes: [hash] }])
})
