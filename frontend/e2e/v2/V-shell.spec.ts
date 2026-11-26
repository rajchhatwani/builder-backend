import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const project = '95ff34eb-4d07-4a60-8669-aaf1cf5442ca'
const root = '/projects/' + project
const home = root + '/overview'
const user = { id: 'me', name: 'Mina Chen', email: 'mina@example.test', platform_role: 'customer', email_verified_at: '2026-01-01' }
const issue = { path: 'auth.keycloak.realm', code: 'suite_realm_derived', message: 'Set the realm to inventory.' }
const suggestion = { id: 'consider_auth', title: 'Decide how people sign in', reason: 'Your API has no user accounts yet.', section: 'auth' }
const sectionNames = [
  ['model', 'Data model'], ['auth', 'Sign-in'], ['authorization', 'Roles and access'], ['payments', 'Payments'],
  ['storage', 'File storage'], ['observability', 'Observability'], ['deployment', 'Deployment'], ['documents', 'Documents'],
  ['state_machines', 'State machines'], ['settings', 'Settings, sequences and lists'], ['history', 'Change history'], ['hooks', 'Custom hooks'], ['seed', 'Seed data'],
]
const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]
type Surface = 'overview' | 'shellglobal'

async function mock(page: Page, surface: Surface, state: State, role = 'editor', blocked = false) {
  const heldPath = surface === 'overview' ? root + '/status' : root + '/members'
  let release = () => {}
  const pending = new Promise<void>(resolve => { release = resolve })
  let dismissed = false
  let failed = state === 'error'
  const empty = state === 'empty' && surface === 'overview'
  const fixture = () => ({
    ready: !empty && !blocked, issues: blocked ? [issue] : [],
    counts: { entities: empty ? 0 : 2, relations: 0, state_machines: 0, settings: 0, sequences: 0, lists: 0, history_configs: 0, hooks: 0, seed_profiles: 0 },
    sections: sectionNames.map(([id, label]) => ({ id, label, configured: !empty && (id === 'model' || id === 'storage'), issue_count: blocked && id === 'auth' ? 1 : 0 })),
    next_step: empty ? { id: 'add_entity', title: 'Add your first entity', reason: 'A backend needs at least one thing to store.', section: 'model' }
      : blocked ? { id: 'fix_issues', title: 'Fix 1 problem before generating', reason: issue.message, section: 'auth' }
      : dismissed ? { id: 'generate', title: 'Generate your backend', reason: 'The model is valid and nothing is left to fix.', section: 'generate' }
      : suggestion,
    dismissed_steps: dismissed ? [{ ...suggestion, dismissed: true }] : [],
  })
  await page.route(url => url.port === '8000', async route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299',
      'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, POST, DELETE, OPTIONS',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id',
    }
    const json = (value: unknown, status = 200) => route.fulfill({ status, headers, json: value })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (path === heldPath) {
      if (state === 'loading') await pending
      if (failed) return json({ code: 'fixture', details: [] }, 500)
    }
    if (path === '/account/refresh') return json({ access_token: 'fixture' })
    if (path === '/account/me') return json(user)
    if (path === '/orgs') return json({ items: [{ id: 'org', name: 'Inventory Co', slug: 'inventory', kind: 'team' }] })
    if (path === root) return json({ id: project, name: 'Inventory', organization_id: 'org', version: 3 })
    if (path === root + '/status') return json(fixture())
    if (path.startsWith(root + '/status/dismiss')) {
      dismissed = method === 'POST'
      return json(fixture())
    }
    if (path === root + '/members') return json(state === 'empty' && surface === 'shellglobal' ? [] : [
      { user_id: 'me', name: user.name, email: user.email, role, mcp_enabled: false },
      { user_id: 'ari', name: 'Ari Kim', email: 'ari@example.test', role: 'viewer', mcp_enabled: false },
    ])
    if (path === root + '/storage') return json({ enabled: true })
    if (path === root + '/generations' || path === root + '/roles') return json({ items: [], total: 0 })
    if (path === root + '/previews') return json([])
    if (path === root + '/presence/heartbeat') return route.fulfill({ status: 204, headers })
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, recover: () => { failed = false } }
}

