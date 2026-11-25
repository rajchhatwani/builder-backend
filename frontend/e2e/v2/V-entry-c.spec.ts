import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const path = '/org/city-library'
const apiPath = '/orgs/city-library'
const date = '2026-11-22T12:00:00Z'
const user = { id: 'reader', email: 'reader@example.test', name: 'Library Reader', email_verified_at: date, default_organization_id: 'library' }
const org = { id: 'library', name: 'City Library', slug: 'city-library', kind: 'team', my_role: 'owner', member_count: 2 }
const members = [
  { user_id: user.id, name: user.name, email: user.email, role: 'owner', status: 'active', joined_at: date, last_login_at: date, mfa_enabled: true },
  { user_id: 'editor', name: 'Avery Sutton', email: 'avery@example.test', role: 'member', status: 'active', joined_at: date, mfa_enabled: false },
]
const plan = {
  plan: { id: 'team', display_name: 'Team', monthly_price_usd: 4900, allow_sso: true, allow_scim: true, allow_mcp: true },
  usage: { seats_used: 2, seats_cap: 8, projects_used: 1, projects_cap: 5, api_tokens_used: 1, api_tokens_cap: 3, mcp_tokens_used: 0, mcp_tokens_cap: 2 },
  subscription: { status: 'active' }, upgrades: [], checkout_available: false, portal_available: false,
}
const cases = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof cases[number]
const captures: Record<State, (page: Page) => Promise<void>> = {
  normal: page => expect(page).toHaveScreenshot('orgconsole-normal.png', { fullPage: true }),
  loading: page => expect(page).toHaveScreenshot('orgconsole-loading.png', { fullPage: true }),
  empty: page => expect(page).toHaveScreenshot('orgconsole-empty.png', { fullPage: true }),
  error: page => expect(page).toHaveScreenshot('orgconsole-error.png', { fullPage: true }),
}

async function mock(page: Page, state: State = 'normal', role = 'owner') {
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
  await page.clock.setFixedTime(new Date('2026-11-25T12:00:00Z'))
  let release = () => {}
  const held = new Promise<void>(resolve => { release = resolve })
  let fail = state === 'error'
  let locked = false
  let hasDirectory = false
  let invitations: unknown[] = []
  const calls: string[] = []
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299',
      'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, POST, PATCH, PUT, DELETE, OPTIONS',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with',
    }
    const send = (json: unknown, status = 200) => route.fulfill({ json, status, headers })
    const empty = () => route.fulfill({ status: 204, headers })
    const list = (items: unknown[]) => send({ items, total: items.length, offset: 0, limit: 50 })
    if (method === 'OPTIONS') return empty()
    calls.push(method + ' ' + path)
    if (path === '/account/refresh') return send({ access_token: 'fixture-session' })
    if (path === '/account/me') return send(user)
    if (path === '/orgs') return list([org])
    if (path === '/orgs/invitations/pending' || path === '/projects') return list([])
    if (path === apiPath) {
      if (method === 'DELETE') locked = true
      return send({ ...org, my_role: role, deletion_scheduled_for: locked ? date : null }, locked && method === 'DELETE' ? 202 : 200)
    }
    if (path === apiPath + '/deletion/cancel') {
      locked = false
      return send(org)
    }
    const resource = path.slice(apiPath.length)
    if (resource === '/members') {
      if (state === 'loading') await held
      if (fail) return send({ code: 'fixture', message: 'Unavailable', details: [] }, 503)
      return list(state === 'empty' ? [] : members)
    }
    if (resource === '/plan') return send(plan)
    if (resource === '/projects' || resource === '/audit') return list([])
    if (resource === '/invitations' && method === 'POST') {
      const row = { id: 'new-invite', ...request.postDataJSON(), status: 'pending', created_at: date, expires_at: '2026-11-30T12:00:00Z' }
      invitations = [row]
      return send({ ...row, invite_url: 'https://builder.example.test/#/invite/fixed-fixture-token', emailed: false }, 201)
    }
    if (resource === '/invitations') return list(invitations)
    if (resource === '/invitations/new-invite' && method === 'DELETE') {
      invitations = []
      return empty()
    }
    if (resource === '/sso') return send({
      configured: false, allowed_by_plan: true, domains: [],
      sp: { entity_id: 'urn:city-library', acs_url: 'https://builder.example.test/acs', metadata_url: 'https://builder.example.test/metadata',
        oidc_redirect_uri: 'https://builder.example.test/oidc', login_url: 'https://builder.example.test/login' },
    })
    const directory = () => ({
      configured: hasDirectory, allowed_by_plan: true, active: hasDirectory,
      base_url: 'https://builder.example.test/scim/v2', users_url: 'https://builder.example.test/scim/v2/Users',
      group_roles: {}, active_users: 0, deactivated_users: 0, groups: [],
    })
    if (resource === '/scim') return send(directory())
    if (resource === '/scim/token') {
      hasDirectory = true
      return send({ ...directory(), token: 'scim-fixed-fixture-token' }, 201)
    }
    if (resource === '/policies') return send({ require_mfa: false, session_ttl_hours: null, allow_impersonation: true, default_session_hours: 168, members_without_mfa: 1 })
    if (resource === '/ai/settings') return send({ has_api_key: false, monthly_budget_micro_usd: null })
    if (resource === '/ai/cost') return list([])
    if (resource === '/usage') return send({ metrics: [{ metric: 'ai_calls', unit: 'calls', period: 'month', used: 3, limit: 10, refused: 0 }] })
    if (resource === '/registry/projects') return send([])
    return send({ code: 'fixture_missing', message: 'Unexpected fixture request', details: [] }, 404)
  })
  return { release, calls, recover: () => { fail = false } }
}

