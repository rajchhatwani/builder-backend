import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { members, projectId, root, time, user } from './fixtures/connect-a'

const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]
const home = root + '/overview'
const headers = {
  'access-control-allow-origin': 'http://localhost:5299',
  'access-control-allow-credentials': 'true',
  'access-control-allow-methods': 'GET, POST, PATCH, DELETE, OPTIONS',
  'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id',
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
})

async function mock(page: Page, state: State, role = 'owner') {
  let release = () => {}
  const pending = new Promise<void>(resolve => { release = resolve })
  let failed = state === 'error'
  let roster = state === 'empty' ? [] : members.map(member => member.user_id === user.id ? { ...member, role } : member)
  const writes: { method: string; body?: unknown }[] = []
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    const fail = (code: string, status: number) => json({ code, details: [] }, status)
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (path === '/account/refresh') return json({ access_token: 'fixture' })
    if (path === '/account/me') return json(user)
    if (path === root) return json({ id: projectId, name: 'Warehouse', version: 3 })
    if (path === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (path === root + '/previews' || path === root + '/tokens') return json([])
    if (path === root + '/presence/heartbeat') return route.fulfill({ status: 204, headers })
    if (path === root + '/members' && method === 'GET') {
      if (state === 'loading') await pending
      return failed ? fail('internal_error', 500) : json(roster)
    }
    if (path === root + '/members' && method === 'POST') {
      const body = request.postDataJSON()
      writes.push({ method, body })
      if (roster.some(member => member.email === body.email)) return fail('conflict', 409)
      if (body.email !== 'new@example.test') return fail('user_unavailable', 404)
      const member = { user_id: 'new', name: 'New Teammate', email: body.email, role: body.role, mcp_enabled: false, created_at: time }
      roster = [...roster, member]
      return json(member, 201)
    }
    if (path.startsWith(root + '/members/')) {
      const id = path.split('/').at(-1)
      const member = roster.find(row => row.user_id === id)
      const body = request.postDataJSON()
      writes.push({ method, body: body ?? undefined })
      if (!member) return fail('not_found', 404)
      if (member.role === 'owner' && !roster.some(row => row.user_id !== id && row.role === 'owner')) return fail('last_owner', 409)
      if (method === 'PATCH') {
        const updated = { ...member, role: body.role }
        roster = roster.map(row => row.user_id === id ? updated : row)
        return json(updated)
      }
      roster = roster.filter(row => row.user_id !== id)
      return route.fulfill({ status: 204, headers })
    }
    return fail('not_found', 404)
  })
  return { release, writes, recover: () => { failed = false }, failRefresh: () => { failed = true } }
}

async function openShare(page: Page) {
  await page.goto(home)
  await expect(page.getByTestId('shell-project')).toHaveText('Warehouse')
  await page.getByRole('button', { name: 'Share', exact: true }).click()
  return page.getByRole('dialog', { name: 'People with access to Warehouse' })
}

for (const state of states) {
  test('projectshare ' + state, async ({ page }) => {
    const { release, recover } = await mock(page, state)
    try {
      const dialog = await openShare(page)
      await expect(state === 'normal' ? dialog.getByText('Mina Chen (you)', { exact: true })
        : state === 'loading' ? dialog.getByRole('status', { name: 'Loading project members…' })
        : state === 'empty' ? dialog.getByText('No members to show')
        : dialog.getByText("Can't load the members.")).toBeVisible()
      await page.evaluate(() => document.fonts.ready)
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => innerWidth))
      const results = await new AxeBuilder({ page }).analyze()
      expect(results.violations.map(({ id, nodes }) => ({ id, targets: nodes.map(node => node.target) }))).toEqual([])
      if (state === 'normal') await expect(page).toHaveScreenshot('projectshare-normal.png', { fullPage: true })
      if (state === 'loading') await expect(page).toHaveScreenshot('projectshare-loading.png', { fullPage: true })
      if (state === 'empty') await expect(page).toHaveScreenshot('projectshare-empty.png', { fullPage: true })
      if (state === 'error') {
        await expect(page).toHaveScreenshot('projectshare-error.png', { fullPage: true })
        recover()
        await dialog.getByRole('button', { name: 'Retry' }).click()
        await expect(dialog.getByText('Mina Chen (you)')).toBeVisible()
      }
    } finally { release() }
  })
}

