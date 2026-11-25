import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const projectId = '8dde65d0-2cf7-4cf4-83e5-e6ec4a5b52ef'
const orgId = '85df77ba-33ee-4450-aa3f-a0380e3e6ba6'
const date = '2026-11-23T12:00:00Z'
const user = {
  id: 'user', email: 'reader@example.test', name: 'Library Reader', platform_role: 'customer',
  status: 'active', must_change_password: false, email_verified_at: date,
  default_organization_id: orgId, created_at: date, last_login_at: date,
}
const org = { id: orgId, name: 'City Library', slug: 'city-library', kind: 'team', my_role: 'owner', require_mfa: false }
const project = {
  id: projectId, name: 'Reading room', slug: 'reading-room', description: 'Track room bookings and opening hours.',
  organization_id: orgId, version: 1, db_engine: 'postgres', created_at: date, updated_at: date,
}
const token = {
  id: 'token-id', name: 'CI pipeline', public_id: 'fixture-public-id', description: 'Release reports',
  scopes: ['read', 'generate'], project_id: projectId, created_at: date, last_used_at: date,
  expires_at: '2027-02-21T12:00:00Z', last_mcp_use_at: null, revoked_at: null,
}
const states = ['normal', 'loading', 'empty', 'error'] as const
const paths = { projects: '/projects', new: '/projects/new', account: '/account' }
type Screen = keyof typeof paths
type State = typeof states[number]

const screenshots: Record<State, (page: Page, screen: Screen) => Promise<void>> = {
  normal: (page, screen) => expect(page).toHaveScreenshot(`${screen}-normal.png`, { fullPage: true }),
  loading: (page, screen) => expect(page).toHaveScreenshot(`${screen}-loading.png`, { fullPage: true }),
  empty: (page, screen) => expect(page).toHaveScreenshot(`${screen}-empty.png`, { fullPage: true }),
  error: (page, screen) => expect(page).toHaveScreenshot(`${screen}-error.png`, { fullPage: true }),
}

async function mock(page: Page, screen: Screen, state: State) {
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
  await page.clock.setFixedTime(new Date('2026-11-25T12:00:00Z'))
  let release = () => {}
  const delay = new Promise<void>(resolve => { release = resolve })
  const endpoint: Record<Screen, string> = { projects: '/projects', new: '/orgs', account: '/account/tokens' }
  let tokens = screen === 'account' && state === 'empty' ? [] : [token]
  let projects = screen === 'projects' && state === 'empty' ? [] : [project]
  let enabled = false
  let unavailable = state === 'error'
  const bodies: Record<string, unknown[]> = {}
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299',
      'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with',
    }
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    const send = (json: unknown, status = 200) => route.fulfill({ json, status, headers })
    const ok = () => route.fulfill({ status: 204, headers })
    const items = (values: unknown[]) => send({ items: values, total: values.length, offset: 0, limit: 200 })
    if (request.postData()) (bodies[path] ??= []).push(request.postDataJSON())
    if (path === endpoint[screen] && method === 'GET') {
      if (state === 'loading') await delay
      if (unavailable) return send({ code: 'fixture_unavailable', message: 'Unavailable', details: [] }, 503)
    }
    if (path === '/account/refresh') return send({ access_token: 'fixture-session' })
    if (path === '/account/me') return send(screen === 'new' && state === 'empty' ? { ...user, default_organization_id: null } : user)
    if (path === '/account/mfa') return send({
      totp_enabled: enabled, enabled_at: enabled ? date : null, session_mfa: enabled,
      required_for_staff: false, required_by: [], sso_only: false, recovery_codes_left: enabled ? 2 : 0,
    })
    if (path === '/account/mfa/totp/setup') return send({
      secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/Library?secret=JBSWY3DPEHPK3PXP',
    })
    if (path === '/account/mfa/totp/enable') {
      enabled = true
      return send({ user, access_token: 'fixture-session', recovery_codes: ['ABCD-EFGH', 'JKLM-NPQR'] })
    }
    if (path === '/account/tokens' && method === 'GET') return send(tokens)
    if (path === '/account/tokens' && method === 'POST') {
      const next = { ...token, id: 'new-token', name: 'Export script', description: null }
      tokens = [next, ...tokens]
      return send({ ...next, token: 'fixture-token-shown-once' }, 201)
    }
    if (path === '/account/tokens/token-id' && method === 'DELETE') {
      tokens = tokens.map(item => item.id === token.id ? { ...item, revoked_at: date } : item)
      return ok()
    }
    if (path === '/orgs/invitations/pending') return items([])
    if (path === '/orgs') return items(screen === 'new' && state === 'empty' ? [] : [org])
    if (path === '/orgs/city-library/plan') return send({
      plan: { id: 'team', display_name: 'Team', allow_mcp: true },
      usage: { projects_used: projects.length, projects_cap: 3, api_tokens_used: 1, api_tokens_cap: 10, mcp_tokens_used: 0, mcp_tokens_cap: 5 },
      subscription: { status: 'active' }, upgrades: [],
    })
    if (path === '/projects' && method === 'GET') return items(projects)
    if (path === '/projects' && method === 'POST') {
      const body = request.postDataJSON()
      if (body.slug === project.slug) return send({ code: 'conflict', message: 'a project with this slug already exists', details: [] }, 409)
      const next = { ...project, name: body.name, description: body.description ?? null }
      projects = [next]
      return send(next, 201)
    }
    if (path === '/projects/' + projectId && method === 'DELETE') {
      projects = []
      return ok()
    }
    if (path.endsWith('/members')) return send([{ user_id: user.id, role: 'owner' }])
    if (path.endsWith('/validate')) return send({ valid: true, issues: [] })
    if (path.endsWith('/entities')) return items([{}])
    if (path.endsWith('/auth')) return send({ enabled: false })
    if (path.endsWith('/generations')) return items([])
    if (path.endsWith('/status')) return send({
      ready: true, next_step: { section: 'model', label: 'Add an entity' }, sections: [], issues: [], counts: {},
    })
    return send({ code: 'fixture_missing', message: 'Unexpected fixture request', details: [] }, 404)
  })
  return { release, bodies, recover: () => { unavailable = false } }
}