for (const state of cases) {
  test(`orgconsole ${state}`, async ({ page }) => {
    const fixture = await mock(page, state)
    try {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1, name: 'City Library' })).toBeVisible()
      if (state === 'loading') await expect(page.getByRole('status', { name: 'Loading organization…' })).toBeVisible()
      else if (state === 'error') await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
      else {
        await expect(page.getByText('Team plan · Active')).toBeVisible()
        if (state === 'empty') await expect(page.getByRole('heading', { name: 'No members to show.' })).toBeVisible()
        else await expect(page.getByRole('combobox', { name: 'Role of avery@example.test' })).toBeVisible()
      }
      await page.evaluate(() => document.fonts.ready.then(() => undefined))
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
      const accessibility = await new AxeBuilder({ page }).analyze()
      expect(accessibility.violations).toEqual([])
      await captures[state](page)
      if (state === 'error') {
        fixture.recover()
        await page.getByRole('button', { name: 'Retry' }).click()
        await expect(page.getByText('Avery Sutton')).toBeVisible()
      }
    } finally {
      fixture.release()
    }
  })
}

test('keeps one-time links and SCIM tokens out of the interface after dismissal', async ({ page }) => {
  await mock(page)
  await page.goto(path + '?tab=invites')
  await page.getByLabel('Email').fill('new-reader@example.test')
  await page.getByRole('button', { name: 'Invite', exact: true }).click()
  await expect(page.getByText(/fixed-fixture-token/)).toBeVisible()
  await page.getByRole('button', { name: 'I have sent it' }).click()
  await expect(page.getByText(/fixed-fixture-token/)).toHaveCount(0)
  await page.getByRole('button', { name: 'Revoke', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Revoke', exact: true }).click()
  await expect(page.getByText('No pending invitations.')).toBeVisible()
  await page.getByRole('tab', { name: 'SSO & SCIM' }).click()
  await expect(page).toHaveURL(/tab=sso/)
  await page.getByRole('button', { name: 'Generate token' }).click()
  await expect(page.getByText('scim-fixed-fixture-token')).toBeVisible()
  await page.getByRole('button', { name: 'I saved the token in my identity provider' }).click()
  await expect(page.getByText('scim-fixed-fixture-token')).toHaveCount(0)
})

test('locks the tabs after confirmed deletion and restores access after cancellation', async ({ page }) => {
  await mock(page)
  await page.goto(path)
  await page.getByRole('button', { name: 'Delete organization' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Request deletion' }).click()
  await expect(page.getByRole('tablist')).toHaveCount(0)
  await page.getByRole('button', { name: 'Cancel deletion' }).click()
  await expect(page.getByRole('tab', { name: 'People' })).toBeVisible()
})

test('members can view usage without reaching admin APIs', async ({ page }) => {
  const { calls } = await mock(page, 'normal', 'member')
  await page.goto(path + '?tab=ai')
  await expect(page.getByTestId('ai-noaccess')).toBeVisible()
  await page.getByRole('tab', { name: 'Usage' }).click()
  await expect(page.getByTestId('usage-used')).toHaveText('3')
  await expect(page.getByTestId('usage-edit')).toHaveCount(0)
  expect(calls.some(call => call.includes('/ai/'))).toBe(false)
})