test('viewer can open Share with the palette and inspect access', async ({ page }) => {
  await mock(page, 'normal', 'viewer')
  await page.goto(home)
  await page.getByRole('button', { name: /Search or jump to/ }).click()
  const search = page.getByRole('combobox', { name: 'Search commands' })
  await search.fill('Share project')
  await search.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'People with access to Warehouse' })
  await expect(dialog.getByText('Only owners can change who has access.')).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0)
  await dialog.getByText('Access diagram').click()
  await expect(dialog.getByText('Alex Bench · Editor · MCP Off')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Share', exact: true })).toBeFocused()
})

test('owner can add, change roles, confirm removal and open Integrations', async ({ page }) => {
  const { writes } = await mock(page, 'normal')
  const dialog = await openShare(page)
  const email = dialog.getByRole('textbox', { name: 'Email' })
  const add = dialog.getByRole('button', { name: 'Add', exact: true })
  await email.fill('bad')
  await add.click()
  await expect(email).toBeFocused()
  await expect(email).toHaveAttribute('aria-invalid', 'true')
  expect(writes).toEqual([])
  await email.fill('missing@example.test')
  await add.click()
  await expect(dialog.getByText('no active account with that e-mail in this organization')).toBeVisible()
  await expect(email).toHaveValue('missing@example.test')
  await email.fill(user.email)
  await add.click()
  await expect(dialog.getByText('already a member')).toBeVisible()
  await expect(email).toHaveValue(user.email)
  await email.fill('new@example.test')
  await add.click()
  await expect(dialog.getByText('New Teammate', { exact: true })).toBeVisible()
  await expect(email).toHaveValue('')
  const role = dialog.getByRole('combobox', { name: 'Role of new@example.test' })
  await role.click()
  await page.getByRole('option', { name: 'Editor', exact: true }).click()
  await expect(role).toContainText('Editor')
  await dialog.getByRole('button', { name: 'Remove new@example.test' }).click()
  const confirm = page.getByRole('dialog', { name: 'Remove new@example.test?' })
  await confirm.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog.getByText('New Teammate', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Remove new@example.test' }).click()
  await confirm.getByRole('button', { name: 'Remove', exact: true }).click()
  await expect(dialog.getByText('New Teammate', { exact: true })).toHaveCount(0)
  expect(writes.slice(-3)).toEqual([
    { method: 'POST', body: { email: 'new@example.test', role: 'viewer' } },
    { method: 'PATCH', body: { role: 'editor' } },
    { method: 'DELETE' },
  ])
  await dialog.getByRole('button', { name: 'Integrations' }).click()
  await expect(page).toHaveURL(root + '/integrations')
})

test('last owner sees the domain conflict and can dismiss the confirmation', async ({ page }) => {
  await mock(page, 'normal')
  const dialog = await openShare(page)
  await dialog.getByRole('button', { name: 'Remove ' + user.email }).click()
  const confirm = page.getByRole('dialog', { name: 'Remove ' + user.email + '?' })
  await confirm.getByRole('button', { name: 'Remove', exact: true }).click()
  const reason = 'a project needs at least one owner; make someone else an owner first'
  await expect(confirm.getByText(reason)).toBeVisible()
  await confirm.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog.getByText(reason)).toBeVisible()
  await expect(dialog.getByText('Mina Chen (you)')).toBeVisible()
})

test('a committed add clears the email even if the roster refresh fails', async ({ page }) => {
  const { failRefresh, recover, writes } = await mock(page, 'normal')
  const dialog = await openShare(page)
  const email = dialog.getByRole('textbox', { name: 'Email' })
  await email.fill('new@example.test')
  failRefresh()
  await dialog.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(dialog.getByText("Can't load the members.")).toBeVisible()
  recover()
  await dialog.getByRole('button', { name: 'Retry' }).click()
  await expect(dialog.getByText('New Teammate', { exact: true })).toBeVisible()
  await expect(email).toHaveValue('')
  expect(writes).toHaveLength(1)
})