async function capture(page: Page, surface: Surface, state: State) {
  await page.evaluate(() => document.fonts.ready)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth))
  const results = await new AxeBuilder({ page }).analyze()
  expect(results.violations.map(({ id, nodes }) => ({ id, targets: nodes.map(node => node.target) }))).toEqual([])
  if (state === 'normal') await expect(page).toHaveScreenshot(surface + '-normal.png', { fullPage: true })
  if (state === 'loading') await expect(page).toHaveScreenshot(surface + '-loading.png', { fullPage: true })
  if (state === 'empty') await expect(page).toHaveScreenshot(surface + '-empty.png', { fullPage: true })
  if (state === 'error') await expect(page).toHaveScreenshot(surface + '-error.png', { fullPage: true })
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
})

for (const state of states) {
  test('overview ' + state, async ({ page }) => {
    const { release, recover } = await mock(page, 'overview', state)
    try {
      await page.goto(home)
      await expect(page.getByTestId('shell-project')).toHaveText('Inventory')
      await expect(page.getByRole('link', { name: 'Inventory Co' })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Updates paused, presence' })).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Home', exact: true })).toBeVisible()
      await expect(state === 'normal' ? page.getByTestId('readiness-banner')
        : state === 'loading' ? page.getByRole('status', { name: 'Loading project status…' })
        : state === 'empty' ? page.getByRole('heading', { name: 'Add your first entity' }).last()
        : page.getByText('We could not load the project status')).toBeVisible()
      if (state === 'normal' || state === 'empty') await expect(page.getByText('Design your data')).toBeVisible()
      await capture(page, 'overview', state)
      if (state === 'error') {
        recover()
        await page.getByRole('button', { name: 'Try again' }).click()
        await expect(page.getByTestId('readiness-banner')).toBeVisible()
      }
    } finally { release() }
  })

  test('shellglobal ' + state, async ({ page }) => {
    const { release, recover } = await mock(page, 'shellglobal', state)
    try {
      await page.goto(home)
      await expect(page.getByTestId('shell-project')).toHaveText('Inventory')
      await expect(page.getByRole('link', { name: 'Inventory Co' })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Updates paused, presence' })).toBeVisible()
      await page.getByRole('button', { name: 'Share', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: 'People with access to Inventory' })
      await expect(dialog).toBeVisible()
      const rosterMember = dialog.getByRole('table', { name: 'Who can access this project' })
        .getByText('Ari Kim', { exact: true })
      await expect(state === 'normal' ? rosterMember
        : state === 'loading' ? dialog.getByRole('status', { name: 'Loading project members…' })
        : state === 'empty' ? dialog.getByText('No members to show')
        : dialog.getByText("Can't load the members.")).toBeVisible()
      if (state === 'error') {
        recover()
        await dialog.getByRole('button', { name: 'Retry' }).click()
        await expect(rosterMember).toBeVisible()
      }
    } finally { release() }
  })
}

test('restores a dismissed suggestion', async ({ page }) => {
  await mock(page, 'overview', 'normal')
  await page.goto(home)
  await page.getByRole('button', { name: 'Not now' }).click()
  await expect(page.getByTestId('next-step')).toHaveAttribute('data-step-id', 'generate')
  await page.getByRole('button', { name: 'Show again' }).click()
  await expect(page.getByTestId('next-step')).toHaveAttribute('data-step-id', 'consider_auth')
})

test('routes Keycloak issues, even from a previously issued project link', async ({ page }) => {
  await mock(page, 'overview', 'normal', 'viewer', true)
  await page.goto('/#/p/' + project + '/overview')
  await expect(page).toHaveURL(home)
  await expect(page.getByRole('link', { name: 'Fix it' })).toHaveAttribute('href', root + '/keycloak')
  await expect(page.getByText('Only project editors and owners can dismiss or restore steps.')).toBeVisible()
})

test('jumps from the command palette and opens the Workbench with a preview CTA', async ({ page }) => {
  await mock(page, 'overview', 'normal')
  await page.goto(home)
  await page.getByRole('button', { name: /Search or jump to/ }).waitFor()
  await page.keyboard.press('Control+k')
  const search = page.getByRole('combobox', { name: 'Search commands' })
  await expect(search).toBeFocused()
  await search.fill('data model')
  await search.press('Enter')
  await expect(page).toHaveURL(root + '/model')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const more = page.getByRole('button', { name: 'More', exact: true })
  await more.click()
  await page.getByRole('menuitem', { name: 'Workbench' }).click()
  await expect(page.getByRole('dialog', { name: 'Workbench' }).getByRole('link', { name: 'See it work' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(more).toBeFocused()
})
