import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const id = '8e87dc58-c920-4ca1-93af-aed0ed17397f'
const root = '/projects/' + id
const user = { id: 'owner', name: 'Mina Chen', email: 'mina@example.test', platform_role: 'customer', email_verified_at: '2026-01-01' }
const suite = { suite_id: 'acme', hub_issuer: 'https://signin.example.test/realms/suite-acme', join_state: 'planned', migration: null }
const auth = {
  id: 'auth', project_id: id, enabled: true, provider: 'builtin', deletion_mode: 'soft', token_store: 'db', jwt_algorithm: 'HS256',
  access_token_ttl_minutes: 15, refresh_token_ttl_days: 7, email_magic_link_enabled: false, email_verification_required: false,
  sms_otp_enabled: false, sms_provider: null, sms_config: null, smtp_config: null, otp_ttl_minutes: 10, invite_only: false,
  multi_tenant: false, login_rate_limit: '5/15minutes', register_rate_limit: '10/hour', reset_rate_limit: '3/hour',
  security_headers_enabled: true, app_name: 'People Directory', app_url: null, email_templates: null, suite: null,
}
const keycloak = {
  id: 'keycloak', project_id: id, active: false, mode: 'own', realm: 'directory', api_client_id: 'directory-api',
  web_client_id: 'directory-web', redirect_uris: ['https://directory.example.test/auth/callback'], password_min_length: 12,
  mfa: 'optional', session_idle_minutes: 30, session_max_hours: 10, audit_retention_days: 90,
  identity_providers: [], source_project_id: null,
}
const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]
type Section = 'auth' | 'keycloak' | 'suite'

async function mock(page: Page, section: Section, state: State, role = 'owner') {
  let release = () => {}
  const waiting = new Promise<void>(resolve => { release = resolve })
  let failed = state === 'error'
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
    if (path === root + '/validate') return json({ valid: true, issues: [] })
    if (path === root + '/auth/custom-fields') return json({ items: [], total: 0, limit: 10, offset: 0 })
    if (path === root + (section === 'keycloak' ? '/keycloak' : '/auth')) {
      if (state === 'loading') await waiting
      if (failed) return json({ code: 'fixture_unavailable', message: 'Please retry.', details: [] }, 503)
      if (state === 'empty' && section !== 'suite') return json({ code: 'not_found', details: [] }, 404)
    }
    if (path === root + '/auth') return json(section === 'suite' ? {
      ...auth, provider: 'keycloak', suite: state === 'empty' ? null : suite,
    } : auth)
    if (path === root + '/keycloak') return json(section === 'suite'
      ? { ...keycloak, active: true, mode: 'shared', realm: 'suite-acme' } : keycloak)
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, recover: () => { failed = false } }
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
  auth: { title: 'Authentication', loading: 'Loading auth configuration…', normal: 'General', empty: 'Auth not configured', error: 'Failed to load auth configuration.' },
  keycloak: { title: 'Keycloak', loading: 'Loading the Keycloak settings…', normal: 'Where Keycloak runs', empty: 'Keycloak has not been configured', error: 'Could not load the Keycloak settings.' },
  suite: { title: 'Suite identity', loading: 'Loading suite identity…', normal: 'Membership', empty: 'This project has no suite', error: 'Could not load the sign-in settings.' },
} as const

for (const section of ['auth', 'keycloak', 'suite'] as const) {
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
        else await expect(main.getByRole('heading', { name: copy[state], exact: true })).toBeVisible()

        await page.evaluate(() => document.fonts.ready)
        expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0)
        const audit = await new AxeBuilder({ page }).analyze()
        expect(audit.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) }))).toEqual([])
        if (section === 'auth') {
          if (state === 'normal') await expect(page).toHaveScreenshot('auth-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('auth-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('auth-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('auth-error.png', { fullPage: true })
        }
        if (section === 'keycloak') {
          if (state === 'normal') await expect(page).toHaveScreenshot('keycloak-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('keycloak-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('keycloak-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('keycloak-error.png', { fullPage: true })
        }
        if (section === 'suite') {
          if (state === 'normal') await expect(page).toHaveScreenshot('suite-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('suite-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('suite-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('suite-error.png', { fullPage: true })
        }
        if (state === 'error') {
          fixture.recover()
          await main.getByRole('button', { name: 'Try again' }).click()
          await expect(main.getByRole('heading', { name: copy.normal, exact: true })).toBeVisible()
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
    await expect(main.getByRole('heading', { name: copy.normal, exact: true })).toBeVisible()
    await expect(main.getByText('You can look at this but not change it. Your role is viewer.')).toBeVisible()
    await expect(main.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  })
}