for (const screen of Object.keys(paths) as Screen[]) {
  for (const state of states) {
    test(`${screen} ${state}`, async ({ page }) => {
      const fixture = await mock(page, screen, state)
      try {
        await page.goto(paths[screen])
        await expect(page.getByRole('heading', { level: 1, name: { projects: 'Projects', new: 'Create a new project', account: 'Account' }[screen] })).toBeVisible()
        if (state === 'loading') {
          await expect(page.getByRole('status', { name: { projects: 'Loading projects…', new: 'Loading project owners…', account: 'Loading API tokens…' }[screen] })).toBeVisible()
        } else if (state === 'error') {
          await expect(page.getByRole('alert')).toBeVisible()
        } else if (screen === 'projects') {
          if (state === 'empty') await expect(page.getByRole('link', { name: 'Create a project' })).toBeVisible()
          else {
            await expect(page.getByRole('link', { name: 'Reading room' })).toBeVisible()
            await expect(page.getByRole('button', { name: 'Delete', exact: true })).toBeVisible()
            await expect(page.getByText('1 entity · No sign-in')).toBeVisible()
            await expect(page.getByText('1 of 3 projects in City Library')).toBeVisible()
          }
        } else if (screen === 'new') {
          await expect(page.getByRole('combobox', { name: 'Owner' })).toContainText(state === 'empty' ? 'Default personal organization' : 'City Library')
          if (state === 'normal') await expect(page.getByText('1 of 3 projects in City Library')).toBeVisible()
        } else {
          await expect(page.getByText(state === 'empty' ? 'No active tokens.' : 'CI pipeline', { exact: true })).toBeVisible()
        }
        if (screen === 'account') await expect(page.getByRole('button', { name: 'Turn on', exact: true })).toBeVisible()
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
        expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
        await screenshots[state](page, screen)
      } finally {
        fixture.release()
      }
    })
  }
}

test('creates a blank project after resolving a slug conflict', async ({ page }) => {
  const fixture = await mock(page, 'new', 'normal')
  await page.goto(paths.new)
  await page.getByRole('textbox', { name: 'Project name' }).fill('Meeting rooms')
  const slug = page.getByRole('textbox', { name: 'Slug (optional)' })
  await slug.fill(project.slug)
  await page.getByRole('radio', { name: /Start blank/ }).check()
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(slug).toHaveAttribute('aria-invalid', 'true')
  await slug.clear()
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/overview$`))
  expect(fixture.bodies['/projects']).toEqual([
    { name: 'Meeting rooms', organization_id: orgId, slug: project.slug },
    { name: 'Meeting rooms', organization_id: orgId },
  ])
})

test('filters by URL and confirms deletion', async ({ page }) => {
  await mock(page, 'projects', 'normal')
  await page.goto(paths.projects)
  await page.getByRole('searchbox', { name: 'Find a project' }).fill('missing')
  await expect(page).toHaveURL(/q=missing/)
  await expect(page.getByText('No projects match your filters.')).toBeVisible()
  await page.getByRole('button', { name: 'Clear filter' }).click()
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete project' }).click()
  await expect(page.getByRole('link', { name: 'Create a project' })).toBeVisible()
})

test('retries account tokens, reveals a new token once and acknowledges recovery codes', async ({ page, request }) => {
  const adapter = await request.get('/src/v2/features/entry/components/QrImage.tsx')
  await expect(adapter).toBeOK()
  const optimizedQr = (await adapter.text()).match(/"(\/[^"]*\/qrcode\.js)\?v=[^"]+"/)?.[1]
  if (!optimizedQr) throw new Error('Vite did not resolve the QR adapter’s optimized dependency')
  await expect.poll(async () => (await request.get(optimizedQr)).status()).toBe(200)

  const fixture = await mock(page, 'account', 'error')
  await page.goto(paths.account)
  await expect(page.getByText('Could not load your tokens.')).toBeVisible()
  fixture.recover()
  await page.getByRole('button', { name: 'Try again' }).click()
  await page.getByRole('button', { name: 'New token' }).click()
  const dialog = page.getByRole('dialog', { name: 'New API token' })
  await dialog.getByRole('textbox', { name: 'Name', exact: true }).fill('Export script')
  await expect(dialog.getByRole('button', { name: 'Create token' })).toBeDisabled()
  await dialog.getByRole('checkbox', { name: /^Read / }).check()
  await dialog.getByRole('button', { name: 'Create token' }).click()
  await expect(page.getByText('fixture-token-shown-once')).toBeVisible()
  await page.getByRole('button', { name: 'I have saved it' }).click()
  await expect(page.getByText('fixture-token-shown-once')).toHaveCount(0)
  await page.getByRole('button', { name: 'Turn on', exact: true }).click()
  await page.getByLabel('Your password', { exact: true }).fill('fixture-password')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByRole('img', { name: 'QR code for your authenticator app' })).toBeVisible()
  await page.getByLabel('Code from the app').fill('123456')
  await page.getByRole('button', { name: 'Turn on', exact: true }).click()
  await expect(page.getByText('ABCD-EFGH')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Continue', exact: true })).toBeDisabled()
  await page.getByRole('checkbox', { name: 'I saved my recovery codes' }).check()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByText('ABCD-EFGH')).toHaveCount(0)
})
